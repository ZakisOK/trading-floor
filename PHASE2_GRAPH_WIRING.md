# Phase 2 Graph Wiring — Needed Changes to src/agents/graph.py

> DO NOT MODIFY graph.py until these changes are reviewed.
> This document captures exactly what needs to change and why.

---

## 1. Add `regime_detector` as a pre-step before all agents

### What to add

Import `regime_detector` from `src.signals.regime_detector` and run it
at the start of `run_trading_cycle`, before `trading_graph.ainvoke`.

```python
# In run_trading_cycle(), after reading Redis regime:
from src.signals.regime_detector import regime_detector

# Fetch price history for the symbol (needs to come from market_data or a feed)
prices = market_data.get("price_history", [])  # list of recent closes
if prices:
    regime = await regime_detector.detect_and_publish(symbol, prices)
else:
    regime = await regime_detector.get_cached_regime(symbol)
```

The detected regime is then injected into the initial AgentState:
```python
initial: AgentState = {
    ...
    "market_data": {"symbol": symbol, "regime": regime, **market_data},
    ...
}
```

This is already partially wired — `run_trading_cycle` reads `market:regime`
from Redis. The change upgrades from the global BTC key to a per-symbol key
and uses RegimeDetector's logic directly instead of the Portfolio Chief's
5-minute broadcast.

**Why:** Regime detection currently runs every 5 minutes on BTC only. With
this change, every symbol gets its own real-time regime label computed from
its own price history at the start of each cycle.

---

## 2. Add `carry_agent` running in parallel with the existing entry nodes

### Current entry node (graph.py line ~78)

```python
async def _run_parallel_entry(state: AgentState) -> AgentState:
    results = await asyncio.gather(
        marcus.analyze(state),
        copy_trade_scout.analyze(state),
        return_exceptions=True,
    )
```

### Required change

```python
from src.agents.carry_agent import CarryAgent

carry_agent = CarryAgent()

async def _run_parallel_entry(state: AgentState) -> AgentState:
    results = await asyncio.gather(
        marcus.analyze(state),
        copy_trade_scout.analyze(state),
        carry_agent.analyze(state),   # <-- add this
        return_exceptions=True,
    )
```

CarryAgent is pure calculation (no LLM, <200ms), so it adds negligible latency
to the parallel entry phase.

Also add the node to the LangGraph StateGraph:
```python
carry_agent_inst = CarryAgent()
graph.add_node("carry_agent", carry_agent_inst.analyze)
```

And update `build_trading_graph()` to run it in parallel at entry:
```python
# Option A: fold into _run_parallel_entry (simpler, recommended)
# Option B: add as a separate parallel branch off the entry point
```

Option A is simpler and avoids restructuring the graph edges.

**Why:** Carry is a signal generator, not a risk filter. It belongs at entry
alongside Marcus and CopyTradeScout so its signal reaches Nova for aggregation.

---

## 3. Pass regime into graph state so all agents can read it

This is already done. Nova reads `state["market_data"]["regime"]` and
also falls back to reading `market:regime:{symbol}` from Redis.

The remaining cleanup: remove the legacy `market:regime` (no symbol suffix)
key read in `run_trading_cycle` and replace with
`await regime_detector.get_cached_regime(symbol)`.

```python
# Current (graph.py ~line 155):
regime = await redis.get("market:regime") or "UNKNOWN"

# Replace with:
regime = await regime_detector.get_cached_regime(symbol)
```

---

## 4. Nova uses regime-weighted accuracy — already implemented

Nova (Phase 2) already calls:
```python
weight = await agent_memory.get_agent_accuracy(
    agent_id, regime=regime, last_n=REGIME_ACCURACY_WINDOW
)
```

No graph wiring change needed for this — it works as soon as the regime
label reaches Nova via AgentState.

---

## Summary of graph.py changes (ordered by priority)

| Priority | Change | File | Lines affected |
|----------|--------|------|----------------|
| 1 | Import + instantiate `CarryAgent` | graph.py | ~line 35-45 |
| 2 | Add `carry_agent.analyze` to `_run_parallel_entry` gather | graph.py | ~line 78-90 |
| 3 | Replace legacy `market:regime` Redis read with `regime_detector.get_cached_regime(symbol)` | graph.py | ~line 155 |
| 4 | (Optional) Add `price_history` to market_data so `detect_and_publish` can run per-symbol | graph.py + data feeds | ~line 150-165 |

Changes 1-3 are safe to make now. Change 4 requires the data feed layer to
supply a `price_history` list — defer until the feed layer exposes this.
