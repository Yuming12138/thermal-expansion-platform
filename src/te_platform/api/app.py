from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
import re
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from te_platform import __version__
from te_platform.api.services import (
    active_dataset_summary,
    ensure_catalog_database,
    ensure_workspace_database,
)
from te_platform.api.structures import inspect_structure
from te_platform.catalog.queries import (
    compare_materials,
    dataset_summary,
    material_detail,
    material_element_statistics,
    material_landscape,
    search_materials,
)
from te_platform.composites.rom import optimize_zte_fraction
from te_platform.composites.curve_rom import optimize_curve_rom
from te_platform.composites.material_pair import curve_materials, optimize_material_pair
from te_platform.config import (
    DEFAULT_PTE_RELEASE_SLUG,
    DEFAULT_RELEASE_SLUG,
    catalog_database_path,
    copyright_owner,
    workspace_database_path,
)
from te_platform.screening.fast_sbr import fast_screen_sbr
from te_platform.screening.sbr import classify_sbr
from te_platform.structures import build_structure_view
from te_platform.workers.alignn_runner import predict_alignn_shear
from te_platform.workers.mattersim_runner import predict_mattersim_descriptors
from te_platform.agent.tools import default_registry
from te_platform.agent.actions import (
    PENDING_APPROVAL,
    claim_action_request,
    complete_action_request,
    fail_action_request,
    list_action_requests,
    reject_action_request,
)
from te_platform.agent.uploads import (
    find_agent_structure,
    inspect_agent_structure,
    store_agent_structure,
)
from te_platform.agent.llm import (
    AgentNotConfiguredError,
    AgentUpstreamError,
    capability as agent_capability,
    chat_with_model,
)
from te_platform.jobs.precision_runner import (
    precision_progress,
    refresh_precision_result,
    resume_precision_qha,
    submit_elastic_job,
    submit_fast_screen_job,
    submit_precision_job,
    submit_qha_job,
)
from te_platform.jobs.repository import get_job
from te_platform.precision.wsl_executor import PrecisionTaskConfig
from te_platform.reports import build_comparison_report_pdf, build_material_curve_pdf


WEB_DIRECTORY = Path(__file__).resolve().parents[1] / "web"


def _download_filename(material_key: str, suffix: str) -> str:
    stem = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", material_key).strip(" ._") or "material"
    return f"{stem}_{suffix}"


def _attachment_headers(filename: str) -> dict[str, str]:
    ascii_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "download"
    encoded_filename = quote(filename, safe="")
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'
        )
    }


class SBRRequest(BaseModel):
    shear_modulus_gpa: float = Field(ge=0)
    bonding_modulus_gpa: float = Field(gt=0)


class FastSBRRequest(BaseModel):
    predicted_shear_modulus_gpa: float = Field(ge=0)
    cohesive_energy_ev_per_atom: float
    cell_volume_a3: float = Field(gt=0)
    atom_count: int = Field(gt=0)
    average_coordination_number: float = Field(gt=0)
    shear_model_mae_gpa: float = Field(default=9.476007, ge=0)


class ROMRequest(BaseModel):
    alpha_pte: float
    alpha_nte: float
    target_alpha: float = 0.0


class CurveROMRequest(BaseModel):
    pte_alpha: list[float] = Field(min_length=2)
    nte_alpha: list[float] = Field(min_length=2)
    target_alpha: float = 0.0
    pte_density: float | None = Field(default=None, gt=0)
    nte_density: float | None = Field(default=None, gt=0)


class MaterialPairCurveRequest(BaseModel):
    pte_material_key: str = Field(min_length=1)
    nte_material_key: str = Field(min_length=1)
    temperature_min_k: float = Field(default=300.0, ge=0)
    temperature_max_k: float = Field(default=800.0, gt=0)
    target_alpha_ppm_per_k: float = 0.0


class AgentToolRequest(BaseModel):
    tool: str
    arguments: dict[str, object] = Field(default_factory=dict)


class AgentHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    history: list[AgentHistoryMessage] = Field(default_factory=list, max_length=12)
    attachments: list[str] = Field(default_factory=list, max_length=3)


def create_app(
    catalog_database: Path | None = None,
    workspace_database: Path | None = None,
    *,
    database: Path | None = None,
) -> FastAPI:
    if database is not None:
        catalog_database = database
        workspace_database = database
    catalog_db = catalog_database or catalog_database_path()
    workspace_db = workspace_database or workspace_database_path()
    allow_catalog_download = catalog_database is None and database is None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ensure_catalog_database(catalog_db, allow_download=allow_catalog_download)
        ensure_workspace_database(workspace_db)
        yield

    app = FastAPI(
        title="热膨胀材料智能计算与设计平台",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=WEB_DIRECTORY), name="static")
    agent_tools = default_registry(catalog_db, workspace_db)

    @app.get("/", include_in_schema=False)
    @app.get("/database", include_in_schema=False)
    @app.get("/predict", include_in_schema=False)
    @app.get("/landscape", include_in_schema=False)
    @app.get("/zte", include_in_schema=False)
    @app.get("/about", include_in_schema=False)
    def web_home() -> FileResponse:
        return FileResponse(WEB_DIRECTORY / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, object]:
        summary = active_dataset_summary(catalog_db)
        return {
            "status": "ok",
            "dataset_release": summary["release"]["slug"],
            "material_count": summary["counts"]["materials"],
            "catalog_database": catalog_db.name,
            "workspace_database": workspace_db.name,
        }

    @app.get("/api/about")
    def about() -> dict[str, object]:
        nte = active_dataset_summary(catalog_db)
        pte = dataset_summary(catalog_db, DEFAULT_PTE_RELEASE_SLUG)
        return {
            "software": {
                "name_zh": "热膨胀材料智能计算与设计平台",
                "name_en": "Thermal Expansion Materials Platform",
                "version": __version__,
                "copyright_owner": copyright_owner(),
                "repository": "https://github.com/Yuming12138/thermal-expansion-platform",
            },
            "descriptor": {
                "name": "剪切—键合描述符",
                "formula": "xi = G/E_tilde",
                "bonding_modulus": "E_tilde = U_V/n = 160.21766208*abs(E_coh)/(AAV*avg_cn)",
                "formal_boundary": 2.84151,
            },
            "datasets": {
                "nte": nte["release"],
                "nte_materials": nte["counts"]["materials"],
                "pte": pte["release"],
                "pte_materials": pte["counts"]["materials"],
                "catalog_materials": nte["counts"]["materials"] + pte["counts"]["materials"],
            },
            "technology": [
                "FastAPI", "SQLite", "pymatgen/CrystalNN", "3Dmol.js",
                "ALIGNN", "MatterSim", "Phonopy", "VASPKIT",
            ],
            "scientific_scope": (
                "G/E_tilde用于固定相、声子驱动的体热膨胀符号筛选；"
                "精确alpha(T)需要QHA或更高层级计算。"
            ),
        }

    @app.get("/api/agent/tools")
    def agent_tool_names() -> dict[str, object]:
        return {
            "tools": agent_tools.names(model_visible_only=True),
            "architecture": "general_primitives_with_approval_gated_tasks",
        }

    @app.get("/api/agent/capability")
    def agent_model_capability() -> dict[str, object]:
        return agent_capability()

    @app.post("/api/agent/call")
    def agent_call(request: AgentToolRequest) -> dict[str, object]:
        try:
            return {"tool": request.tool, "result": agent_tools.call(request.tool, **request.arguments)}
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/agent/chat")
    async def agent_chat(request: AgentChatRequest) -> dict[str, object]:
        try:
            attachments = [
                inspect_agent_structure(workspace_db, structure_id)
                for structure_id in request.attachments
            ]
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            return await chat_with_model(
                request.message,
                agent_tools,
                history=[item.model_dump() for item in request.history],
                attachments=attachments,
                pending_actions=[
                    {
                        "approval_id": item["id"],
                        "summary": item["summary"],
                        "created_at": item["created_at"],
                    }
                    for item in list_action_requests(
                        workspace_db,
                        status=PENDING_APPROVAL,
                        limit=5,
                    )
                ],
            )
        except AgentNotConfiguredError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except AgentUpstreamError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/api/agent/structures")
    async def agent_structure_upload(file: UploadFile = File(...)) -> dict[str, object]:
        if not file.filename:
            raise HTTPException(status_code=400, detail="A structure filename is required")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded structure is empty")
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Structure file exceeds 5 MB")
        try:
            return store_agent_structure(
                workspace_db,
                filename=file.filename,
                content=content,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/agent/approvals/{action_id}/approve")
    def approve_agent_action(action_id: str) -> dict[str, object]:
        claimed = False
        try:
            action = claim_action_request(workspace_db, action_id)
            claimed = True
            if action["action"] not in {
                "submit_qha_calculation",
                "submit_structure_calculation",
            }:
                raise ValueError(f"Unsupported Agent action: {action['action']}")
            arguments = action["arguments"]
            structure_path = find_agent_structure(
                workspace_db, str(arguments["structure_id"])
            )
            config = PrecisionTaskConfig(**arguments["config"])
            mode = arguments.get("mode", "qha")
            submitter = {
                "fast": lambda: submit_fast_screen_job(
                    workspace_db,
                    structure_path.read_bytes(),
                    filename=structure_path.name,
                ),
                "elastic": lambda: submit_elastic_job(
                    workspace_db,
                    structure_path.read_bytes(),
                    config,
                    filename=structure_path.name,
                ),
                "qha": lambda: submit_qha_job(
                    workspace_db,
                    structure_path.read_bytes(),
                    config,
                    filename=structure_path.name,
                ),
            }.get(mode)
            if submitter is None:
                raise ValueError(f"Unsupported calculation mode: {mode}")
            job = submitter()
            completed = complete_action_request(
                workspace_db,
                action_id,
                {"job_id": job["id"], "workflow": job["workflow"]},
            )
            return {"approval": completed, "job": job}
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            if claimed:
                try:
                    fail_action_request(workspace_db, action_id, str(error))
                except ValueError:
                    pass
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/agent/approvals")
    def agent_action_requests(
        status: Literal[
            "PENDING_APPROVAL", "APPROVED", "EXECUTED", "REJECTED", "FAILED"
        ] = "PENDING_APPROVAL",
        limit: int = Query(default=10, ge=1, le=100),
    ) -> dict[str, object]:
        return {
            "status": status,
            "requests": list_action_requests(workspace_db, status=status, limit=limit),
        }

    @app.post("/api/agent/approvals/{action_id}/reject")
    def reject_agent_action(action_id: str) -> dict[str, object]:
        try:
            return {"approval": reject_action_request(workspace_db, action_id)}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/datasets/current")
    def current_dataset() -> dict[str, object]:
        return active_dataset_summary(catalog_db)

    @app.get("/api/materials")
    def materials(
        query: str = "",
        limit: int = Query(default=50, ge=1, le=500),
        elements: str = Query(default="", max_length=256),
        element_mode: Literal["contains", "exact"] = "contains",
        sort_by: Literal["material_key", "G_GPa", "E_tilde_GPa", "CTE_ppm", "xi"] = "material_key",
        sort_order: Literal["ascending", "descending"] = "ascending",
        cte_min_ppm: float | None = None,
        cte_max_ppm: float | None = None,
    ) -> list[dict[str, object]]:
        ensure_catalog_database(catalog_db)
        selected_elements = [
            item[:1].upper() + item[1:].lower()
            for item in (part.strip() for part in elements.split(","))
            if item
        ]
        try:
            return search_materials(
                catalog_db,
                DEFAULT_RELEASE_SLUG,
                query,
                limit,
                elements=selected_elements,
                element_mode=element_mode,
                sort_by=sort_by,
                sort_order=sort_order,
                cte_min_ppm=cte_min_ppm,
                cte_max_ppm=cte_max_ppm,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/materials/landscape")
    def landscape(
        limit: int = Query(default=1600, ge=1, le=7001),
    ) -> list[dict[str, object]]:
        ensure_catalog_database(catalog_db)
        return material_landscape(catalog_db, DEFAULT_RELEASE_SLUG, limit)

    @app.get("/api/materials/elements")
    def material_elements() -> dict[str, object]:
        ensure_catalog_database(catalog_db)
        return material_element_statistics(catalog_db, DEFAULT_RELEASE_SLUG)

    @app.get("/api/materials/compare")
    def material_comparison(
        material_keys: str = Query(min_length=3, max_length=2048),
        temperature_k: float = Query(default=300.0, ge=0),
    ) -> dict[str, object]:
        ensure_catalog_database(catalog_db)
        try:
            return compare_materials(
                catalog_db,
                DEFAULT_RELEASE_SLUG,
                material_keys.split("|"),
                temperature_k=temperature_k,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/materials/compare/report.pdf")
    def material_comparison_pdf(
        material_keys: str = Query(min_length=3, max_length=2048),
        temperature_k: float = Query(default=300.0, ge=0),
        project_name: str = Query(default="Material comparison", min_length=1, max_length=120),
    ) -> Response:
        ensure_catalog_database(catalog_db)
        try:
            comparison = compare_materials(
                catalog_db,
                DEFAULT_RELEASE_SLUG,
                material_keys.split("|"),
                temperature_k=temperature_k,
            )
            content = build_comparison_report_pdf(comparison, project_name=project_name.strip())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        filename = _download_filename(project_name, "comparison_report.pdf")
        return Response(
            content=content,
            media_type="application/pdf",
            headers=_attachment_headers(filename),
        )

    @app.get("/api/materials/{material_key}/download/POSCAR")
    def material_poscar_download(material_key: str) -> Response:
        ensure_catalog_database(catalog_db)
        try:
            detail = material_detail(catalog_db, DEFAULT_RELEASE_SLUG, material_key)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        structure = next(
            (
                item
                for item in detail["structures"]
                if str(item.get("format", "")).upper() == "POSCAR" and item.get("content")
            ),
            None,
        )
        if structure is None:
            raise HTTPException(status_code=404, detail="Material has no stored POSCAR")
        filename = _download_filename(material_key, "POSCAR")
        content = str(structure["content"])
        if not content.endswith("\n"):
            content += "\n"
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers=_attachment_headers(filename),
        )

    @app.get("/api/materials/{material_key}/download/thermal_expansion.dat")
    def material_thermal_expansion_download(material_key: str) -> Response:
        ensure_catalog_database(catalog_db)
        try:
            detail = material_detail(catalog_db, DEFAULT_RELEASE_SLUG, material_key)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        curve = detail.get("precision_thermal_expansion")
        if not curve:
            raise HTTPException(status_code=404, detail="Material has no stored thermal-expansion curve")
        release = detail.get("dataset_release") or {}
        lines = [
            f"# material_key: {material_key}",
            f"# dataset_release: {release.get('slug', '')} version={release.get('version', '')}",
            f"# qha_job_id: {curve.get('job_id', '')}",
            "# columns: temperature_K volumetric_thermal_expansion_coefficient_1_per_K",
        ]
        lines.extend(
            f"{float(point['temperature_k']):.8f} {float(point['alpha_ppm_per_k']) / 1_000_000:.12e}"
            for point in curve["points"]
        )
        filename = _download_filename(material_key, "thermal_expansion.dat")
        return Response(
            content="\n".join(lines) + "\n",
            media_type="text/plain; charset=utf-8",
            headers=_attachment_headers(filename),
        )

    @app.get("/api/materials/{material_key}/download/thermal_expansion.pdf")
    def material_thermal_expansion_pdf(material_key: str) -> Response:
        ensure_catalog_database(catalog_db)
        try:
            detail = material_detail(catalog_db, DEFAULT_RELEASE_SLUG, material_key)
            content = build_material_curve_pdf(detail)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        filename = _download_filename(material_key, "thermal_expansion.pdf")
        return Response(
            content=content,
            media_type="application/pdf",
            headers=_attachment_headers(filename),
        )

    @app.get("/api/materials/{material_key}")
    def material(material_key: str) -> dict[str, object]:
        ensure_catalog_database(catalog_db)
        try:
            detail = material_detail(catalog_db, DEFAULT_RELEASE_SLUG, material_key)
            structure = next(
                (item for item in detail["structures"] if item.get("content")),
                None,
            )
            if structure:
                try:
                    detail["structure_view"] = build_structure_view(
                        structure["content"], structure["format"]
                    )
                except Exception:  # Keep material details available if scene generation fails.
                    detail["structure_view"] = None
            else:
                detail["structure_view"] = None
            return detail
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/sbr/classify")
    def sbr_classify(request: SBRRequest) -> dict[str, object]:
        return classify_sbr(
            request.shear_modulus_gpa,
            request.bonding_modulus_gpa,
        ).to_dict()

    @app.post("/api/sbr/fast-screen")
    def sbr_fast_screen(request: FastSBRRequest) -> dict[str, object]:
        return fast_screen_sbr(
            request.predicted_shear_modulus_gpa,
            request.cohesive_energy_ev_per_atom,
            request.cell_volume_a3,
            request.atom_count,
            request.average_coordination_number,
            shear_model_mae_gpa=request.shear_model_mae_gpa,
        ).to_dict()

    @app.post("/api/composites/rom")
    def composite_rom(request: ROMRequest) -> dict[str, object]:
        return optimize_zte_fraction(
            request.alpha_pte,
            request.alpha_nte,
            request.target_alpha,
        ).to_dict()

    @app.post("/api/composites/curve-rom")
    def composite_curve_rom(request: CurveROMRequest) -> dict[str, object]:
        try:
            return optimize_curve_rom(
                request.pte_alpha,
                request.nte_alpha,
                request.target_alpha,
                pte_density=request.pte_density,
                nte_density=request.nte_density,
            ).to_dict()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/composites/materials")
    def composite_materials(
        role: str,
        query: str = "",
        limit: int = Query(default=30, ge=1, le=100),
    ) -> list[dict[str, object]]:
        release_slug = {
            "pte": DEFAULT_PTE_RELEASE_SLUG,
            "nte": DEFAULT_RELEASE_SLUG,
        }.get(role.lower())
        if release_slug is None:
            raise HTTPException(status_code=422, detail="role must be 'pte' or 'nte'")
        try:
            return curve_materials(
                catalog_db,
                release_slug,
                query,
                limit,
                alpha_sign=1 if role.lower() == "pte" else -1,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/composites/curve-design")
    def composite_curve_design(request: MaterialPairCurveRequest) -> dict[str, object]:
        try:
            return optimize_material_pair(
                catalog_db,
                pte_release_slug=DEFAULT_PTE_RELEASE_SLUG,
                nte_release_slug=DEFAULT_RELEASE_SLUG,
                pte_material_key=request.pte_material_key,
                nte_material_key=request.nte_material_key,
                temperature_min_k=request.temperature_min_k,
                temperature_max_k=request.temperature_max_k,
                target_alpha_ppm_per_k=request.target_alpha_ppm_per_k,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/structures/inspect")
    async def structure_inspect(file: UploadFile = File(...)) -> dict[str, object]:
        if not file.filename:
            raise HTTPException(status_code=400, detail="A structure filename is required")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded structure is empty")
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Structure file exceeds 5 MB")
        try:
            result = inspect_structure(file.filename, content)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "filename": file.filename,
            "bytes": len(content),
            "inspection": result.to_dict(),
            "next_step": (
                "Use the ALIGNN worker to predict G, then calculate paper-defined E_tilde=U_V/n "
                "and return the fast SBR result."
            ),
        }

    @app.post("/api/structures/alignn-shear")
    async def alignn_shear(file: UploadFile = File(...)) -> dict[str, object]:
        if not file.filename:
            raise HTTPException(status_code=400, detail="A structure filename is required")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded structure is empty")
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Structure file exceeds 5 MB")
        try:
            inspection = inspect_structure(file.filename, content)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        suffix = Path(file.filename).suffix.lower() or ".vasp"
        structure_hash = sha256(content).hexdigest()
        upload_directory = workspace_db.parent / "uploads"
        upload_directory.mkdir(parents=True, exist_ok=True)
        structure_path = upload_directory / f"{structure_hash}{suffix}"
        if not structure_path.exists():
            structure_path.write_bytes(content)
        try:
            prediction = predict_alignn_shear(structure_path)
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {
            "structure_sha256": structure_hash,
            "inspection": inspection.to_dict(),
            "alignn": prediction.to_dict(),
            "next_step": (
                "Run MatterSim cohesive-energy and CrystalNN coordination workers "
                "to calculate paper-defined E_tilde=U_V/n and the fast SBR result."
            ),
        }

    @app.post("/api/structures/fast-screen")
    async def structure_fast_screen(file: UploadFile = File(...)) -> dict[str, object]:
        if not file.filename:
            raise HTTPException(status_code=400, detail="A structure filename is required")
        content = await file.read()
        if not content or len(content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Structure must be between 1 byte and 5 MB")
        try:
            inspection = inspect_structure(file.filename, content)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        suffix = Path(file.filename).suffix.lower() or ".vasp"
        structure_hash = sha256(content).hexdigest()
        upload_directory = workspace_db.parent / "uploads"
        upload_directory.mkdir(parents=True, exist_ok=True)
        structure_path = upload_directory / f"{structure_hash}{suffix}"
        if not structure_path.exists():
            structure_path.write_bytes(content)
        try:
            alignn = predict_alignn_shear(structure_path)
            mattersim = predict_mattersim_descriptors(structure_path)
            descriptors = mattersim.descriptors
            result = fast_screen_sbr(
                float(alignn.prediction["shear_modulus_gpa"]),
                float(descriptors["cohesive_energy_ev_per_atom"]),
                float(inspection.cell_volume_a3 or 0.0),
                int(descriptors["atom_count"]),
                float(descriptors["average_coordination_number"]),
            )
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {
            "structure_sha256": structure_hash,
            "inspection": inspection.to_dict(),
            "alignn": alignn.to_dict(),
            "mattersim": mattersim.to_dict(),
            "fast_sbr": result.to_dict(),
            "next_step": "Use full elastic tensor and QHA for a high-confidence alpha(T) result.",
        }

    @app.post("/api/precision/jobs")
    async def submit_precision(file: UploadFile = File(...)) -> dict[str, object]:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded structure is empty")
        try:
            inspect_structure(file.filename or "POSCAR", content)
            return submit_precision_job(
                workspace_db, content, PrecisionTaskConfig(), filename=file.filename or "POSCAR"
            )
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/precision/elastic-jobs")
    async def submit_elastic(file: UploadFile = File(...)) -> dict[str, object]:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded structure is empty")
        try:
            inspect_structure(file.filename or "POSCAR", content)
            return submit_elastic_job(
                workspace_db, content, PrecisionTaskConfig(), filename=file.filename or "POSCAR"
            )
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/precision/qha-jobs")
    async def submit_qha(file: UploadFile = File(...)) -> dict[str, object]:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded structure is empty")
        try:
            inspect_structure(file.filename or "POSCAR", content)
            return submit_qha_job(
                workspace_db, content, PrecisionTaskConfig(), filename=file.filename or "POSCAR"
            )
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/precision/jobs/{job_id}")
    def precision_job(job_id: str) -> dict[str, object]:
        try:
            job = get_job(workspace_db, job_id)
            job["progress"] = precision_progress(workspace_db, job_id)
            return job
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/precision/jobs/{job_id}/resume-qha")
    def resume_qha_job(job_id: str) -> dict[str, object]:
        try:
            return resume_precision_qha(workspace_db, job_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/precision/jobs/{job_id}/refresh-result")
    def refresh_precision_job_result(job_id: str) -> dict[str, object]:
        try:
            return refresh_precision_result(workspace_db, job_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return app


app = create_app()
