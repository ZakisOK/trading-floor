# Weeks 1 + 2 — Operator Handoff

**Date built:** 2026-04-19/20 (overnight session, single sitting).
**Plan source:** `.claude/_external_plan_review/`
**Status:** Code complete for Weeks 1 + 2. Live in your dev stack. **One blocker for trades to flow: missing ANTHROPIC_API_KEY.**

---

## TL;DR — what to do when you wake up

1. Set a real `ANTHROPIC_API_KEY=sk-ant-...` in `.env` (replace the placeholder). Without this, no LLM-based agent (Marcus, Vera, Rex, XRP Analyst) can produce signals → Diana never approves → no trades flow.
2. Restart the agents container: `docker compose restart agents`.
3. Watch a cycle complete: `docker logs -f trading-floor-agents-1 | grep -E "trading_cycle|atlas|sized_order"`.
4. Within minutes you should see: signals emitted → Diana approved → constructor decision → `atlas_order_filled` (sim) → `trade_outcomes` row in Postgres.
5. Run the K1/F1 drills (instructions in §3 below) once you've confirmed the pipeline. Those are the gates that unlock `alpaca_paper`.

---

## What shipped tonight

### Week 1 — Memory + Safety
- `alembic/versions/002_agent_episodes.py` — Timescale hypertable + immutability triggers + agent_version CHECK + 30d compression. Composite PK `(episode_id, ts)` per Timescale's hypertable rules.
- `src/core/cycle.py`, `src/core/versioning.py` — UUIDv7 cycle_id, `compute_agent_version` ({git_sha}:{model}:{prompt_hash}).
- `src/agents/registry.py` — startup `assert_versions()` gate.
- `src/agents/base.py` — extended `AgentState`, `BaseAgent.__init__` computes version, `analyze_with_heartbeat` emits one episode per call.
- `src/agents/sage.py` — `_build_initial_state` stamps cycle identity at graph entry.
- 7 active agents updated with real `model_name` + `prompt_template`.
- `src/streams/episode_writer.py` + `scripts/run_episode_writer.py` + docker-compose `episode-writer` service.
- `cycle_id` threaded through broker, alpaca_broker, position_monitor, Atlas, COMMANDER queue, audit, trades stream.
- `src/execution/position_source.py` — `PositionSource` Protocol + Sim/Alpaca impls + `VenueAwarePositionProvider` + `VenueAwareFlattener` + `BrokerUnavailableError`.
- `src/execution/risk_monitor.py` — venue-aware. `risk:metrics` reflects the venue's real book.
- `src/execution/alpaca_broker.py` — `flatten_all()` with per-position 30s timeout.
- `src/execution/position_monitor.py` — kill switch dispatches via `position_flattener`.
- `src/execution/broker.py` — silent Alpaca + live-exchange fallbacks REMOVED. Both activate kill switch + raise `BrokerUnavailableError`. Sizing call removed from `_paper_fill`; `quantity=0` → REJECTED.
- `src/execution/position_sizer.py` — new `PositionSizer.size(...) → SizedOrder` API.
- `src/api/main.py` — startup probe refuses to boot if venue=alpaca_paper/live and Alpaca unreachable. `/api/health/broker` endpoint.
- `src/execution/risk.py` — DELETED.
- `runbooks/episode-pipeline.md` with operator sign-off table.

### Week 2 — Portfolio + Outcomes
- `alembic/versions/003_trade_outcomes.py` — `trade_outcomes` (immutable) + `agent_contributions` (FK + UNIQUE) + `correlation_snapshots`.
- `src/core/config.py` — `AUTONOMY_MODE_LIMITS` dict.
- `src/execution/portfolio_snapshot.py` — `PortfolioSnapshot` frozen dataclass, 5s cache, reads correlation matrix.
- `src/agents/portfolio_constructor.py` — `PortfolioConstructorAgent` with: blackout windows, per-mode caps, gross exposure cap, per-symbol cap (downsize), correlation overlap (downsize), idempotency by `cycle_id`, shadow-mode flag.
- `src/agents/sage.py` — graph: `... → diana → constructor → atlas`. Conditional skip of atlas when sized_order is None or zero qty.
- `src/agents/atlas.py` — pure execution. Reads `sized_order` from state. Records contributors on BOTH BUY and SELL fills (B5), no confidence threshold filter (B5). Generates `trade_id` per execution; persists contributors to `paper:trade:{trade_id}:contributors` for outcome writer.
- `src/execution/broker.py _paper_fill` — stamps `trade_id` + `cycle_id` on the open position.
- `src/execution/position_monitor.py _exit_position` — emits `stream:trade_outcomes` event keyed on `trade_id` (B4).
- `src/streams/outcome_writer.py` — drains `stream:trade_outcomes` → `trade_outcomes` + `agent_contributions`. Joins `agent_version` from `agent_episodes`.
- `scripts/run_outcome_writer.py` + docker-compose `outcome-writer` service.
- `scripts/run_counterfactual_attribution.py` — Diana-replay nightly job. Single contributor → automatic hit. Multi: removes each agent in turn, checks if Diana flips. Idempotent on `counterfactual_hit IS NULL`.

### Tests — 66/66 passing
- `tests/test_week01_memory_pr.py` — 13 tests (T-CYCLE, T-VERSION, T-EPISODE, killswitch, missing-cycle-id).
- `tests/test_week01_safety_pr.py` — 13 tests (A1 dispatch, A2 K1 stub, A3 F1 stub, A4 S1 sizing coverage, A5 module removed).
- `tests/test_week01_immutability.py` — 4 DB-bound tests (T-IMMUT-01/02/03 + agent_version CHECK).
- `tests/test_week02_portfolio_pr.py` — 8 tests (T-PC-01/02/03/04, idempotency, shadow mode, broker unavailable).

### Live state right now (verified at 06:17 UTC)

| Component | Status |
|---|---|
| docker compose stack (api, agents, monitors, episode-writer, outcome-writer) | All running |
| Postgres migrations | Applied through 003 |
| `agent_episodes` rows | 108+ accumulating live |
| `stream:episodes` lag | 0 |
| `stream:trade_outcomes` | Empty (no trades yet) |
| `risk:metrics.portfolio_value` | 10,000.00 (sim, no positions) |
| `config:system.autonomy_mode` | TRUSTED |
| `config:system.execution_venue` | sim |

---

## §1 — Fix the API key (5 min)

```bash
# Edit .env, replace this line:
ANTHROPIC_API_KEY=your_anthropic_api_key_here
# with:
ANTHROPIC_API_KEY=sk-ant-...

# Restart agents container:
docker compose restart agents

# Watch a cycle:
docker logs -f trading-floor-agents-1
```

Within ~30s you should see:
```
trading_cycle_started cycle_id=... symbol=BTC/USDT
signal_emitted agent=Marcus direction=LONG confidence=0.7
diana_risk_check approved=True ...
constructor_decision approved=True notional=200 ...
atlas_order_filled symbol=BTC/USDT side=BUY ...
```

## §2 — Verify trade pipeline end-to-end (10 min, after §1)

Once a sim trade opens, position_monitor will eventually hit a stop or target and emit a structured exit:

```bash
# trade_outcomes
docker exec trading-floor-postgres-1 psql -U tradingfloor -d tradingfloor -c "
SELECT trade_id, symbol, direction, pnl_usd, exit_reason, exit_ts
FROM trade_outcomes ORDER BY exit_ts DESC LIMIT 5;
"

# Per-trade attribution
docker exec trading-floor-postgres-1 psql -U tradingfloor -d tradingfloor -c "
SELECT t.trade_id, t.symbol, t.pnl_usd, c.agent_id, c.signal_direction,
       c.matched_trade_direction, c.counterfactual_hit, c.attributed_pnl_usd
FROM trade_outcomes t
JOIN agent_contributions c USING (trade_id)
ORDER BY t.exit_ts DESC LIMIT 20;
"
```

`counterfactual_hit` is NULL until you run the attribution job:

```bash
docker exec trading-floor-agents-1 python scripts/run_counterfactual_attribution.py --limit 100
```

## §3 — Operator gates (need you, not me)

These are the Week 1 + Week 2 exit criteria I cannot complete autonomously. Each produces an artifact for `evidence/week-01/` or `evidence/week-02/`.

### K1 drill — kill switch in alpaca_paper (45 min)

**Pre-req:** real Alpaca paper credentials in `.env`.

```bash
# 1. Force venue to alpaca_paper
docker exec trading-floor-redis-1 redis-cli -a change_me_local_only HSET config:system execution_venue alpaca_paper

# 2. Restart api so the probe runs
docker compose restart api

# 3. Verify probe passes
docker logs trading-floor-api-1 --tail 20 | grep broker_probe

# 4. Open 2 small Alpaca paper positions manually

# 5. Trigger kill switch
curl -X POST http://localhost:8000/api/orders/kill

# 6. Within 60s verify both Alpaca positions closed
docker exec trading-floor-redis-1 redis-cli -a change_me_local_only HGETALL risk:metrics
docker exec trading-floor-redis-1 redis-cli -a change_me_local_only GET kill_switch:active

# Save journalctl excerpt + Redis output to evidence/week-01/K1-drill.txt
```

### F1 drill — credential failure (20 min)

```bash
# 1. Set venue back to alpaca_paper
docker exec trading-floor-redis-1 redis-cli -a change_me_local_only HSET config:system execution_venue alpaca_paper

# 2. Reset kill switch
docker exec trading-floor-redis-1 redis-cli -a change_me_local_only SET kill_switch:active false

# 3. Invalidate Alpaca creds
docker exec trading-floor-redis-1 redis-cli -a change_me_local_only HSET config:alpaca api_key INVALID

# 4. Wait for next cycle / trigger one

# 5. Expect: kill_switch:active = "true", reason contains "alpaca_unavailable"
docker exec trading-floor-redis-1 redis-cli -a change_me_local_only GET kill_switch:reason
docker logs trading-floor-agents-1 --tail 30 | grep -E 'alpaca|kill'
```

### P1 drill — paper trading end-to-end (Week 2 exit gate)

After API key fix + K1 + F1 pass:

```bash
docker exec trading-floor-redis-1 redis-cli -a change_me_local_only HSET config:system execution_venue alpaca_paper
docker compose restart api

# Watch for 2 hours. Verify every trade has contributors:
docker exec trading-floor-postgres-1 psql -U tradingfloor -d tradingfloor -c "
SELECT t.trade_id, COUNT(c.contribution_id) AS contributors
FROM trade_outcomes t
LEFT JOIN agent_contributions c USING (trade_id)
WHERE t.exit_ts > NOW() - INTERVAL '2 hours'
GROUP BY t.trade_id
HAVING COUNT(c.contribution_id) = 0;
"
# Expect zero rows.
```

### Runbook walkthrough (30 min)

Read `runbooks/episode-pipeline.md` end-to-end. Sign §7 sign-off table. Commit.

---

## §4 — Why no $10k actuals overnight (revisited, with Week 2 progress)

You asked for actuals from a $10k paper account by morning. **What you have:**
- The system is *eligible* to start producing real paper actuals as soon as the API key + drills are done.
- Week 2's PortfolioConstructor + outcome linking + counterfactual attribution is ALREADY BUILT — every paper trade will be:
  - sized correctly (no more zero-quantity to Alpaca)
  - capped per autonomy mode (COMMANDER 2%/5%/150%/10%, TRUSTED 3%/7%/200%/15%, YOLO 5%/12%/300%/20%)
  - rejected during blackout windows
  - written to `trade_outcomes` with full P&L
  - linked back to contributing agents
  - attributable to specific agent(s) whose vote moved the decision (after nightly counterfactual job runs)

**What you don't have:**
- Actual fills. Until ANTHROPIC_API_KEY is set + drills run, the cycle path produces no signals → no trades.

The gap between "code done" and "data flowing" is now ~30 min of your time tomorrow morning.

---

## §5 — Status check at a glance

| Item | State |
|---|---|
| Spec / Plan loaded | ✅ |
| Phase 0 verification | ✅ |
| Memory PR — code | ✅ |
| Safety PR — code | ✅ |
| Week 2 Portfolio PR — code | ✅ |
| Week 2 Outcomes PR — code | ✅ |
| Unit tests (66) | ✅ all passing |
| DB immutability tests (4) | ✅ passing against live Postgres |
| All containers rebuilt + restarted | ✅ |
| ANTHROPIC_API_KEY set | ⏸ **operator** (5 min) |
| K1 drill (alpaca_paper kill switch) | ⏸ operator (45 min) |
| F1 drill (credential failure) | ⏸ operator (20 min) |
| P1 drill (paper trading 2h) | ⏸ operator (2h passive) |
| Runbook walkthrough sign-off | ⏸ operator (30 min) |
| `evidence/week-01/` + `evidence/week-02/` artifacts | ⏸ operator |
| Counterfactual job nightly schedule | ⏸ operator (cron entry) |
| Week 8 live trading readiness review | ⏸ 6+ weeks away (PRINCIPLE #1) |

When the ⏸ items become ✅, ping me and I'll start Week 3 — measurement (Brier/expectancy scoring) + replay engine.
