import os
import signal

from app.database.db import DB_PATH

# One file per worker process, in an absolute directory next to the database.
# Absolute, so `worker stop` works from any directory. One file per process, so
# N workers don't overwrite each other and `worker stop` can signal all of them.
PID_DIR = os.path.join(os.path.dirname(DB_PATH), ".queuectl-pids")


def _pid_file(pid: int) -> str:
    return os.path.join(PID_DIR, f"worker-{pid}.pid")


def _remove(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def is_alive(pid: int) -> bool:
    """Check whether a process exists, without killing it.

    On Windows os.kill(pid, 0) does NOT mean "probe" — Python maps it to
    TerminateProcess, which would kill the worker we are only asking about. So
    Windows gets an OpenProcess/GetExitCodeProcess check instead.
    """
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def write_pid():
    """Register the current process as a running worker."""
    os.makedirs(PID_DIR, exist_ok=True)
    with open(_pid_file(os.getpid()), "w") as f:
        f.write(str(os.getpid()))


def read_pids() -> list:
    """Every live worker PID. Stale files are pruned as a side effect."""
    if not os.path.isdir(PID_DIR):
        return []

    pids = []
    for name in os.listdir(PID_DIR):
        if not (name.startswith("worker-") and name.endswith(".pid")):
            continue
        path = os.path.join(PID_DIR, name)
        try:
            with open(path) as f:
                pid = int(f.read().strip())
        except (ValueError, OSError):
            _remove(path)
            continue

        if is_alive(pid):
            pids.append(pid)
        else:
            _remove(path)

    return sorted(pids)


def count_active_workers() -> int:
    """How many workers are currently running."""
    return len(read_pids())


def delete_pid(pid: int = None):
    """Deregister a worker. Defaults to the current process."""
    _remove(_pid_file(pid if pid is not None else os.getpid()))


def stop_all() -> list:
    """Send SIGTERM to every live worker. Returns the PIDs signalled."""
    stopped = []
    for pid in read_pids():
        try:
            os.kill(pid, signal.SIGTERM)
            stopped.append(pid)
        except OSError:
            _remove(_pid_file(pid))
    return stopped
