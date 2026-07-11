from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path

from te_platform.jobs.repository import create_job, transition_job
from te_platform.jobs.states import JobStatus
from te_platform.precision.results import parse_precision_results
from te_platform.precision.wsl_executor import PrecisionTaskConfig, build_precision_command, prepare_precision_task


_QHA_DISPLACEMENT_PROGRESS = re.compile(
    r"(?P<percent>\d+)%\|.*?\|\s*(?P<completed>\d+)/(?P<total>\d+)\s+\["
)


def precision_progress(database: str | Path, job_id: str) -> dict[str, str | int | float] | None:
    work = Path(database).parent / "runs" / job_id
    root = work / "elastic"
    if not root.is_dir():
        return _qha_displacement_progress(work)
    tasks = [path for path in root.rglob("strain_*") if path.is_dir()]
    if tasks:
        completed = sum((path / "CONTCAR").is_file() for path in tasks)
        return {
            "stage": "elastic",
            "completed_strains": completed,
            "total_strains": len(tasks),
            "percent": round(100.0 * completed / len(tasks), 1),
        }
    return _qha_displacement_progress(work)


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


def submit_precision_job(database: str | Path, structure: bytes, config: PrecisionTaskConfig) -> dict[str, object]:
    job = create_job(database, workflow="precision_elastic_qha", parameters={"config": config.__dict__})
    work = Path(database).parent / "runs" / job["id"]
    work.mkdir(parents=True, exist_ok=False)
    (work / "POSCAR").write_bytes(structure)
    prepare_precision_task(work)
    transition_job(database, job["id"], JobStatus.QUEUED)
    threading.Thread(target=_run, args=(Path(database), job["id"], work, config, False), daemon=True).start()
    return job


def resume_precision_qha(database: str | Path, parent_job_id: str) -> dict[str, object]:
    from te_platform.jobs.repository import get_job

    parent = get_job(database, parent_job_id)
    parent_work = Path(database).parent / "runs" / parent_job_id
    if not (parent_work / "elastic" / "ELASTIC_TENSOR").is_file():
        raise ValueError("QHA recovery requires a completed elastic tensor in the parent task")
    config = PrecisionTaskConfig(**parent["parameters"]["config"])
    job = create_job(
        database,
        workflow="precision_elastic_qha",
        parameters={"config": config.__dict__, "parent_job_id": parent_job_id, "mode": "thermal_only"},
    )
    work = Path(database).parent / "runs" / job["id"]
    work.mkdir(parents=True, exist_ok=False)
    (work / "POSCAR").write_bytes((parent_work / "POSCAR").read_bytes())
    prepare_precision_task(work)
    transition_job(database, job["id"], JobStatus.QUEUED)
    threading.Thread(target=_run, args=(Path(database), job["id"], work, config, True), daemon=True).start()
    return job


def _run(database: Path, job_id: str, work: Path, config: PrecisionTaskConfig, thermal_only: bool) -> None:
    transition_job(database, job_id, JobStatus.RUNNING)
    log = work / "workflow.log"
    try:
        with log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                build_precision_command(work, config, thermal_only=thermal_only),
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if completed.returncode != 0:
            transition_job(database, job_id, JobStatus.FAILED, error_message=f"Workflow failed; see {log}")
            return
        result = parse_precision_results(work).to_dict()
        transition_job(database, job_id, JobStatus.SUCCEEDED, result=result)
    except Exception as error:
        transition_job(database, job_id, JobStatus.FAILED, error_message=str(error))
