"""
graph.py — LangGraph multi-agent research pipeline builder.

Pipeline routes:
  marcus ──► vera ──► rex ──┬──► [xrp_analyst if XRP] ──────► polymarket_scout ──► nova
                            └──► [commodities_analyst if =F] ─► polymarket_scout ──► nova
  copy_trade_scout runs in parallel with marcus (both are signal generators).
  Their outputs merge into vera → rex → specialist → polymarket_scout → nova.

Nova aggregates all signals with Bayesian weighting and forwards conviction
packets to stream:trade_desk:inbox for Desk 2 to act on.
"""
from __future__ import annotations

import structlog

from src.agents.base import AgentState, BaseAgent

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Lazy imports so the app boots even if langgraph isn't installed yet
# ---------------------------------------------------------------------------
try:
    from langgraph.graph import StateGraph, END as _END  # type: ignore[import]
    _LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _LANGGRAPH_AVAILABLE = False
    _END = "__end__"

from src.agents.marcus import MarcusAgent
from src.agents.vera import VeraAgent
from src.agents.rex import RexAgent
from src.agents.nova import NovaAgent
from src.agents.atlas import AtlasAgent
from src.agents.xrp_analyst import XRPAnalystAgent
from src.agents.polymarket_scout import PolymarketScoutAgent
from src.agents.commodities_analyst import CommoditiesAnalystAgent
from src.agents.copy_trade_scout import CopyTradeScoutAgent

marcus = MarcusAgent()
vera = VeraAgent()
rex = RexAgent()
nova = NovaAgent()
atlas = AtlasAgent()
xrp_analyst = XRPAnalystAgent()
polymarket_scout = PolymarketScoutAgent()
commodities_analyst = CommoditiesAnalystAgent()
copy_trade_scout = CopyTradeScoutAgent()


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

def _route_after_rex(state: AgentState) -> str:
    """
    Route to specialist agent based on symbol type:
      XRP  → xrp_analyst
      =F   → commodities_analyst (futures ticker)
      else → polymarket_scout (skip specialist)
    """
    market = state.get("market_data") or {}
    symbol = market.get("symbol", "")
    if "XRP" in symbol:
        return "xrp_analyst"
    if symbol.endswith("=F"):
        return "commodities_analyst"
    return "polymarket_scout"


async def _run_parallel_entry(state: AgentState) -> AgentState:
    """
    Run marcus and copy_trade_scout concurrently as parallel entry nodes.
    Both are signal generators — their outputs merge into the state before vera.
    """
    import asyncio
    results = await asyncio.gather(
        marcus.analyze(state),
        copy_trade_scout.analyze(state),
        return_exceptions=True,
    )

    # Merge signals from both into a unified state
    merged = dict(state)
    all_signals = list(state.get("signals", []))

    for result in results:
        if isinstance(result, Exception):
            logger.warning("parallel_entry_agent_error err=%s", result)
            continue
        all_signals.extend(result.get("signals", []))
        # Take the latest market_data if either updated it
        if result.get("market_data"):
            merged["market_data"] = result["market_data"]

    merged["signals"] = all_signals
    return AgentState(**merged)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_trading_graph():  # type: ignore[return]
    """
    Build and compile the LangGraph research workflow.

    Route:
      parallel_entry (marcus + copy_trade_scout) → vera → rex →
      [xrp_analyst | commodities_analyst | direct] → polymarket_scout → nova

    Nova publishes the conviction packet to stream:trade_desk:inbox.
    Atlas is called by TradeDeskAgent (Desk 2), not here.
    """
    if not _LANGGRAPH_AVAILABLE:
        return None

    graph = StateGraph(AgentState)

    # Entry: run marcus + copy_trade_scout in parallel, merge signals
    graph.add_node("parallel_entry", _run_parallel_entry)
    graph.add_node("vera", vera.analyze)
    graph.add_node("rex", rex.analyze)
    graph.add_node("xrp_analyst", xrp_analyst.analyze)
    graph.add_node("commodities_analyst", commodities_analyst.analyze)
    graph.add_node("polymarket_scout", polymarket_scout.analyze)
    graph.add_node("nova", nova.analyze)

    graph.set_entry_point("parallel_entry")
    graph.add_edge("parallel_entry", "vera")
    graph.add_edge("vera", "rex")
    graph.add_conditional_edges(
        "rex",
        _route_after_rex,
        {
            "xrp_analyst": "xrp_analyst",
            "commodities_analyst": "commodities_analyst",
            "polymarket_scout": "polymarket_scout",
        },
    )
    graph.add_edge("xrp_analyst", "polymarket_scout")
    graph.add_edge("commodities_analyst", "polymarket_scout")
    graph.add_edge("polymarket_scout", "nova")
    graph.add_edge("nova", _END)

    return graph.compile()


trading_graph = build_trading_graph()


async def run_trading_cycle(symbol: str, market_data: dict) -> AgentState:
    """Run a full research cycle for a symbol through all Desk 1 agents."""
    from src.core.redis import get_redis
    redis = get_redis()
    try:
        regime = await redis.get("market:regime") or "UNKNOWN"
    except Exception:
        regime = "UNKNOWN"

    initial: AgentState = {
        "agent_id": "graph",
        "agent_name": "Research Graph",
        "messages": [],
        "market_data": {"symbol": symbol, "regime": regime, **market_data},
        "signals": [],
        "risk_approved": False,
        "final_decision": None,
        "confidence": 0.0,
        "reasoning": "",
    }

    if trading_graph is None:
        # Fallback: run agents sequentially without LangGraph
        import asyncio
        state = initial
        sym = (state.get("market_data") or {}).get("symbol", "")

        # Parallel entry (sequential fallback)
        import asyncio
        entry_results = await asyncio.gather(
            marcus.analyze(state),
            copy_trade_scout.analyze(state),
            return_exceptions=True,
        )
        merged_signals = list(state.get("signals", []))
        for r in entry_results:
            if not isinstance(r, Exception):
                merged_signals.extend(r.get("signals", []))
        merged = dict(state)
        merged["signals"] = merged_signals
        state = AgentState(**merged)

        # Main pipeline
        state = await vera.analyze(state)
        state = await rex.analyze(state)

        if "XRP" in sym:
            state = await xrp_analyst.analyze(state)
        elif sym.endswith("=F"):
            state = await commodities_analyst.analyze(state)

        state = await polymarket_scout.analyze(state)
        state = await nova.analyze(state)
        return state

    result: AgentState = await trading_graph.ainvoke(initial)
    logger.info(
        "research_cycle_complete",
        symbol=symbol,
        signals=len(result.get("signals", [])),
        strength=result.get("reasoning", ""),
    )
    return result


class GraphAgent(BaseAgent):
    """Thin wrapper around run_trading_cycle for legacy compatibility."""

    def __init__(self) -> None:
        super().__init__("graph", "Research Graph", "Orchestrator")

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        return await run_trading_cycle(symbol, market)


# Keep SageAgent as an alias so any existing import of SageAgent still works
SageAgent = GraphAgent
