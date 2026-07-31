from app.database.db import get_connection
from typing import Optional
from datetime import datetime, timezone, timedelta

def insert_job(job: dict):
    """Save a new job to the database."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO jobs (id, command, state, attempts, max_retries, created_at, updated_at)
        VALUES (:id, :command, :state, :attempts, :max_retries, :created_at, :updated_at)
    """, job)
    conn.commit()
    conn.close()


def get_jobs_by_state(state: str) -> list:
    """Fetch all jobs with a given state."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE state = ?", (state,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_state_counts() -> list:
    """Count jobs grouped by state."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT state, COUNT(*) as count
        FROM jobs
        GROUP BY state
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def claim_job(worker_id: str) -> Optional[dict]:
    """Atomically claim a pending or retry-ready job."""
    conn = get_connection()

    now = datetime.now(timezone.utc).isoformat()

    row = conn.execute("""
        SELECT * FROM jobs
        WHERE state = 'pending'
        OR (state = 'failed' AND retry_after <= ?)
        ORDER BY created_at ASC
        LIMIT 1
    """, (now,)).fetchone()

    if not row:
        conn.close()
        return None

    job = dict(row)

    conn.execute("""
        UPDATE jobs
        SET state = 'processing',
            updated_at = ?
        WHERE id = ?
    """, (now, job["id"]))

    conn.commit()
    conn.close()
    return job


def update_job_state(job_id: str, state: str, attempts: int, retry_after: str = None):
    """Update job state, attempts, and retry_after in database."""
    conn = get_connection()
    conn.execute("""
        UPDATE jobs
        SET state = ?, attempts = ?, updated_at = ?, retry_after = ?
        WHERE id = ?
    """, (state, attempts, datetime.now(timezone.utc).isoformat(), retry_after, job_id))
    conn.commit()
    conn.close()

def get_dead_jobs() -> list:
    """Fetch all dead jobs from DLQ."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE state = 'dead' ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def requeue_job(job_id: str):
    """Reset a dead job back to pending with fresh attempts."""
    conn = get_connection()
    conn.execute("""
        UPDATE jobs
        SET state = 'pending',
            attempts = 0,
            retry_after = NULL,
            updated_at = ?
        WHERE id = ? AND state = 'dead'
    """, (datetime.now(timezone.utc).isoformat(), job_id))
    affected = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    conn.close()
    return affected > 0

def update_heartbeat(job_id: str):
    """Update the heartbeat timestamp for a processing job."""
    conn = get_connection()
    conn.execute("""
        UPDATE jobs
        SET worker_heartbeat = ?
        WHERE id = ?
    """, (datetime.now(timezone.utc).isoformat(), job_id))
    conn.commit()
    conn.close()


def recover_stuck_jobs(timeout_seconds: int = 30) -> int:
    """Reset processing jobs whose heartbeat has expired."""
    conn = get_connection()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)).isoformat()

    result = conn.execute("""
        UPDATE jobs
        SET state = 'pending',
            updated_at = ?
        WHERE state = 'processing'
        AND (worker_heartbeat IS NULL OR worker_heartbeat < ?)
    """, (datetime.now(timezone.utc).isoformat(), cutoff))

    recovered = result.rowcount
    conn.commit()
    conn.close()
    return recovered