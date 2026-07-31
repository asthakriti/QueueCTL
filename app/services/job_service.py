import uuid
import json
from datetime import datetime, timezone

from app.repository.job_repository import insert_job, get_jobs_by_state, get_state_counts


def enqueue_job(job_json: str) -> dict:
    """Parse, validate and enqueue a job."""

    # Parse JSON
    try:
        data = json.loads(job_json)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON string.")

    # Build job
    now = datetime.now(timezone.utc).isoformat()
    job = {
        "id": data.get("id", str(uuid.uuid4())),
        "command": data.get("command", ""),
        "state": "pending",
        "attempts": 0,
        "max_retries": data.get("max_retries", 3),
        "created_at": now,
        "updated_at": now,
    }

    # Validate
    if not job["command"]:
        raise ValueError("'command' field is required.")

    # Save
    insert_job(job)
    return job


def list_jobs(state: str) -> list:
    """Return all jobs with given state."""
    return get_jobs_by_state(state)


def get_status() -> list:
    """Return job counts grouped by state."""
    return get_state_counts()