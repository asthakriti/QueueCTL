import typer
import json

from app.database.db import init_db
from app.services.job_service import enqueue_job, list_jobs, get_status

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


@worker_app.command("stop")
def worker_stop():
    """Gracefully stop all running workers."""
    typer.echo("Stopping workers...")


@dlq_app.command("list")
def dlq_list():
    """List all dead jobs."""
    typer.echo("DLQ list: coming soon")


@dlq_app.command("retry")
def dlq_retry(job_id: str):
    """Retry a dead job."""
    typer.echo(f"Retrying job: {job_id}")


@config_app.command("set")
def config_set(key: str, value: str):
    """Set a config value."""
    typer.echo(f"Config set: {key} = {value}")