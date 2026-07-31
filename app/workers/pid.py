import os

PID_FILE = "worker.pid"


def write_pid():
    """Save current process PID to file."""
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def read_pid() -> int:
    """Read PID from file. Returns None if file doesn't exist."""
    if not os.path.exists(PID_FILE):
        return None
    with open(PID_FILE, "r") as f:
        return int(f.read().strip())


def delete_pid():
    """Remove PID file."""
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)