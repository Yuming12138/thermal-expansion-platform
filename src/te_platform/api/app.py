from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from te_platform.api.services import active_dataset_summary, ensure_active_database
from te_platform.api.structures import inspect_structure
from te_platform.catalog.queries import material_detail, material_landscape, search_materials
from te_platform.composites.rom import optimize_zte_fraction
from te_platform.config import DEFAULT_RELEASE_SLUG, database_path
from te_platform.screening.fast_sbr import fast_screen_sbr
from te_platform.screening.sbr import classify_sbr
from te_platform.workers.alignn_runner import predict_alignn_shear


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


def create_app(database: Path | None = None) -> FastAPI:
    db_path = database or database_path()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ensure_active_database(db_path)
        yield

    app = FastAPI(
        title="热膨胀材料智能计算与设计平台",
        version="0.4.0",
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

    @app.get("/", include_in_schema=False)
    def web_home() -> FileResponse:
        return FileResponse(WEB_DIRECTORY / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, object]:
        summary = active_dataset_summary(db_path)
        return {
            "status": "ok",
            "dataset_release": summary["release"]["slug"],
            "material_count": summary["counts"]["materials"],
        }

    @app.get("/api/datasets/current")
    def current_dataset() -> dict[str, object]:
        return active_dataset_summary(db_path)

    @app.get("/api/materials")
    def materials(
        query: str = "",
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict[str, object]]:
        ensure_active_database(db_path)
        return search_materials(db_path, DEFAULT_RELEASE_SLUG, query, limit)

    @app.get("/api/materials/landscape")
    def landscape(
        limit: int = Query(default=1600, ge=1, le=7001),
    ) -> list[dict[str, object]]:
        ensure_active_database(db_path)
        return material_landscape(db_path, DEFAULT_RELEASE_SLUG, limit)

    @app.get("/api/materials/{material_key}")
    def material(material_key: str) -> dict[str, object]:
        ensure_active_database(db_path)
        try:
            return material_detail(db_path, DEFAULT_RELEASE_SLUG, material_key)
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
        upload_directory = db_path.parent / "uploads"
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

    return app


app = create_app()
