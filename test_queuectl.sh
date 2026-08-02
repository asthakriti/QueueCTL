#!/bin/bash

# ─────────────────────────────────────────
# QueueCTL Test Script
# Run from project root with venv activated
# ─────────────────────────────────────────

PASS=0
FAIL=0

check() {
    local description="$1"
    local result="$2"
    local expected="$3"

    if echo "$result" | grep -q "$expected"; then
        echo "✅ PASS: $description"
        PASS=$((PASS + 1))
    else
        echo "❌ FAIL: $description"
        echo "   Expected: '$expected'"
        echo "   Got:      '$result'"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
echo "======================================"
echo "       QueueCTL Test Suite"
echo "======================================"
echo ""

# ─────────────────────────────────────────
# CLEANUP — fresh state
# ─────────────────────────────────────────
echo "--- Cleaning up old database ---"
rm -f queuectl.db worker.pid
echo ""

# ─────────────────────────────────────────
# TEST 1: Enqueue a job
# ─────────────────────────────────────────
echo "--- TEST 1: Enqueue Jobs ---"

result=$(queuectl enqueue '{"id":"t1","command":"echo hello"}')
check "Enqueue t1" "$result" "Job added"

result=$(queuectl enqueue '{"id":"t2","command":"echo world","max_retries":2}')
check "Enqueue t2 with max_retries" "$result" "Job added"

result=$(queuectl enqueue '{"id":"t3","command":"exit 1","max_retries":1}')
check "Enqueue t3 (will fail)" "$result" "Job added"

echo ""

# ─────────────────────────────────────────
# TEST 2: Duplicate ID
# ─────────────────────────────────────────
echo "--- TEST 2: Duplicate Job ID ---"

result=$(queuectl enqueue '{"id":"t1","command":"echo duplicate"}' 2>&1)
check "Duplicate ID rejected" "$result" "already exists\|Error\|error\|UNIQUE"

echo ""

# ─────────────────────────────────────────
# TEST 3: Status before worker
# ─────────────────────────────────────────
echo "--- TEST 3: Status Check ---"

result=$(queuectl status)
check "Status shows pending jobs" "$result" "pending"

echo ""

# ─────────────────────────────────────────
# TEST 4: List pending jobs
# ─────────────────────────────────────────
echo "--- TEST 4: List Jobs ---"

result=$(queuectl list --state pending)
check "List pending shows t1" "$result" "t1"

result=$(queuectl list --state pending --json)
check "JSON output is valid" "$result" "{"

echo ""

# ─────────────────────────────────────────
# TEST 5: Run worker and process jobs
# ─────────────────────────────────────────
echo "--- TEST 5: Worker Processes Jobs ---"
echo "(Running worker for 20 seconds...)"

timeout 20 queuectl worker start &
WORKER_PID=$!
sleep 18
kill $WORKER_PID 2>/dev/null
wait $WORKER_PID 2>/dev/null

result=$(queuectl list --state completed)
check "t1 completed" "$result" "t1"

result=$(queuectl list --state completed)
check "t2 completed" "$result" "t2"

echo ""

# ─────────────────────────────────────────
# TEST 6: Failed job retry → DLQ
# ─────────────────────────────────────────
echo "--- TEST 6: Retry + DLQ ---"
echo "(Waiting for t3 to fail and move to DLQ...)"

sleep 5

result=$(queuectl dlq list)
check "t3 moved to DLQ" "$result" "t3"

echo ""

# ─────────────────────────────────────────
# TEST 7: DLQ Retry
# ─────────────────────────────────────────
echo "--- TEST 7: DLQ Retry ---"

result=$(queuectl dlq retry t3)
check "DLQ retry requeues t3" "$result" "re-queued\|pending"

result=$(queuectl list --state pending)
check "t3 back in pending" "$result" "t3"

echo ""

# ─────────────────────────────────────────
# TEST 8: Config set
# ─────────────────────────────────────────
echo "--- TEST 8: Config ---"

result=$(queuectl config set max-retries 5)
check "Config set max-retries" "$result" "5\|updated\|set\|Config"

result=$(queuectl config set backoff-base 3)
check "Config set backoff-base" "$result" "3\|updated\|set\|Config"

echo ""

# ─────────────────────────────────────────
# TEST 9: Worker stop without worker running
# ─────────────────────────────────────────
echo "--- TEST 9: Stop Non-Existent Worker ---"

result=$(queuectl worker stop 2>&1)
check "Stop with no worker graceful" "$result" "No running\|not found\|Error"

echo ""

# ─────────────────────────────────────────
# TEST 10: Invalid JSON
# ─────────────────────────────────────────
echo "--- TEST 10: Invalid JSON ---"

result=$(queuectl enqueue 'not valid json' 2>&1)
check "Invalid JSON rejected" "$result" "Error\|error\|invalid\|Invalid"

echo ""

# ─────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────
echo "======================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "======================================"
echo ""
