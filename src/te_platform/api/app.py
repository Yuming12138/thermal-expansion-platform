from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from te_platform.api.services import (
    active_dataset_summary,
    ensure_catalog_database,
    ensure_workspace_database,
)
from te_platform.api.structures import inspect_structure
from te_platform.catalog.queries import material_detail, material_landscape, search_materials
from te_platform.composites.rom import optimize_zte_fraction
from te_platform.composites.curve_rom import optimize_curve_rom
from te_platform.composites.material_pair import curve_materials, optimize_material_pair
from te_platform.config import (
    DEFAULT_PTE_RELEASE_SLUG,
    DEFAULT_RELEASE_SLUG,
    catalog_database_path,
    workspace_database_path,
)
from te_platform.screening.fast_sbr import fast_screen_sbr
from te_platform.screening.sbr import classify_sbr
from te_platform.workers.alignn_runner import predict_alignn_shear
from te_platform.workers.mattersim_runner import predict_mattersim_descriptors
from te_platform.agent.tools import default_registry
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
    submit_precision_job,
    submit_qha_job,
)
from te_platform.jobs.repository import get_job
from te_platform.precision.wsl_executor import PrecisionTaskConfig


WEB_DIRECTORY = Path(__file__).resolve().parents[1] / "web"


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


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)


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

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ensure_catalog_database(catalog_db)
        ensure_workspace_database(workspace_db)
        yield

    app = FastAPI(
        title="热膨胀材料智能计算与设计平台",
        version="0.6.0",
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
    agent_tools = default_registry(catalog_db)

    @app.get("/", include_in_schema=False)
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

    @app.get("/api/agent/tools")
    def agent_tool_names() -> dict[str, object]:
        return {"tools": agent_tools.names()}

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
            return await chat_with_model(request.message, agent_tools)
        except AgentNotConfiguredError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except AgentUpstreamError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.get("/api/datasets/current")
    def current_dataset() -> dict[str, object]:
        return active_dataset_summary(catalog_db)

    @app.get("/api/materials")
    def materials(
        query: str = "",
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict[str, object]]:
        ensure_catalog_database(catalog_db)
        return search_materials(catalog_db, DEFAULT_RELEASE_SLUG, query, limit)

    @app.get("/api/materials/landscape")
    def landscape(
        limit: int = Query(default=1600, ge=1, le=7001),
    ) -> list[dict[str, object]]:
        ensure_catalog_database(catalog_db)
        return material_landscape(catalog_db, DEFAULT_RELEASE_SLUG, limit)

    @app.get("/api/materials/{material_key}")
    def material(material_key: str) -> dict[str, object]:
        ensure_catalog_database(catalog_db)
        try:
            return material_detail(catalog_db, DEFAULT_RELEASE_SLUG, material_key)
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
                "Use the ALIGNN worker to predict G, then calculate E_tilde "
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
                "to calculate E_tilde and the fast SBR result."
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
