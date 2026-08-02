import sqlite3
import os

# Absolute path, resolved from this file — so the CLI finds the same database
# no matter which directory it is run from.
DB_PATH = os.environ.get("QUEUECTL_DB") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "queuectl.db")
)


def get_connection():
    """Get a database connection tuned for concurrent workers.

    - isolation_level=None puts the connection in autocommit mode, so
      transactions are controlled explicitly (see claim_job's BEGIN IMMEDIATE).
    - WAL lets readers run while a writer holds the write lock.
    - busy_timeout makes a blocked writer wait instead of immediately raising
      "database is locked".
    """
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            retry_after TEXT,
            worker_heartbeat TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Migration: process group of the command a worker is currently running,
    # so a recovering worker can reap orphans left by a killed worker.
    existing = {row[1] for row in cursor.execute("PRAGMA table_info(jobs)")}
    if "child_pgid" not in existing:
        cursor.execute("ALTER TABLE jobs ADD COLUMN child_pgid INTEGER")

    # Speeds up the claim query's scan for the oldest claimable job.
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_state_created ON jobs (state, created_at)"
    )

    # Insert default values if not present
    cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('max-retries', '3')")
    cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('backoff-base', '2')")
    cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('job-timeout', '300')")

    conn.commit()
    conn.close()
