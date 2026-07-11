from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from te_platform.jobs.repository import create_job, transition_job
from te_platform.jobs.states import JobStatus
from te_platform.precision.results import parse_precision_results
from te_platform.precision.wsl_executor import PrecisionTaskConfig, build_precision_command, prepare_precision_task


def precision_progress(database: str | Path, job_id: str) -> dict[str, int | float] | None:
    root = Path(database).parent / "runs" / job_id / "elastic"
    if not root.is_dir():
        return None
    tasks = [path for path in root.rglob("strain_*") if path.is_dir()]
    if not tasks:
        return None
    completed = sum((path / "CONTCAR").is_file() for path in tasks)
    return {
        "completed_strains": completed,
        "total_strains": len(tasks),
        "percent": round(100.0 * completed / len(tasks), 1),
    }


def submit_precision_job(database: str | Path, structure: bytes, config: PrecisionTaskConfig) -> dict[str, object]:
    job = create_job(database, workflow="precision_elastic_qha", parameters={"config": config.__dict__})
    work = Path(database).parent / "runs" / job["id"]
    work.mkdir(parents=True, exist_ok=False)
    (work / "POSCAR").write_bytes(structure)
    prepare_precision_task(work)
    transition_job(database, job["id"], JobStatus.QUEUED)
    threading.Thread(target=_run, args=(Path(database), job["id"], work, config), daemon=True).start()
    return job


def _run(database: Path, job_id: str, work: Path, config: PrecisionTaskConfig) -> None:
    transition_job(database, job_id, JobStatus.RUNNING)
    log = work / "workflow.log"
    try:
        with log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(build_precision_command(work, config), stdout=handle, stderr=subprocess.STDOUT, check=False)
        if completed.returncode != 0:
            transition_job(database, job_id, JobStatus.FAILED, error_message=f"Workflow failed; see {log}")
            return
        result = parse_precision_results(work).to_dict()
        transition_job(database, job_id, JobStatus.SUCCEEDED, result=result)
    except Exception as error:
        transition_job(database, job_id, JobStatus.FAILED, error_message=str(error))
