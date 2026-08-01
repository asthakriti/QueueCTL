# QueueCTL

A CLI-based background job queue system with worker processes, automatic
retries with exponential backoff, and a Dead Letter Queue (DLQ).

---

## Setup

**Requirements:** Python 3.9+, Git Bash (on Windows) or any bash terminal

```bash
# Clone the repository
git clone https://github.com/asthakriti/QueueCT.git
cd queuectl

# Create virtual environment
python3 -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# source .venv/bin/activate     # Mac/Linux

# Install dependencies
pip install -e .
```

---

## Usage

### Enqueue a Job
```bash
queuectl enqueue '{"id":"job1","command":"echo hello"}'
queuectl enqueue '{"id":"job2","command":"sleep 5","max_retries":3}'
```

### Start Workers
```bash
# Start 1 worker (foreground)
queuectl worker start

# Start with custom count (runs multiple in background)
queuectl worker start --count 3
```

### Stop Workers
```bash
# From a different terminal
queuectl worker stop
```

### Check Status
```bash
queuectl status
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
# View dead jobs
queuectl dlq list

# Retry a dead job
queuectl dlq retry job1
```

### Configuration
```bash
queuectl config set max-retries 3
queuectl config set backoff-base 2
```

---

## Architecture

```
queuectl/
├── app/
│   ├── cli/
│   │   └── main_cli.py        # All CLI commands
│   ├── database/
│   │   └── db.py              # SQLite connection and schema
│   ├── repository/
│   │   └── job_repository.py  # All database queries
│   ├── services/
│   │   └── job_service.py     # Business logic
│   ├── workers/
│   │   ├── worker.py          # Worker loop and execution
│   │   └── pid.py             # PID file management
│   └── config.py              # Config read/write
├── pyproject.toml
├── DECISIONS.md
└── README.md
```

### How It Works

1. **Enqueue** — Jobs are stored in SQLite with `state = pending`
2. **Worker** — Polls the database, claims a pending job atomically, executes
   the shell command via `subprocess`
3. **Retry** — Failed jobs are scheduled for retry using exponential backoff
   (`delay = base ^ attempts`)
4. **DLQ** — After `max_retries` failures, job moves to `state = dead`
5. **Crash Recovery** — Worker updates a heartbeat every 10s. Jobs with
   expired heartbeats (>30s) are reset to pending automatically
6. **Graceful Shutdown** — SIGTERM/SIGINT finishes the current job before
   exiting

---

## Job Lifecycle

pending → processing → completed
↘
failed → (retry after backoff) → pending
↘ (max retries exceeded)
dead (DLQ)

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

| Key          | Default | Description                    |
|--------------|---------|--------------------------------|
| max-retries  | 3       | Maximum retry attempts per job |
| backoff-base | 2       | Base for exponential backoff   |

Config changes affect only newly-enqueued jobs. Already-enqueued jobs
store their own `max_retries` value at enqueue time.

---

## Testing the System

### Basic Job
```bash
queuectl enqueue '{"id":"test1","command":"echo hello"}'
queuectl worker start
```

### Retry + DLQ
```bash
queuectl enqueue '{"id":"fail1","command":"exit 1","max_retries":3}'
queuectl worker start
# Watch job retry 3 times then move to DLQ
queuectl dlq list
queuectl dlq retry fail1
```

### Crash Recovery
```bash
queuectl enqueue '{"id":"crash1","command":"sleep 300"}'
queuectl worker start
# Close the terminal window (simulates SIGKILL)
# Wait 35 seconds, then start worker again
queuectl worker start
# Job will be recovered automatically
```

---

## Demo Recording

[Link to demo recording](#) ← add your recording link here

---

## Design Decisions

See [DECISIONS.md](./DECISIONS.md) for detailed explanation of all
architectural choices.
