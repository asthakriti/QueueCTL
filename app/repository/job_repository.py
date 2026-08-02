from typing import Optional
from datetime import datetime, timezone, timedelta

from app.database.db import get_connection
from app.utils import utc_now, JOB_STATES, kill_process_group


def insert_job(job: dict):
    """Save a new job to the database."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO jobs (id, command, state, attempts, max_retries, created_at, updated_at)
        VALUES (:id, :command, :state, :attempts, :max_retries, :created_at, :updated_at)
    """, job)
    conn.close()


def get_jobs_by_state(state: str) -> list:
    """Fetch all jobs with a given state."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE state = ? ORDER BY created_at ASC", (state,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_state_counts() -> list:
    """Count jobs grouped by state.

    Every state is reported, including the ones with zero jobs — "processing 0"
    is exactly the thing you want to be able to see after a crash-recovery test.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT state, COUNT(*) as count
        FROM jobs
        GROUP BY state
    """).fetchall()
    conn.close()

    found = {row["state"]: row["count"] for row in rows}
    counts = [{"state": s, "count": found.pop(s, 0)} for s in JOB_STATES]
    # Any unexpected state still shows up rather than being silently dropped.
    counts.extend({"state": s, "count": c} for s, c in sorted(found.items()))
    return counts


def claim_job(worker_id: str) -> Optional[dict]:
    """Atomically claim one pending (or retry-ready) job.

    Correctness rests on two things:

    1. BEGIN IMMEDIATE takes SQLite's RESERVED write lock *before* the SELECT,
       so the read and the write are one serialisable transaction. Without it
       the SELECT runs in autocommit mode and N workers can all read the same
       row before any of them writes.
    2. `WHERE id = ? AND state = ?` — the compare-and-swap guard. If another
       worker changed the row between our read and our write, rowcount is 0 and
       we return None instead of stealing a job someone else owns.

    The heartbeat is stamped here, in the same UPDATE, so a freshly claimed job
    is never NULL-heartbeat and therefore never looks "expired" to
    recover_stuck_jobs().
    """
    conn = get_connection()
    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute("""
            SELECT * FROM jobs
            WHERE state = 'pending'
               OR (state = 'failed' AND retry_after IS NOT NULL AND retry_after <= ?)
            ORDER BY created_at ASC
            LIMIT 1
        """, (now,)).fetchone()

        if row is None:
            conn.execute("COMMIT")
            return None

        job = dict(row)

        cursor = conn.execute("""
            UPDATE jobs
            SET state = 'processing',
                worker_heartbeat = ?,
                updated_at = ?
            WHERE id = ? AND state = ?
        """, (now, now, job["id"], job["state"]))

        if cursor.rowcount != 1:
            # Lost the race — another worker changed this row first.
            conn.execute("ROLLBACK")
            return None

        conn.execute("COMMIT")
        job["state"] = "processing"
        job["worker_heartbeat"] = now
        return job

    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def update_job_state(job_id: str, state: str, attempts: int, retry_after: str = None):
    """Update job state, attempts, and retry_after in database."""
    conn = get_connection()
    conn.execute("""
        UPDATE jobs
        SET state = ?, attempts = ?, updated_at = ?, retry_after = ?,
            worker_heartbeat = NULL, child_pgid = NULL
        WHERE id = ?
    """, (state, attempts, utc_now(), retry_after, job_id))
    conn.close()


def set_child_pgid(job_id: str, pgid: int):
    """Record the process group of the command currently running for this job."""
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET child_pgid = ? WHERE id = ? AND state = 'processing'",
        (pgid, job_id),
    )
    conn.close()


def get_dead_jobs() -> list:
    """Fetch all dead jobs from DLQ."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE state = 'dead' ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def requeue_job(job_id: str) -> bool:
    """Reset a dead job back to pending with fresh attempts."""
    conn = get_connection()
    cursor = conn.execute("""
        UPDATE jobs
        SET state = 'pending',
            attempts = 0,
            retry_after = NULL,
            worker_heartbeat = NULL,
            updated_at = ?
        WHERE id = ? AND state = 'dead'
    """, (utc_now(), job_id))
    affected = cursor.rowcount
    conn.close()
    return affected > 0


def update_heartbeat(job_id: str):
    """Update the heartbeat timestamp for a job this worker is processing."""
    conn = get_connection()
    conn.execute("""
        UPDATE jobs
        SET worker_heartbeat = ?
        WHERE id = ? AND state = 'processing'
    """, (utc_now(), job_id))
    conn.close()


def recover_stuck_jobs(timeout_seconds: int = 30) -> int:
    """Reset processing jobs whose heartbeat has expired.

    NULL is deliberately *not* treated as expired: claim_job() always stamps a
    heartbeat, so a NULL heartbeat on a processing row can't happen through the
    normal path. Treating NULL as expired is what let workers steal each other's
    freshly-claimed jobs.

    Before requeueing, the orphaned command left behind by the dead worker is
    killed. Otherwise it keeps running and the retry executes the same job
    concurrently with it.
    """
    conn = get_connection()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("""
            SELECT id, child_pgid FROM jobs
            WHERE state = 'processing'
              AND worker_heartbeat IS NOT NULL
              AND worker_heartbeat < ?
        """, (cutoff,)).fetchall()

        if not rows:
            conn.execute("COMMIT")
            return 0

        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"""
            UPDATE jobs
            SET state = 'pending',
                worker_heartbeat = NULL,
                child_pgid = NULL,
                updated_at = ?
            WHERE id IN ({placeholders})
        """, [utc_now()] + ids)
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()

    for row in rows:
        kill_process_group(row["child_pgid"])

    return len(ids)
