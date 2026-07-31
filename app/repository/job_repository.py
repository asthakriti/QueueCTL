from app.database.db import get_connection


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