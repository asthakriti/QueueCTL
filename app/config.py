from app.database.db import get_connection


def get_config(key: str, default=None):
    """Read a config value from database."""
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM config WHERE key = ?", (key,)
    ).fetchone()
    conn.close()

    if row is None:
        return default
    return row["value"]


def set_config(key: str, value: str):
    """Save a config value to database."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO config (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, value))
    conn.commit()
    conn.close()