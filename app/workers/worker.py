import subprocess
import time
from datetime import datetime, timezone, timedelta

from app.repository.job_repository import claim_job, update_job_state

BACKOFF_BASE = 2


class Worker:
    """A worker that picks up and executes jobs from the queue."""

    def start(self):
        """Start the worker loop."""
        print("Worker started. Waiting for jobs...")

        while True:
            job = claim_job(worker_id="worker-1")

            if not job:
                time.sleep(2)
                continue

            self._execute(job)

    def _execute(self, job: dict):
        """Execute a single job."""
        print(f"Running job: {job['id']} — {job['command']}")

        attempts = job["attempts"] + 1

        try:
            result = subprocess.run(
                job["command"],
                shell=True,
                timeout=60
            )

            if result.returncode == 0:
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
            delay = BACKOFF_BASE ** attempts
            retry_after = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            update_job_state(job["id"], "failed", attempts, retry_after)
            print(f"Job failed: {job['id']} — retrying in {delay}s")