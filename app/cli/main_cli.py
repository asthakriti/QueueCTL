import json
import os
import signal as os_signal
import subprocess
import sys

import typer

from app.database.db import init_db
from app.config import set_config
from app.workers.pid import read_pids, count_active_workers
from app.workers.worker import Worker
from app.services.job_service import (
    enqueue_job,
    list_jobs,
    get_status,
    list_dead_jobs,
    retry_dead_job,
)

init_db()

app = typer.Typer(help="QueueCTL — A CLI background job queue system.")
worker_app = typer.Typer(help="Manage workers.")
dlq_app = typer.Typer(help="Manage the Dead Letter Queue.")
config_app = typer.Typer(help="Manage configuration.")

app.add_typer(worker_app, name="worker")
app.add_typer(dlq_app, name="dlq")
app.add_typer(config_app, name="config")

ALLOWED_CONFIG_KEYS = ["max-retries", "backoff-base", "job-timeout"]


@app.command()
def enqueue(job_json: str):
    """Add a new job to the queue."""
    try:
        job = enqueue_job(job_json)
        typer.echo(f"Job added: {job['id']}")
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)
    except Exception:
        typer.echo("Error: Job with this ID already exists.")
        raise typer.Exit(1)


@app.command()
def status():
    """Show summary of all job states and active workers."""
    typer.echo("=== QueueCTL Status ===")
    for row in get_status():
        typer.echo(f"  {row['state']:<12} {row['count']}")
    typer.echo(f"  {'workers':<12} {count_active_workers()} active")


@app.command(name="list")
def list_cmd(
    state: str = typer.Option(..., "--state"),
    json_output: bool = typer.Option(False, "--json"),
):
    """List jobs by state."""
    jobs = list_jobs(state)
    if json_output:
        typer.echo(json.dumps(jobs, indent=2))
    else:
        if not jobs:
            typer.echo(f"No jobs with state '{state}'.")
            return
        for job in jobs:
            typer.echo(f"[{job['state']}] {job['id']} — {job['command']}")


@worker_app.command("start")
def worker_start(count: int = typer.Option(1, "--count")):
    """Start one or more workers in the foreground.

    Each worker is a separate OS process, not a thread — so every worker gets
    its own signal handling and its own PID file, and one crashing worker
    doesn't take the others down.
    """
    if count < 1:
        typer.echo("Error: --count must be at least 1.")
        raise typer.Exit(1)

    if count == 1:
        Worker().start()
        return

    typer.echo(f"Starting {count} worker(s) as separate processes...")
    child_code = "from app.workers.worker import run_worker; run_worker()"
    procs = [
        subprocess.Popen([sys.executable, "-c", child_code]) for _ in range(count)
    ]

    def _forward(signum, frame):
        for p in procs:
            if p.poll() is None:
                try:
                    p.terminate()
                except OSError:
                    pass

    os_signal.signal(os_signal.SIGINT, _forward)
    os_signal.signal(os_signal.SIGTERM, _forward)

    for p in procs:
        while p.poll() is None:
            try:
                p.wait()
            except KeyboardInterrupt:
                _forward(None, None)


@worker_app.command("stop")
def worker_stop():
    """Gracefully stop all running workers."""
    pids = read_pids()
    if not pids:
        typer.echo("No running worker found.")
        raise typer.Exit(1)

    stopped = 0
    for pid in pids:
        try:
            os.kill(pid, os_signal.SIGTERM)
            typer.echo(f"Stop signal sent to worker (PID: {pid}).")
            stopped += 1
        except OSError:
            typer.echo(f"Worker {pid} not found — it may have already stopped.")

    if stopped == 0:
        typer.echo("No running worker found.")
        raise typer.Exit(1)

    typer.echo(f"Stopped {stopped} worker(s).")


@dlq_app.command("list")
def dlq_list():
    """List all dead jobs."""
    jobs = list_dead_jobs()
    if not jobs:
        typer.echo("No dead jobs in DLQ.")
        return
    for job in jobs:
        typer.echo(f"[dead] {job['id']} — {job['command']} (attempts: {job['attempts']})")


@dlq_app.command("retry")
def dlq_retry(job_id: str):
    """Move a dead job back to pending queue."""
    if retry_dead_job(job_id):
        typer.echo(f"Job {job_id} re-queued successfully.")
    else:
        typer.echo(f"Error: Job '{job_id}' not found in DLQ.")
        raise typer.Exit(1)


@config_app.command("set")
def config_set(key: str, value: str):
    """Set a config value."""
    if key not in ALLOWED_CONFIG_KEYS:
        typer.echo(f"Error: Unknown config key '{key}'. Allowed: {ALLOWED_CONFIG_KEYS}")
        raise typer.Exit(1)
    try:
        if int(value) < 1:
            raise ValueError
    except ValueError:
        typer.echo(f"Error: '{key}' must be a positive integer.")
        raise typer.Exit(1)

    set_config(key, value)
    typer.echo(f"Config updated: {key} = {value}")


if __name__ == "__main__":
    app()
