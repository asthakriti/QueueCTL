# Design Decisions

## 1. Atomic Job Claiming — Preventing Duplicate Execution

**File:** `app/repository/job_repository.py` — `claim_job()`

Two lines do the work. Both are required; either one alone is not enough.

```python
conn.execute("BEGIN IMMEDIATE")                    # (1)
...
UPDATE jobs SET state = 'processing', worker_heartbeat = ?, updated_at = ?
WHERE id = ? AND state = ?                         # (2)
```

**(1) `BEGIN IMMEDIATE`** acquires SQLite's RESERVED write lock *before* the
`SELECT` runs, so the read and the write are one serialisable transaction. This
is the line that matters. Without it the `SELECT` runs in autocommit mode and
takes no lock that survives to the `UPDATE` — N workers can all read the same
row, then all update it. SQLite serialises the *writes*, but every writer still
believes it won the row. A write lock acquired at the `UPDATE` does not make
read-then-write atomic; it has to be held from before the `SELECT`.

**(2) `WHERE id = ? AND state = ?`** is a compare-and-swap guard. The job is
only claimed if its state is still what we read a moment ago. If another worker
got there first, `cursor.rowcount` is 0, we `ROLLBACK` and return `None`, and
the loop retries. This is belt-and-braces: the claim stays correct even if the
transaction discipline is later broken by a refactor.

This holds across separate OS processes because SQLite's locking is enforced on
the database file itself — every process opening the same `.db` respects the
same lock. `get_connection()` enables WAL and a 30s `busy_timeout` so a blocked
writer waits rather than raising `database is locked`.

**Verified:** 8 processes racing for 1 job → exactly 1 winner. 20 jobs across 6
worker processes → 20 executions, 20 distinct jobs, 0 duplicates.

---

## 2. Crash Recovery Mechanism

**Mechanism:** heartbeat-based timeout detection, plus orphan reaping.

When a worker claims a job, the claiming `UPDATE` stamps `worker_heartbeat` in
the same statement, and a background thread refreshes it every
`HEARTBEAT_INTERVAL` (5s). `recover_stuck_jobs()` runs at the top of every
worker loop:

```sql
SELECT id, child_pgid FROM jobs
WHERE state = 'processing'
  AND worker_heartbeat IS NOT NULL
  AND worker_heartbeat < (now - 15 seconds)
```

**`IS NOT NULL` is load-bearing.** Treating a NULL heartbeat as "expired" means
a freshly claimed job — which has not had time to receive its first background
beat — looks abandoned to every other worker, and gets stolen instantly. That is
why the heartbeat is stamped at claim time rather than only by the beat thread.

**Orphan reaping.** A job's command is launched with `start_new_session=True`,
so it and everything it spawns share one process group; that group id is
recorded in `jobs.child_pgid`. When a worker is SIGKILLed the command is *not*
killed — it keeps running with no one waiting on it. Before requeueing a stuck
job, the recovering worker kills the recorded process group. Without this, the
orphan and the retry run the same command concurrently.

**Crash scenario step by step:**
- Worker claims job → `state = processing`, heartbeat stamped, `child_pgid` recorded
- Worker receives SIGKILL → no cleanup handler runs, command is orphaned
- Heartbeat updates stop
- After 15s (3 missed beats) another worker sees the expired heartbeat
- It kills the orphaned process group, resets the job to `pending`, re-runs it

**Worst-case recovery time:** ~16 seconds — well inside the 60s requirement.

**Remaining trade-off — this is at-least-once, not exactly-once.** *Claiming* is
exactly-once; *execution* is at-least-once. Two windows remain:

1. The worker finishes the command but is killed before writing `completed`.
2. The orphaned command completes its side effects in the gap between the kill
   and recovery noticing (up to ~16s).

Neither is closable by an external command runner — it cannot know whether a
foreign process's side effects landed. The honest answer is that job handlers
must be idempotent. Reaping the process group shrinks window 2 to the recovery
interval instead of the job's full remaining runtime.

---

## 3. DLQ Retry — Does it Reset Attempts?

**Decision:** Yes, `dlq retry` resets `attempts` to 0.

**Reasoning:** If attempts were NOT reset, a job with `max_retries=3` that
failed 3 times would immediately move back to DLQ on the very next failure —
giving it zero additional chances. Resetting to 0 gives the job a completely
fresh start, which is the expected behavior when an operator manually retries a
dead job.

**Trade-off:** The job gets `max_retries` additional attempts, not just one.
This is intentional — if an operator is retrying, they want it to actually have
a chance to succeed.

**Note on the boundary:** `_handle_failure` uses `attempts >= max_retries`, so
`max_retries=3` means three total attempts and two retries. This follows the
spec's normative sentence — *"after `max_retries` failed attempts, the job moves
to the DLQ"* — rather than the looser worked example, which shows three retry
delays (2s, 4s, 8s) and would imply a fourth attempt.

---

## 4. Worker Stop — Cross-Process Signaling

**Chosen approach:** one PID file per worker process, in an absolute directory.

**File:** `app/workers/pid.py`

Each worker writes `<db-dir>/.queuectl-pids/worker-<pid>.pid` on startup and
removes it on exit. `queuectl worker stop` reads every file in that directory,
prunes the ones whose process is gone, and sends SIGTERM to each live PID.

Two details that were wrong in an earlier version and are worth calling out:

- **The directory is absolute**, derived from `DB_PATH`. A relative
  `worker.pid` lands wherever the shell happens to be, so running the CLI from
  a different directory made `worker stop` unable to find the worker.
- **One file per process, not one file total.** A single shared `worker.pid`
  gets truncated by whichever worker started last; `worker stop` then stops only
  that one, and when it exits it deletes the file — leaving the other workers
  permanently unstoppable through the CLI.

Liveness is probed with `OpenProcess`/`GetExitCodeProcess` on Windows rather
than `os.kill(pid, 0)`, because Python on Windows maps `os.kill` to
`TerminateProcess` — signal 0 would kill the process we are only asking about.

**Alternatives considered:**

- **Control socket:** worker listens on a Unix socket; stop connects and sends a
  message. Rejected — more moving parts, no benefit at this scale, and no clean
  Windows story.
- **Database polling:** worker checks a `should_stop` flag. Rejected — adds
  latency up to the poll interval and constant write load, and does not help
  when the worker is wedged rather than idle.
- **PID files (chosen):** zero dependencies, instant delivery, works across any
  number of terminals.

**Multi-worker note:** `worker start --count N` spawns N separate OS processes,
not threads. `signal.signal()` only binds on the main thread, so N `Worker`
objects constructed on one main thread overwrite each other's handlers and only
the last one ever shuts down — the rest loop forever and the process hangs.
Separate processes give each worker its own signal handling, its own PID file,
and failure isolation.

---

## 5. Priority Queues — What Would Change?

**What survives unchanged:**

- Database schema (add one column: `priority INTEGER DEFAULT 0`)
- Worker execution logic
- Retry and backoff mechanism
- DLQ handling
- Crash recovery

**What breaks:**

- `claim_job()`'s `SELECT` — currently `ORDER BY created_at ASC`. Would become
  `ORDER BY priority DESC, created_at ASC`, and the composite index
  `(state, created_at)` would become `(state, priority, created_at)`.
- `enqueue` would need to accept an optional `priority` field.

The rest of the system is deliberately unaware of ordering — only the claiming
query decides which job is next.

---

## 6. Configuration Semantics

`config set max-retries N` and `config set backoff-base N` are persisted in the
`config` table and take effect as follows:

| Setting | Applies to |
|---|---|
| `max-retries` | Jobs enqueued **after** the change. Already-queued jobs keep the `max_retries` stamped on their row, so a job's retry budget cannot change underneath it mid-flight. A per-job `max_retries` in the enqueue JSON always wins. |
| `backoff-base` | **Immediately**, including in-flight jobs. It is read inside `_handle_failure()` on each failure rather than once at worker construction, so an operator can widen the backoff during an incident without restarting workers. It is one query on a failure path, not a hot loop. |
| `job-timeout` | The next job a worker starts. Default 300s; the command's whole process group is killed on timeout, then the job follows the normal retry path. |
