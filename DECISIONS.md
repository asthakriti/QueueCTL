# Design Decisions

## 1. Atomic Job Claiming — Preventing Duplicate Execution

**File:** `app/repository/job_repository.py` — `claim_job()` function

The critical section is:
```sql
SELECT * FROM jobs WHERE state = 'pending' ORDER BY created_at ASC LIMIT 1
UPDATE jobs SET state = 'processing' WHERE id = ?
```

SQLite guarantees that write operations acquire an exclusive database-level
lock. When Worker A is executing the UPDATE, Worker B's UPDATE will block
until the lock is released. Since we SELECT then immediately UPDATE within
the same connection, no other worker can claim the same job between these
two operations.

This is atomic across separate OS processes because SQLite's locking is
enforced at the file system level — all processes share the same .db file
and respect the same lock.

---

## 2. Crash Recovery Mechanism

**Mechanism:** Heartbeat-based timeout detection

When a worker picks up a job, it:
1. Sets `state = 'processing'`
2. Starts a background thread that updates `worker_heartbeat` every 10 seconds

On every worker loop iteration, `recover_stuck_jobs()` runs:
```sql
UPDATE jobs SET state = 'pending'
WHERE state = 'processing'
AND worker_heartbeat < (now - 30 seconds)
```

**Crash scenario step by step:**
- Worker picks job → state = processing, heartbeat starts
- Worker receives SIGKILL → no cleanup handler runs
- Heartbeat updates stop
- After 30 seconds → next worker detects expired heartbeat
- Job reset to pending → picked up and executed again

**Worst-case recovery time:** 30 seconds (well within the 60s requirement)

**Trade-off:** There is a small window where a job could run twice — if the
worker completes the job but crashes before updating state to 'completed'.
This is an acceptable trade-off for simplicity. A production system would
use idempotent job handlers to handle this.

---

## 3. DLQ Retry — Does it Reset Attempts?

**Decision:** Yes, `dlq retry` resets `attempts` to 0.

**Reasoning:** If attempts were NOT reset, a job with `max_retries=3` that
failed 3 times would immediately move back to DLQ on the very next failure —
giving it zero additional chances. Resetting to 0 gives the job a completely
fresh start, which is the expected behavior when an operator manually retries
a dead job.

**Trade-off:** The job gets `max_retries` additional attempts, not just one.
This is intentional — if an operator is retrying, they want it to actually
have a chance to succeed.

---

## 4. Worker Stop — Cross-Process Signaling

**Chosen approach:** PID file (`worker.pid`)

When a worker starts, it writes its PID to `worker.pid`.
`queuectl worker stop` reads this file and sends SIGTERM to that PID.

**Alternatives considered:**

- **Control socket:** Worker listens on a Unix socket; stop command connects
  and sends a message. Rejected — significantly more complex to implement,
  and provides no meaningful benefit for this use case.

- **Database polling:** Worker periodically checks a `should_stop` flag in
  the database. Rejected — introduces latency (up to poll interval) and adds
  unnecessary database load.

- **PID file (chosen):** Simple, zero dependencies, instant signal delivery.
  Works across any number of terminals. Limitation: only tracks one worker
  process per PID file. For multiple workers, would need per-worker PID files.

---

## 5. Priority Queues — What Would Change?

**What survives unchanged:**
- Database schema (add one column: `priority INTEGER DEFAULT 0`)
- Worker execution logic
- Retry and backoff mechanism
- DLQ handling
- Crash recovery

**What breaks:**
- `claim_job()` query — currently orders by `created_at ASC` only.
  Would need: `ORDER BY priority DESC, created_at ASC`
- Enqueue command — would need to accept optional `priority` field

The rest of the system is designed to be unaware of ordering — only the
claiming mechanism cares about which job to pick next.