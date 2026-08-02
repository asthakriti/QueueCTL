import os
import signal
import subprocess
import threading
from datetime import datetime, timezone, timedelta

from app.config import get_config
from app.repository.job_repository import (
    claim_job,
    update_job_state,
    update_heartbeat,
    recover_stuck_jobs,
    set_child_pgid,
)
from app.utils import kill_process_group
from app.workers.pid import write_pid, delete_pid

# Timings. Overridable by env var so the test suite can run the crash-recovery
# scenario in seconds instead of minutes; defaults are what ships.
HEARTBEAT_INTERVAL = int(os.environ.get("QUEUECTL_HEARTBEAT_INTERVAL", 5))
RECOVERY_TIMEOUT = int(os.environ.get("QUEUECTL_RECOVERY_TIMEOUT", 15))
POLL_INTERVAL = 1         # how long an idle worker sleeps between claim attempts
DEFAULT_JOB_TIMEOUT = 300


class Worker:
    """A worker that picks up and executes jobs from the queue."""

    def __init__(self):
        self.running = True
        self.current_job_id = None
        self._stop = threading.Event()
        self._proc = None

        # signal.signal() only works on the main thread. Each worker is its own
        # OS process (see `worker start --count`), so this always binds.
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._handle_shutdown)
            signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Called when SIGINT or SIGTERM is received."""
        print("\nShutdown signal received. Finishing current job...", flush=True)
        self.running = False
        self._stop.set()

    def _heartbeat_loop(self):
        """Background thread — proves to other workers that this job is alive.

        Waits on an Event rather than sleeping, so shutdown is immediate instead
        of taking up to HEARTBEAT_INTERVAL seconds.
        """
        while not self._stop.is_set():
            if self.current_job_id:
                update_heartbeat(self.current_job_id)
            self._stop.wait(HEARTBEAT_INTERVAL)

    def start(self):
        """Start the worker loop."""
        write_pid()
        print(f"Worker started (PID: {os.getpid()}). Waiting for jobs...", flush=True)

        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        try:
            while self.running:
                recovered = recover_stuck_jobs(RECOVERY_TIMEOUT)
                if recovered:
                    print(f"Recovered {recovered} stuck job(s).", flush=True)

                job = claim_job(worker_id=f"worker-{os.getpid()}")

                if not job:
                    self._stop.wait(POLL_INTERVAL)
                    continue

                self.current_job_id = job["id"]
                try:
                    self._execute(job)
                finally:
                    self.current_job_id = None
        finally:
            self._stop.set()
            delete_pid()
            print("Worker stopped gracefully.", flush=True)

    def _execute(self, job: dict):
        """Execute a single job."""
        print(f"Running job: {job['id']} — {job['command']}", flush=True)

        attempts = job["attempts"] + 1
        timeout = int(get_config("job-timeout", default=DEFAULT_JOB_TIMEOUT))

        # start_new_session puts the command and everything it spawns into its
        # own process group. The group id is recorded so that if this worker is
        # SIGKILLed, the worker that recovers the job can kill the orphan before
        # re-running it (see recover_stuck_jobs).
        try:
            self._proc = subprocess.Popen(
                job["command"], shell=True, start_new_session=(os.name != "nt")
            )
            set_child_pgid(job["id"], self._proc.pid)
        except Exception as e:
            print(f"Job error: {job['id']} — {e}", flush=True)
            self._handle_failure(job, attempts)
            return

        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_child()
            print(f"Job timed out after {timeout}s: {job['id']}", flush=True)
            self._handle_failure(job, attempts)
            return
        except KeyboardInterrupt:
            print("Waiting for job to finish...", flush=True)
            self._proc.wait()
        except Exception as e:
            self._kill_child()
            print(f"Job error: {job['id']} — {e}", flush=True)
            self._handle_failure(job, attempts)
            return

        if self._proc.returncode == 0:
            update_job_state(job["id"], "completed", attempts)
            print(f"Job completed: {job['id']}", flush=True)
        else:
            self._handle_failure(job, attempts)

        self._proc = None

    def _kill_child(self):
        """Make sure a timed-out or errored command doesn't keep running.

        Kills the whole process group, not just the shell — otherwise a
        `sh -c "sleep 100; ..."` leaves the sleep behind.
        """
        if self._proc and self._proc.poll() is None:
            kill_process_group(self._proc.pid)
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:
                pass
        self._proc = None

    def _handle_failure(self, job: dict, attempts: int):
        """Handle a failed job — retry with backoff, or move to the DLQ."""
        if attempts >= job["max_retries"]:
            update_job_state(job["id"], "dead", attempts)
            print(f"Job dead (max retries reached): {job['id']}", flush=True)
        else:
            # Read per-failure, not once at construction, so `config set
            # backoff-base` takes effect without restarting the worker.
            base = int(get_config("backoff-base", default=2))
            delay = base ** attempts
            retry_after = (
                datetime.now(timezone.utc) + timedelta(seconds=delay)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            update_job_state(job["id"], "failed", attempts, retry_after)
            print(f"Job failed: {job['id']} — retrying in {delay}s", flush=True)


def run_worker():
    """Module-level entry point so a worker can be launched as its own process."""
    Worker().start()
