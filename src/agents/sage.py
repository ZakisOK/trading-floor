"""Sage — Portfolio Manager / LangGraph supervisor.

Builds and runs the multi-agent trading graph.
# pip install langgraph  (if not already installed)
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
from src.agents.diana import DianaAgent
from src.agents.atlas import AtlasAgent
from src.agents.xrp_analyst import XRPAnalystAgent
from src.agents.polymarket_scout import PolymarketScoutAgent

marcus = MarcusAgent()
vera = VeraAgent()
rex = RexAgent()
diana = DianaAgent()
atlas = AtlasAgent()
xrp_analyst = XRPAnalystAgent()
polymarket_scout = PolymarketScoutAgent()


def _route_after_rex(state: AgentState) -> str:
    """Route to xrp_analyst for XRP symbols, otherwise skip straight to polymarket_scout."""
    market = state.get("market_data") or {}
    symbol = market.get("symbol", "")
    if "XRP" in symbol:
        return "xrp_analyst"
    return "polymarket_scout"


def _route_after_diana(state: AgentState) -> str:
    return "atlas" if state.get("risk_approved") else _END


def build_trading_graph():  # type: ignore[return]
    """Build and compile the LangGraph trading workflow.

    Route: marcus → vera → rex → [xrp_analyst if XRP] → polymarket_scout → diana → atlas
    """
    if not _LANGGRAPH_AVAILABLE:
        return None
    graph = StateGraph(AgentState)
    graph.add_node("marcus", marcus.analyze)
    graph.add_node("vera", vera.analyze)
    graph.add_node("rex", rex.analyze)
    graph.add_node("xrp_analyst", xrp_analyst.analyze)
    graph.add_node("polymarket_scout", polymarket_scout.analyze)
    graph.add_node("diana", diana.analyze)
    graph.add_node("atlas", atlas.analyze)

    graph.set_entry_point("marcus")
    graph.add_edge("marcus", "vera")
    graph.add_edge("vera", "rex")
    graph.add_conditional_edges(
        "rex",
        _route_after_rex,
        {"xrp_analyst": "xrp_analyst", "polymarket_scout": "polymarket_scout"},
    )
    graph.add_edge("xrp_analyst", "polymarket_scout")
    graph.add_conditional_edges(
        "diana", _route_after_diana, {"atlas": "atlas", _END: _END}
    )
    graph.add_edge("polymarket_scout", "diana")
    graph.add_edge("atlas", _END)
    return graph.compile()


trading_graph = build_trading_graph()


async def run_trading_cycle(symbol: str, market_data: dict) -> AgentState:
    """Run a full analysis cycle for a symbol through all agents."""
    initial: AgentState = {
        "agent_id": "sage",
        "agent_name": "Sage",
        "messages": [],
        "market_data": {"symbol": symbol, **market_data},
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
        tail_agents = [polymarket_scout, diana, atlas]
        for agent in base_agents + xrp_agents + tail_agents:
            state = await agent.analyze(state)
        return state

    result: AgentState = await trading_graph.ainvoke(initial)
    logger.info(
        "trading_cycle_complete",
        symbol=symbol,
        signals=len(result.get("signals", [])),
        approved=result.get("risk_approved"),
    )
    return result


class SageAgent(BaseAgent):
    """Supervisor agent — wraps run_trading_cycle for legacy compatibility."""

    def __init__(self) -> None:
        super().__init__("sage", "Sage", "Supervisor")

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        return await run_trading_cycle(symbol, market)
