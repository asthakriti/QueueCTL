# QueueCTL

A CLI-based background job queue system with worker processes, automatic
retries with exponential backoff, crash recovery, and a Dead Letter Queue (DLQ).

---

## Setup

**Requirements:** Python 3.9+, Git Bash (on Windows) or any bash terminal

```bash
git clone https://github.com/asthakriti/QueueCTL.git
cd queuectl
python3 -m venv .venv
source .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -e .
```

---

## Usage

### Enqueue a Job

```bash
queuectl enqueue '{"id":"job1","command":"echo hello"}'
queuectl enqueue '{"id":"job2","command":"sleep 5","max_retries":3}'
```

`id` is optional — a UUID is generated if omitted. `max_retries` falls back to
the configured default.

### Start Workers

```bash
# One worker in the foreground
queuectl worker start

# Three workers, each a separate OS process
queuectl worker start --count 3
```

You can also run `queuectl worker start` in several terminals; workers
coordinate through the database, not through the process that launched them.

### Stop Workers

```bash
# From any other terminal — stops every running worker
queuectl worker stop
```

### Check Status

```bash
queuectl status
```

```
=== QueueCTL Status ===
  pending      1
  processing   0
  completed    4
  failed       0
  dead         1
  workers      2 active
```

### List Jobs by State

```bash
queuectl list --state pending
queuectl list --state completed
queuectl list --state failed
queuectl list --state dead
queuectl list --state pending --json
```

### Dead Letter Queue

```bash
queuectl dlq list
queuectl dlq retry job1
```

### Configuration

```bash
queuectl config set max-retries 3
queuectl config set backoff-base 2
queuectl config set job-timeout 300
```

---

## Architecture

```
queuectl/
├── app/
│   ├── cli/
│   │   └── main_cli.py        # All CLI commands
│   ├── database/
│   │   └── db.py              # SQLite connection, PRAGMAs, schema
│   ├── repository/
│   │   └── job_repository.py  # All SQL — claiming, recovery, DLQ
│   ├── services/
│   │   └── job_service.py     # Validation and business logic
│   ├── workers/
│   │   ├── worker.py          # Worker loop and job execution
│   │   └── pid.py             # Per-process PID files
│   ├── config.py              # Config read/write
│   └── utils.py               # Timestamps, process-group kill
├── pyproject.toml
├── DECISIONS.md
└── README.md
```

Layering is strictly one-directional: `cli → services → repository → database`.
The worker talks to the repository directly because it is a second entry point,
not a caller of the CLI.

### How It Works

1. **Enqueue** — jobs are stored in SQLite with `state = pending`.
2. **Claim** — a worker claims one job inside a `BEGIN IMMEDIATE` transaction
   with a `WHERE id = ? AND state = ?` compare-and-swap guard, so exactly one
   worker can ever win a given job.
3. **Execute** — the command runs via `subprocess` in its own process group.
4. **Retry** — a failed job is scheduled with exponential backoff
   (`delay = base ^ attempts`).
5. **DLQ** — after `max_retries` attempts the job moves to `state = dead`.
6. **Crash recovery** — the worker refreshes a heartbeat every 5s. A job whose
   heartbeat is older than 15s is treated as abandoned: its orphaned command is
   killed and the job is reset to `pending`.
7. **Graceful shutdown** — SIGTERM/SIGINT finishes the current job, then exits.

---

## Concurrency Model

`worker start --count N` spawns **N separate OS processes**, not threads. This
matters for three reasons:

- `signal.signal()` only binds on the main thread, so N workers sharing one main
  thread would overwrite each other's handlers and only the last one would ever
  shut down.
- Each process gets its own PID file, so `worker stop` can stop all of them.
- One crashing worker does not take the others down.

Workers coordinate purely through the database, so processes started from
separate terminals are equivalent to processes started with `--count`.

SQLite is opened in **WAL** mode with a 30s `busy_timeout`, so readers do not
block the writer and a contended write waits instead of failing with
`database is locked`. Jobs execute in child processes, so N workers really do
run N commands at once; only the short claim/update transactions serialise.

**Verified:** 20 jobs across 6 worker processes → 20 executions, 20 distinct
jobs, zero duplicates.

---

## Delivery Semantics

**Claiming is exactly-once. Execution is at-least-once.**

Two workers can never claim the same job. But if a worker is SIGKILLed after its
command has run and before it records `completed`, recovery will re-run that
command. Killing the orphaned process group on recovery shrinks the window to
the recovery interval, but cannot close it — an external command runner cannot
know whether a foreign process's side effects landed. **Job handlers should be
idempotent.** See `DECISIONS.md` §2.

---

## Job Lifecycle

```
pending ──► processing ──► completed
                │
                └──► failed ──(backoff)──► pending
                        │
                        └──(attempts >= max_retries)──► dead (DLQ)
```

`dlq retry <id>` moves a `dead` job back to `pending` with `attempts` reset to 0.

---

## Job States

| State      | Description                              |
|------------|------------------------------------------|
| pending    | Waiting to be picked up by a worker      |
| processing | Currently being executed                 |
| completed  | Successfully executed                    |
| failed     | Failed, waiting for retry backoff delay  |
| dead       | Permanently failed, moved to DLQ         |

---

## Configuration

| Key          | Default | Description                              | Applies to |
|--------------|---------|------------------------------------------|------------|
| max-retries  | 3       | Default attempts before a job goes to DLQ | Jobs enqueued after the change |
| backoff-base | 2       | Base for exponential backoff              | Immediately, including in-flight jobs |
| job-timeout  | 300     | Seconds before a running command is killed | The next job a worker starts |

A `max_retries` supplied in the enqueue JSON always overrides the configured
default. An already-enqueued job keeps the `max_retries` stamped on its row, so
its retry budget cannot change underneath it.

---


## Demo Recording

[Link to demo recording](#) ← add your recording link here

---

## Design Decisions

See [DECISIONS.md](./DECISIONS.md) for the reasoning behind atomic claiming,
crash recovery, DLQ retry semantics, worker signalling, and what would change
for priority queues.
