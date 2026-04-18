---
name: halt_protocol
description: Procedure when the kill switch trips, audit gap is detected, or any agent signals unsafe state
triggers: [kill_switch, audit_gap, unsafe_state, emergency_stop]
requires_tools: [cancel_open_orders, set_agent_status, produce_audit]
cost_tokens: 1200
---
## When to use
Execute whenever the operator engages the kill switch, Diana raises an unapproved risk breach, the audit hash chain breaks, or any agent posts `status=unsafe`. This SOP takes precedence over every other active skill — abandon partial work and run it end to end.

## Procedure
1. Publish `stream:alerts` event `severity=critical` with reason and originating agent.
2. Cancel all open orders across every connected broker (`atlas.cancel_all`). Confirm each cancel by order id in the audit stream.
3. Flatten any positions that are in-progress inside a pending bracket — do not open new hedges.
4. Set every agent's heartbeat hash to `status=paused`. Sage stops accepting new trading cycles.
5. Snapshot current P&L, open positions, and pending signals into Graphiti under `group_id=firm` as `episode_type=halt_snapshot`.
6. Write an immutable audit entry with the SHA-256 hash of the previous entry plus reason, operator id, and ISO-8601 UTC timestamp.
7. Page the operator via the configured alert channel. Do not resume without an explicit `mode=RESUME` command from the operator.

## Rubric / Decision rule
If any cancel confirmation times out past 5 seconds, escalate to broker-level API key revocation. Partial flatten is never acceptable — either all positions are closed in a venue or operator is paged.

## Post-conditions
- Writes `halt_snapshot` episode to firm memory
- Publishes a `kill_switch_engaged` audit record
- Every agent reports `status=paused` on next heartbeat
