from app.database.db import get_connection
from datetime import datetime, timezone
from typing import Optional

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