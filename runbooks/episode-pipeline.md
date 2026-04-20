# Runbook — Episode Pipeline (Week 1 / B5)

**Purpose.** Keep `stream:episodes` → `agent_episodes` healthy. This is the
substrate every later week (replay, attribution, reflection, retrieval) reads
from. If it stops, those weeks stop being trustworthy.

**Owners.** Whoever is on call for the trading-floor systemd stack.

**Scope.** Producer (`BaseAgent._emit_episode`), stream (`stream:episodes`),
consumer group (`cg:episode_writer`), writer service
(`trading-episode-writer.service`), table (`agent_episodes`).

---

## 1. Daily health check

Run the four checks below. Anything red goes to escalation in §5.

### 1a. Producer is emitting

```bash
# Latest episode timestamp on the stream
redis-cli -a "$REDIS_PASSWORD" XREVRANGE stream:episodes + - COUNT 1
```

Expect a row from within the last 60 seconds during active trading hours. If
the latest entry is >5 min old AND there is active cycle traffic
(`stream:audit` has recent `signal_emitted` events), the producer is broken
— check API logs for `episode_emit_failed` warnings or
`episode_missing_cycle_id` errors.

### 1b. Consumer is alive

```bash
systemctl status trading-episode-writer
journalctl -u trading-episode-writer --since "10 min ago" -n 50
```

Expect `active (running)` and recent `episode_written` log lines (DEBUG; raise
log level if you don't see any: `LOG_LEVEL=DEBUG`).

### 1c. Lag is bounded

```bash
redis-cli -a "$REDIS_PASSWORD" XINFO GROUPS stream:episodes
```

The line for `cg:episode_writer` shows `pending` and `lag`. **Hard SLO:**
`lag < 100` under normal load. **Soft SLO:** p95 write lag (Redis emit →
Postgres row) < 2s — measured by the integration test E1 and observable via
Phoenix traces.

If `lag` climbs past 1000 and stays there, see §3 (Postgres outage).

### 1d. Postgres row count vs expected

```sql
-- Episodes per cycle should equal (agents in graph) * (cycles in window).
-- For the legacy graph: 7 agents (marcus, vera, rex, [xrp_analyst on XRP],
-- polymarket_scout, diana, atlas). xrp_analyst makes the multiplier 8 only
-- on XRP cycles.

SELECT
    DATE_TRUNC('hour', ts) AS hour,
    COUNT(DISTINCT cycle_id) AS cycles,
    COUNT(*) AS episodes,
    ROUND(COUNT(*)::numeric / NULLIF(COUNT(DISTINCT cycle_id), 0), 2) AS episodes_per_cycle
FROM agent_episodes
WHERE ts > NOW() - INTERVAL '6 hours'
GROUP BY 1
ORDER BY 1 DESC;
```

Expect `episodes_per_cycle` ≈ 7.0–8.0 for XRP-heavy hours, ≈ 7.0 otherwise.
Sustained <6.5 means an agent is silently failing — find it:

```sql
SELECT agent_id, COUNT(*) FILTER (WHERE error IS NOT NULL) AS errors,
       COUNT(*) AS total
FROM agent_episodes
WHERE ts > NOW() - INTERVAL '1 hour'
GROUP BY agent_id
ORDER BY errors DESC;
```

---

## 2. Verifying immutability (drill T-IMMUT)

Run quarterly to confirm the trigger is still in place.

```sql
-- Must raise: "agent_episodes is immutable. ..."
UPDATE agent_episodes
   SET symbol = 'X'
 WHERE episode_id = (SELECT episode_id FROM agent_episodes LIMIT 1);

-- Must raise the same exception
DELETE FROM agent_episodes
 WHERE episode_id = (SELECT episode_id FROM agent_episodes LIMIT 1);
```

If either succeeds, the trigger has been dropped. Stop the world:

```bash
systemctl stop trading-floor trading-paper trading-monitors
```

Restore the trigger from migration 002 (`alembic upgrade head` against a
clean shadow DB and copy out the trigger DDL) and post-mortem how it was
dropped.

---

## 3. Postgres outage (≤10 min)

**Behavior.** Producer keeps emitting to `stream:episodes` (Redis only —
Postgres is not in the hot path). Consumer logs `consumer_loop_error` every
sweep and re-tries; messages stay un-acked.

**Action while down.**
1. Don't restart the writer — it's already retrying.
2. Confirm Redis is fine: `redis-cli PING` → `PONG`.
3. Confirm the bound is holding: stream max length should plateau near
   `EPISODES_MAXLEN` (100k). At ~7 episodes/cycle and 60 cycles/hour that's
   ~166 hours of buffer.

**After Postgres returns.**
1. Watch lag drain: `redis-cli XINFO GROUPS stream:episodes`. Should drop
   under 100 within minutes.
2. Confirm row count matches expected via §1d. If it doesn't, the missing
   range is permanent loss — note the window in `evidence/incidents/`.

If the outage exceeds buffer capacity, the spec accepts partial loss
(B4 contract: "episode loss is preferable to cycle loss"). Document the loss
window and move on. Audit-only rebuild path is in §4.

---

## 4. Bounded recovery from `stream:audit` (last resort)

If both `stream:episodes` and `agent_episodes` lose data for the same window,
you can reconstruct cycle-level facts (but not full agent context) from
`stream:audit`:

```bash
# Pull cycle outcomes for the missing window
redis-cli -a "$REDIS_PASSWORD" XRANGE stream:audit \
    "$(date -u -d '2 hours ago' +%s)000-0" "$(date -u +%s)000-0" \
    | grep -E 'signal_emitted|trade_executed'
```

Audit entries carry `cycle_id` (Week 1 / B1 #5). For each missing cycle you
can reconstruct: which agents emitted signals, what direction, what
confidence — but NOT the input state, market snapshot, or reasoning text.
That's the cost of a both-stores outage. There is no way to fully reconstruct
episodes without their original payload.

Write the reconstructed rows via `episode_corrections`, **never** by inserting
into `agent_episodes` directly (the trigger will reject it for any role
except `migration_admin`, and using that role bypasses the safety contract).

---

## 5. Escalation

Trigger paths:

| Symptom | Page |
|---|---|
| Episode write lag > 30s for > 5 min | Yes — primary on-call |
| Producer silent for > 10 min during trading hours | Yes — primary on-call |
| Immutability drill fails | Yes — primary AND owner |
| Postgres outage > 30 min | Yes — primary AND DB owner |
| Lag > 50% of EPISODES_MAXLEN | Yes — capacity owner |

Escalation message template:

```
EPISODE PIPELINE ALERT
- Symptom: <which check from §1 failed>
- First seen: <ts>
- Cycle traffic: <yes/no>  (check stream:audit signal_emitted last 5 min)
- Immediate impact: <describe — typically: replay/attribution will have gaps>
- Action taken: <none / restarted writer / paged DB>
```

---

## 6. Killswitch for episode emission

The producer reads `feature:episode_pipeline_enabled` from Redis at every
emit. To mute the producer (e.g. if a bug is corrupting payloads) without
redeploying:

```bash
redis-cli -a "$REDIS_PASSWORD" SET feature:episode_pipeline_enabled false
```

Cycles continue to run normally — they just stop generating episodes. Re-enable
with `SET ... true` (or `DEL`, since default-on is the absent-key behavior).

This is a **temporary** measure. Any window with the flag off creates a hard
gap in the data — note it in `evidence/incidents/` and re-enable as soon as
the bug is patched.

---

## 7. Operator sign-off

| Check | Date | Operator | Result |
|---|---|---|---|
| Walked through §1 daily checks | | | |
| Walked through §2 immutability drill | | | |
| Walked through §3 Postgres outage drill | | | |
| Read §6 killswitch and confirmed Redis access | | | |

PR cannot ship Week 1 closed without all four signed.
