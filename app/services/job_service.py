import uuid
import json

from app.config import get_config
from app.utils import utc_now
from app.repository.job_repository import (
    insert_job,
    get_jobs_by_state,
    get_state_counts,
    get_dead_jobs,
    requeue_job,
)


def enqueue_job(job_json: str) -> dict:
    """Parse, validate and enqueue a job."""

    # Parse JSON
    try:
        data = json.loads(job_json)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON string.")

    if not isinstance(data, dict):
        raise ValueError("Job must be a JSON object.")

    # Per-job max_retries wins; otherwise fall back to the persisted config
    # value set by `queuectl config set max-retries N`.
    try:
        default_retries = int(get_config("max-retries", default=3))
    except (TypeError, ValueError):
        default_retries = 3

    now = utc_now()
    job = {
        "id": data.get("id") or str(uuid.uuid4()),
        "command": data.get("command", ""),
        "state": "pending",
        "attempts": 0,
        "max_retries": int(data.get("max_retries", default_retries)),
        "created_at": now,
        "updated_at": now,
    }

    # Validate
    if not job["command"]:
        raise ValueError("'command' field is required.")
    if job["max_retries"] < 1:
        raise ValueError("'max_retries' must be at least 1.")

    # Save
    insert_job(job)
    return job


def list_jobs(state: str) -> list:
    """Return all jobs with given state."""
    return get_jobs_by_state(state)


def get_status() -> list:
    """Return job counts for every state, including zeros."""
    return get_state_counts()


def list_dead_jobs() -> list:
    """Return all dead jobs."""
    return get_dead_jobs()


def retry_dead_job(job_id: str) -> bool:
    """Move a dead job back to pending. Returns True if successful."""
    return requeue_job(job_id)
