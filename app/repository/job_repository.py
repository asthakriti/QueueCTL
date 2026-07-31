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
    """Atomically claim a pending job for this worker."""
    conn = get_connection()

    row = conn.execute("""
        SELECT * FROM jobs
        WHERE state = 'pending'
        ORDER BY created_at ASC
        LIMIT 1
    """).fetchone()

    if not row:
        conn.close()
        return None

    job = dict(row)

    conn.execute("""
        UPDATE jobs
        SET state = 'processing',
            updated_at = ?
        WHERE id = ?
    """, (datetime.now(timezone.utc).isoformat(), job["id"]))

    conn.commit()
    conn.close()
    return job


def update_job_state(job_id: str, state: str, attempts: int = None):
    """Update job state in database."""
    from datetime import datetime, timezone
    conn = get_connection()

    if attempts is not None:
        conn.execute("""
            UPDATE jobs
            SET state = ?, attempts = ?, updated_at = ?
            WHERE id = ?
        """, (state, attempts, datetime.now(timezone.utc).isoformat(), job_id))
    else:
        conn.execute("""
            UPDATE jobs
            SET state = ?, updated_at = ?
            WHERE id = ?
        """, (state, datetime.now(timezone.utc).isoformat(), job_id))

    conn.commit()
    conn.close()