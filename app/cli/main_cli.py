import typer
import json
import os
import threading
import signal as os_signal

from app.workers.pid import read_pid
from app.database.db import init_db
from app.workers.worker import Worker
from app.config import set_config, get_config
from app.services.job_service import enqueue_job, list_jobs, get_status, list_dead_jobs, retry_dead_job

init_db()

app = typer.Typer(help="QueueCTL — A CLI background job queue system.")

worker_app = typer.Typer(help="Manage workers.")
dlq_app = typer.Typer(help="Manage the Dead Letter Queue.")
config_app = typer.Typer(help="Manage configuration.")

app.add_typer(worker_app, name="worker")
app.add_typer(dlq_app, name="dlq")
app.add_typer(config_app, name="config")


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
    counts = get_status()
    typer.echo("=== QueueCTL Status ===")
    for row in counts:
        typer.echo(f"  {row['state']:<12} {row['count']}")


@app.command(name="list")
def list_cmd(
    state: str = typer.Option(..., "--state"),
    json_output: bool = typer.Option(False, "--json")
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
    """Start workers in the foreground."""
    typer.echo(f"Starting {count} worker(s)...")

    threads = []
    for i in range(count):
        worker = Worker()
        t = threading.Thread(target=worker.start, daemon=True)
        threads.append(t)
        t.start()

    # Wait for all threads to finish
    for t in threads:
        t.join()


@worker_app.command("stop")
def worker_stop():
    """Gracefully stop all running workers."""
    typer.echo("Stopping workers...")


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
    success = retry_dead_job(job_id)

    if success:
        typer.echo(f"Job {job_id} re-queued successfully.")
    else:
        typer.echo(f"Error: Job '{job_id}' not found in DLQ.")
        raise typer.Exit(1)

@config_app.command("set")
def config_set(key: str, value: str):
    """Set a config value."""
    allowed_keys = ["max-retries", "backoff-base"]

    if key not in allowed_keys:
        typer.echo(f"Error: Unknown config key '{key}'. Allowed: {allowed_keys}")
        raise typer.Exit(1)

    set_config(key, value)
    typer.echo(f"Config updated: {key} = {value}")


@worker_app.command("start")
def worker_start(count: int = typer.Option(1, "--count")):
    """Start workers in the foreground."""
    typer.echo(f"Starting {count} worker(s)...")
    Worker().start()


@worker_app.command("stop")
def worker_stop():
    """Gracefully stop all running workers."""
    pid = read_pid()

    if pid is None:
        typer.echo("No running worker found.")
        raise typer.Exit(1)

    try:
        os.kill(pid, os_signal.SIGTERM)
        typer.echo(f"Stop signal sent to worker (PID: {pid}).")
    except ProcessLookupError:
        typer.echo("Worker process not found — it may have already stopped.")
        raise typer.Exit(1)

