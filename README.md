# QueueCTL

A CLI-based background job queue system with worker processes, automatic
retries with exponential backoff, and a Dead Letter Queue (DLQ).

---

## Setup

**Requirements:** Python 3.9+, Git Bash (on Windows) or any bash terminal

```bash
# Clone the repository
git clone <your-repo-url>
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
