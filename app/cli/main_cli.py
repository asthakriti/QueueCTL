import typer
import json
import uuid
from datetime import datetime, timezone

from app.database.db import init_db, get_connection

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

    # Step 1: Parse the JSON string
    try:
        data = json.loads(job_json)
    except json.JSONDecodeError:
        typer.echo("Error: Invalid JSON. Please pass valid JSON string.")
        raise typer.Exit(1)

    # Step 2: Build the job
    now = datetime.now(timezone.utc).isoformat()
    job = {
        "id": data.get("id", str(uuid.uuid4())),
        "command": data.get("command", ""),
        "state": "pending",
        "attempts": 0,
        "max_retries": data.get("max_retries", 3),
        "created_at": now,
        "updated_at": now,
    }

    # Step 3: Validate
    if not job["command"]:
        typer.echo("Error: 'command' is required.")
        raise typer.Exit(1)

    # Step 4: Save to database
    try:
        conn = get_connection()
        conn.execute("""
            INSERT INTO jobs (id, command, state, attempts, max_retries, created_at, updated_at)
            VALUES (:id, :command, :state, :attempts, :max_retries, :created_at, :updated_at)
        """, job)
        conn.commit()
        conn.close()
    except Exception as e:
        typer.echo(f"Error: Job with id '{job['id']}' already exists.")
        raise typer.Exit(1)

    typer.echo(f"Job added: {job['id']}")


@app.command()
def status():
    """Show summary of all job states and active workers."""
    typer.echo("Status: coming soon")


@app.command()
def list(
    state: str = typer.Option(..., "--state"),
    json: bool = typer.Option(False, "--json")
):
    """List jobs by state."""
    typer.echo(f"Listing jobs: state={state}")


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