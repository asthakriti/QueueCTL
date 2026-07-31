import sqlite3
import os

# Database file ka path
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "queuectl.db")
DB_PATH = os.path.abspath(DB_PATH)


def get_connection():
    """Database se connection lo."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create jobs table if it doesn't exist."""
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
            retry_after TEXT
        )
    """)

    conn.commit()
    conn.close()