import subprocess
import time

from app.repository.job_repository import claim_job, update_job_state


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

        try:
            result = subprocess.run(
                job["command"],
                shell=True,
                timeout=60
            )

            if result.returncode == 0:
                update_job_state(job["id"], "completed", job["attempts"] + 1)
                print(f"Job completed: {job['id']}")
            else:
                update_job_state(job["id"], "failed", job["attempts"] + 1)
                print(f"Job failed: {job['id']}")

        except Exception as e:
            update_job_state(job["id"], "failed", job["attempts"] + 1)
            print(f"Job error: {job['id']} — {e}")