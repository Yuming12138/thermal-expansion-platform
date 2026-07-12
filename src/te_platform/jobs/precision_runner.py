from __future__ import annotations

import re
import shutil
import subprocess
import threading
from hashlib import sha256
from pathlib import Path
from typing import Literal

from te_platform.api.structures import inspect_structure
from te_platform.jobs.repository import create_job, get_job, replace_completed_job_result, transition_job
from te_platform.jobs.states import JobStatus
from te_platform.precision.results import parse_elastic_results, parse_precision_results, parse_qha_results
from te_platform.precision.wsl_executor import PrecisionTaskConfig, build_precision_command, prepare_precision_task
from te_platform.screening.fast_sbr import calculate_bonding_modulus
from te_platform.screening.fast_sbr import fast_screen_sbr
from te_platform.screening.sbr import classify_sbr
from te_platform.workers.alignn_runner import predict_alignn_shear
from te_platform.workers.mattersim_runner import predict_mattersim_descriptors
from te_platform.workers.structure_converter import write_precision_poscar


_QHA_DISPLACEMENT_PROGRESS = re.compile(
    r"(?P<percent>\d+)%\|.*?\|\s*(?P<completed>\d+)/(?P<total>\d+)\s+\["
)


def precision_progress(database: str | Path, job_id: str) -> dict[str, str | int | float] | None:
    work = Path(database).parent / "runs" / job_id
    root = work / "elastic"
    if root.is_dir():
        tasks = [path for path in root.rglob("strain_*") if path.is_dir()]
        if tasks:
            completed = sum((path / "CONTCAR").is_file() for path in tasks)
            return {
                "stage": "elastic",
                "completed_strains": completed,
                "total_strains": len(tasks),
                "percent": round(100.0 * completed / len(tasks), 1),
            }
    qha_progress = _qha_displacement_progress(work)
    if qha_progress is not None:
        return qha_progress
    job = get_job(database, job_id)
    if job["workflow"] == "fast_structure_screening":
        percent = {
            JobStatus.PENDING.value: 0.0,
            JobStatus.QUEUED.value: 5.0,
            JobStatus.RUNNING.value: 50.0,
            JobStatus.SUCCEEDED.value: 100.0,
            JobStatus.FAILED.value: 100.0,
            JobStatus.CANCELLED.value: 100.0,
        }[job["status"]]
        return {"stage": "fast_screening", "percent": percent}
    return None


def _qha_displacement_progress(work: Path) -> dict[str, str | int | float] | None:
    log_path = work / "qha_calc.log"
    if not log_path.is_file():
        return None
    matches = list(_QHA_DISPLACEMENT_PROGRESS.finditer(log_path.read_text(encoding="utf-8", errors="replace")))
    if not matches:
        return None
    match = matches[-1]
    completed = int(match["completed"])
    total = int(match["total"])
    if total <= 0:
        return None
    return {
        "stage": "qha_force_constants",
        "completed_displacements": completed,
        "total_displacements": total,
        "percent": round(100.0 * completed / total, 1),
    }


CalculationMode = Literal["combined", "elastic", "qha"]


def submit_fast_screen_job(
    database: str | Path,
    structure: bytes,
    filename: str = "POSCAR",
) -> dict[str, object]:
    job = create_job(
        database,
        workflow="fast_structure_screening",
        parameters={"mode": "fast", "filename": filename, "structure_sha256": sha256(structure).hexdigest()},
    )
    work = Path(database).parent / "runs" / job["id"]
    work.mkdir(parents=True, exist_ok=False)
    suffix = Path(filename).suffix.lower() or ".vasp"
    structure_path = work / f"input{suffix}"
    structure_path.write_bytes(structure)
    transition_job(database, job["id"], JobStatus.QUEUED)
    threading.Thread(
        target=_run_fast_screen,
        args=(Path(database), job["id"], structure_path, filename),
        daemon=True,
    ).start()
    return get_job(database, job["id"])


def _run_fast_screen(
    database: Path,
    job_id: str,
    structure_path: Path,
    filename: str,
) -> None:
    transition_job(database, job_id, JobStatus.RUNNING)
    try:
        content = structure_path.read_bytes()
        inspection = inspect_structure(filename, content)
        alignn = predict_alignn_shear(structure_path)
        mattersim = predict_mattersim_descriptors(structure_path)
        descriptors = mattersim.descriptors
        screening = fast_screen_sbr(
            float(alignn.prediction["shear_modulus_gpa"]),
            float(descriptors["cohesive_energy_ev_per_atom"]),
            float(inspection.cell_volume_a3 or 0.0),
            int(descriptors["atom_count"]),
            float(descriptors["average_coordination_number"]),
        )
        transition_job(
            database,
            job_id,
            JobStatus.SUCCEEDED,
            result={
                "calculation_mode": "fast",
                "structure_sha256": sha256(content).hexdigest(),
                "inspection": inspection.to_dict(),
                "alignn": alignn.to_dict(),
                "mattersim": mattersim.to_dict(),
                "fast_sbr": screening.to_dict(),
            },
        )
    except Exception as error:
        transition_job(
            database,
            job_id,
            JobStatus.FAILED,
            error_message=str(error),
        )


def submit_precision_job(
    database: str | Path,
    structure: bytes,
    config: PrecisionTaskConfig,
    filename: str = "POSCAR",
) -> dict[str, object]:
    return _submit_job(database, structure, config, filename=filename, mode="combined")


def submit_elastic_job(
    database: str | Path,
    structure: bytes,
    config: PrecisionTaskConfig,
    filename: str = "POSCAR",
) -> dict[str, object]:
    return _submit_job(database, structure, config, filename=filename, mode="elastic")


def submit_qha_job(
    database: str | Path,
    structure: bytes,
    config: PrecisionTaskConfig,
    filename: str = "POSCAR",
) -> dict[str, object]:
    return _submit_job(database, structure, config, filename=filename, mode="qha")


def _submit_job(
    database: str | Path,
    structure: bytes,
    config: PrecisionTaskConfig,
    *,
    filename: str,
    mode: CalculationMode,
) -> dict[str, object]:
    workflow = {
        "combined": "precision_elastic_qha",
        "elastic": "precision_elastic",
        "qha": "precision_qha",
    }[mode]
    job = create_job(
        database,
        workflow=workflow,
        parameters={"config": config.__dict__, "mode": mode, "filename": filename},
    )
    work = Path(database).parent / "runs" / job["id"]
    work.mkdir(parents=True, exist_ok=False)
    write_precision_poscar(work, filename=filename, content=structure)
    prepare_precision_task(work)
    transition_job(database, job["id"], JobStatus.QUEUED)
    threading.Thread(target=_run, args=(Path(database), job["id"], work, config, mode), daemon=True).start()
    return job


def resume_precision_qha(database: str | Path, parent_job_id: str) -> dict[str, object]:
    parent = get_job(database, parent_job_id)
    parent_work = Path(database).parent / "runs" / parent_job_id
    elastic_source_job_id = _find_elastic_source_job(database, parent_job_id)
    elastic_source_work = Path(database).parent / "runs" / elastic_source_job_id
    config = PrecisionTaskConfig(**parent["parameters"]["config"])
    job = create_job(
        database,
        workflow="precision_elastic_qha",
        parameters={
            "config": config.__dict__,
            "parent_job_id": parent_job_id,
            "elastic_source_job_id": elastic_source_job_id,
            "mode": "qha",
        },
    )
    work = Path(database).parent / "runs" / job["id"]
    work.mkdir(parents=True, exist_ok=False)
    (work / "POSCAR").write_bytes((parent_work / "POSCAR").read_bytes())
    elastic_work = work / "elastic"
    elastic_work.mkdir()
    shutil.copy2(elastic_source_work / "elastic" / "ELASTIC_TENSOR", elastic_work / "ELASTIC_TENSOR")
    source_bm_log = elastic_source_work / "elastic" / "BM_SS.log"
    if source_bm_log.is_file():
        shutil.copy2(source_bm_log, elastic_work / "BM_SS.log")
    prepare_precision_task(work)
    transition_job(database, job["id"], JobStatus.QUEUED)
    threading.Thread(target=_run, args=(Path(database), job["id"], work, config, "qha"), daemon=True).start()
    return job


def _find_elastic_source_job(database: str | Path, job_id: str) -> str:
    """Resolve a QHA recovery chain to the task that produced its elastic tensor."""
    visited: set[str] = set()
    current_job_id = job_id
    while current_job_id not in visited:
        visited.add(current_job_id)
        work = Path(database).parent / "runs" / current_job_id
        if (work / "elastic" / "ELASTIC_TENSOR").is_file():
            return current_job_id
        current = get_job(database, current_job_id)
        ancestor_job_id = current["parameters"].get("parent_job_id")
        if not isinstance(ancestor_job_id, str) or not ancestor_job_id:
            break
        current_job_id = ancestor_job_id
    raise ValueError("QHA recovery requires a completed elastic tensor in this task's lineage")


def refresh_precision_result(database: str | Path, job_id: str) -> dict[str, object]:
    """Reparse a succeeded task after result-parser or quality-rule updates."""
    if get_job(database, job_id)["status"] != JobStatus.SUCCEEDED.value:
        raise ValueError("Only a succeeded task can have its parsed result refreshed")
    job = get_job(database, job_id)
    work = Path(database).parent / "runs" / job_id
    mode = job["parameters"].get("mode", "combined")
    result = _parse_completed_result(work, mode)
    return replace_completed_job_result(database, job_id, result)


def _parse_completed_result(work: Path, mode: str) -> dict[str, object]:
    if mode == "qha":
        return {"calculation_mode": "qha", **parse_qha_results(work).to_dict()}
    if mode == "elastic":
        elastic = parse_elastic_results(work)
        mattersim = predict_mattersim_descriptors(work / "POSCAR")
        descriptors = mattersim.descriptors
        bonding = calculate_bonding_modulus(
            float(descriptors["cohesive_energy_ev_per_atom"]),
            float(descriptors["cell_volume_a3"]),
            int(descriptors["atom_count"]),
            float(descriptors["average_coordination_number"]),
        )
        sbr = classify_sbr(elastic.shear_modulus_hill_gpa, bonding.bonding_modulus_gpa)
        return {
            "calculation_mode": "elastic",
            **elastic.to_dict(),
            "mattersim": mattersim.to_dict(),
            "bonding": bonding.to_dict(),
            "sbr": sbr.to_dict(),
        }
    return {"calculation_mode": "combined", **parse_precision_results(work).to_dict()}


def _run(
    database: Path,
    job_id: str,
    work: Path,
    config: PrecisionTaskConfig,
    mode: CalculationMode,
) -> None:
    transition_job(database, job_id, JobStatus.RUNNING)
    log = work / "workflow.log"
    try:
        with log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                build_precision_command(work, config, mode=mode),
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if completed.returncode != 0:
            transition_job(database, job_id, JobStatus.FAILED, error_message=f"Workflow failed; see {log}")
            return
        result = _parse_completed_result(work, mode)
        transition_job(database, job_id, JobStatus.SUCCEEDED, result=result)
    except Exception as error:
        transition_job(database, job_id, JobStatus.FAILED, error_message=str(error))
