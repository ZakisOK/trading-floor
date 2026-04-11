"""
graph.py — LangGraph multi-agent research pipeline builder.

This is a rename of the original sage.py (graph builder only).
The pipeline now ends with Nova (Synthesizer) instead of Diana.
Diana has moved to Desk 2 (Trade Desk) for final position sizing.

Route: marcus → vera → rex → [xrp_analyst if XRP] → polymarket_scout → nova
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
from src.agents.nova import NovaAgent          # Nova replaces Diana as final node
from src.agents.atlas import AtlasAgent
from src.agents.xrp_analyst import XRPAnalystAgent
from src.agents.polymarket_scout import PolymarketScoutAgent

marcus = MarcusAgent()
vera = VeraAgent()
rex = RexAgent()
nova = NovaAgent()                             # Synthesizer — new final node
atlas = AtlasAgent()
xrp_analyst = XRPAnalystAgent()
polymarket_scout = PolymarketScoutAgent()


def _route_after_rex(state: AgentState) -> str:
    """Route to xrp_analyst for XRP symbols, otherwise skip to polymarket_scout."""
    market = state.get("market_data") or {}
    symbol = market.get("symbol", "")
    if "XRP" in symbol:
        return "xrp_analyst"
    return "polymarket_scout"


def build_trading_graph():  # type: ignore[return]
    """Build and compile the LangGraph research workflow.

    Route: marcus → vera → rex → [xrp_analyst if XRP] → polymarket_scout → nova
    Nova publishes the conviction packet to stream:trade_desk:inbox.
    Atlas is now called by TradeDeskAgent (Desk 2), not here.
    """
    if not _LANGGRAPH_AVAILABLE:
        return None
    graph = StateGraph(AgentState)
    graph.add_node("marcus", marcus.analyze)
    graph.add_node("vera", vera.analyze)
    graph.add_node("rex", rex.analyze)
    graph.add_node("xrp_analyst", xrp_analyst.analyze)
    graph.add_node("polymarket_scout", polymarket_scout.analyze)
    graph.add_node("nova", nova.analyze)       # Nova is the new terminal research node

    graph.set_entry_point("marcus")
    graph.add_edge("marcus", "vera")
    graph.add_edge("vera", "rex")
    graph.add_conditional_edges(
        "rex",
        _route_after_rex,
        {"xrp_analyst": "xrp_analyst", "polymarket_scout": "polymarket_scout"},
    )
    graph.add_edge("xrp_analyst", "polymarket_scout")
    graph.add_edge("polymarket_scout", "nova")  # nova replaced diana here
    graph.add_edge("nova", _END)
    return graph.compile()


trading_graph = build_trading_graph()


async def run_trading_cycle(symbol: str, market_data: dict) -> AgentState:
    """Run a full research cycle for a symbol through all Desk 1 agents."""
    # Inject the current market regime from Portfolio Chief
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
        state = initial
        market = state.get("market_data") or {}
        sym = market.get("symbol", "")
        base_agents = [marcus, vera, rex]
        xrp_agents = [xrp_analyst] if "XRP" in sym else []
        tail_agents = [polymarket_scout, nova]
        for agent in base_agents + xrp_agents + tail_agents:
            state = await agent.analyze(state)
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
