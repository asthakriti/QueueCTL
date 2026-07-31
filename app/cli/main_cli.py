import typer

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
    typer.echo(f"Enqueuing: {job_json}")


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