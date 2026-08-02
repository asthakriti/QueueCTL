import os
import signal
import subprocess
from datetime import datetime, timezone

# All job states, in the order `status` reports them.
JOB_STATES = ["pending", "processing", "completed", "failed", "dead"]


def kill_process_group(pgid) -> bool:
    """Kill a command's whole process group.

    Jobs are launched with start_new_session=True, so the shell and everything
    it spawns share one process group whose id is the shell's pid. Recording
    that id lets a recovering worker reap the orphaned command left behind by a
    SIGKILLed worker, instead of letting it race the retry.
    """
    if not pgid:
        return False
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pgid)],
                capture_output=True,
                check=False,
            )
            return True
        os.killpg(pgid, 0)          # does the group still exist?
        os.killpg(pgid, signal.SIGKILL)
        return True
    except (OSError, ProcessLookupError):
        return False


def utc_now() -> str:
    """UTC timestamp in the format the assignment spec uses: 2025-11-04T10:30:00Z.

    Every timestamp written to the database goes through this function, so
    string comparisons (retry_after <= now, worker_heartbeat < cutoff) are
    always comparing the same fixed-width format and sort correctly.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
