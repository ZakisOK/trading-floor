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

marcus = MarcusAgent()
vera = VeraAgent()
rex = RexAgent()
diana = DianaAgent()
atlas = AtlasAgent()


def _route_after_analysis(state: AgentState) -> str:
    return "diana"


def _route_after_risk(state: AgentState) -> str:
    return "atlas" if state.get("risk_approved") else _END


def build_trading_graph():  # type: ignore[return]
    """Build and compile the LangGraph trading workflow."""
    if not _LANGGRAPH_AVAILABLE:
        return None
    graph = StateGraph(AgentState)
    graph.add_node("marcus", marcus.analyze)
    graph.add_node("vera", vera.analyze)
    graph.add_node("rex", rex.analyze)
    graph.add_node("diana", diana.analyze)
    graph.add_node("atlas", atlas.analyze)
    graph.set_entry_point("marcus")
    graph.add_edge("marcus", "vera")
    graph.add_edge("vera", "rex")
    graph.add_conditional_edges("rex", _route_after_analysis, {"diana": "diana"})
    graph.add_conditional_edges(
        "diana", _route_after_risk, {"atlas": "atlas", _END: _END}
    )
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
        for agent in [marcus, vera, rex, diana, atlas]:
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
