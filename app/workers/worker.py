import subprocess
import time
import signal
import os
import threading
from datetime import datetime, timezone, timedelta
from app.config import get_config

from app.repository.job_repository import claim_job, update_job_state, update_heartbeat, recover_stuck_jobs
from app.workers.pid import write_pid, delete_pid

HEARTBEAT_INTERVAL = 10   # every 10 seconds
RECOVERY_TIMEOUT = 30     # jobs older than 30s are stuck


class Worker:
    """A worker that picks up and executes jobs from the queue."""

    def __init__(self):
        self.running = True
        self.current_job_id = None
        self.backoff_base = int(get_config("backoff-base", default=2))
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Called when SIGINT or SIGTERM is received."""
        print("\nShutdown signal received. Finishing current job...")
        self.running = False
        delete_pid()
        print("Worker stopped gracefully.")

    def _heartbeat_loop(self):
        """Background thread — updates heartbeat every 10 seconds."""
        while self.running:
            if self.current_job_id:
                update_heartbeat(self.current_job_id)
            time.sleep(HEARTBEAT_INTERVAL)

    def start(self):
        """Start the worker loop."""
        write_pid()
        print(f"Worker started (PID: {os.getpid()}). Waiting for jobs...")

        # Start heartbeat thread
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        try:
            while self.running:
                # Recover stuck jobs first
                recovered = recover_stuck_jobs(RECOVERY_TIMEOUT)
                if recovered:
                    print(f"Recovered {recovered} stuck job(s).")

                job = claim_job(worker_id="worker-1")

                if not job:
                    time.sleep(2)
                    continue

                self.current_job_id = job["id"]
                self._execute(job)
                self.current_job_id = None

        finally:
            delete_pid()

    def _execute(self, job: dict):
        """Execute a single job."""
        print(f"Running job: {job['id']} — {job['command']}")

        attempts = job["attempts"] + 1

        try:
            proc = subprocess.Popen(
                job["command"],
                shell=True,
                start_new_session=True
            )
            proc.wait(timeout=60)

            if proc.returncode == 0:
                update_job_state(job["id"], "completed", attempts)
                print(f"Job completed: {job['id']}")
            else:
                self._handle_failure(job, attempts)

        except KeyboardInterrupt:
            print("Waiting for job to finish...")
            proc.wait()
            if proc.returncode == 0:
                update_job_state(job["id"], "completed", attempts)
                print(f"Job completed: {job['id']}")
            else:
                self._handle_failure(job, attempts)

        except Exception as e:
            print(f"Job error: {job['id']} — {e}")
            self._handle_failure(job, attempts)

    def _handle_failure(self, job: dict, attempts: int):
        """Handle a failed job — retry or move to DLQ."""
        if attempts >= job["max_retries"]:
            update_job_state(job["id"], "dead", attempts)
            print(f"Job dead (max retries reached): {job['id']}")
        else:
            delay = self.backoff_base ** attempts
            retry_after = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            update_job_state(job["id"], "failed", attempts, retry_after)
            print(f"Job failed: {job['id']} — retrying in {delay}s")