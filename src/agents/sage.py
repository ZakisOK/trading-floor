"""Sage — Portfolio Manager / LangGraph supervisor.

Builds and runs the multi-agent trading graph.

Week 1: cycle_id / cycle_started_at / subsystem / regime_fingerprint are
stamped onto the initial state here, at graph entry. Every downstream agent
reads them from the state dict.
"""
from __future__ import annotations

import structlog

from src.agents.base import AgentState, BaseAgent
from src.core.cycle import (
    compute_regime_fingerprint_stub,
    new_cycle_id,
    utcnow,
)

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
from src.agents.portfolio_constructor import portfolio_constructor

marcus = MarcusAgent()
vera = VeraAgent()
rex = RexAgent()
diana = DianaAgent()
atlas = AtlasAgent()
xrp_analyst = XRPAnalystAgent()
polymarket_scout = PolymarketScoutAgent()
# Week 2 / A1 — portfolio_constructor sits between Diana and Atlas.
constructor = portfolio_constructor


def _route_after_rex(state: AgentState) -> str:
    """Route to xrp_analyst for XRP symbols, otherwise skip straight to polymarket_scout."""
    market = state.get("market_data") or {}
    symbol = market.get("symbol", "")
    if "XRP" in symbol:
        return "xrp_analyst"
    return "polymarket_scout"


def _route_after_diana(state: AgentState) -> str:
    return "constructor" if state.get("risk_approved") else _END


def _route_after_constructor(state: AgentState) -> str:
    """Constructor's veto is final. Atlas only runs if a sized_order survived."""
    sized = state.get("sized_order")
    if state.get("risk_approved") and sized and sized.get("quantity", 0) > 0:
        return "atlas"
    return _END


def build_trading_graph():  # type: ignore[return]
    """Build and compile the LangGraph trading workflow.

    Route (Week 2): marcus → vera → rex → [xrp_analyst if XRP]
                    → polymarket_scout → diana → constructor → atlas
    """
    if not _LANGGRAPH_AVAILABLE:
        return None
    graph = StateGraph(AgentState)
    graph.add_node("marcus", marcus.analyze_with_heartbeat)
    graph.add_node("vera", vera.analyze_with_heartbeat)
    graph.add_node("rex", rex.analyze_with_heartbeat)
    graph.add_node("xrp_analyst", xrp_analyst.analyze_with_heartbeat)
    graph.add_node("polymarket_scout", polymarket_scout.analyze_with_heartbeat)
    graph.add_node("diana", diana.analyze_with_heartbeat)
    graph.add_node("constructor", constructor.analyze_with_heartbeat)
    graph.add_node("atlas", atlas.analyze_with_heartbeat)

    graph.set_entry_point("marcus")
    graph.add_edge("marcus", "vera")
    graph.add_edge("vera", "rex")
    graph.add_conditional_edges(
        "rex",
        _route_after_rex,
        {"xrp_analyst": "xrp_analyst", "polymarket_scout": "polymarket_scout"},
    )
    graph.add_edge("xrp_analyst", "polymarket_scout")
    graph.add_edge("polymarket_scout", "diana")
    graph.add_conditional_edges(
        "diana", _route_after_diana,
        {"constructor": "constructor", _END: _END},
    )
    graph.add_conditional_edges(
        "constructor", _route_after_constructor,
        {"atlas": "atlas", _END: _END},
    )
    graph.add_edge("atlas", _END)
    return graph.compile()


trading_graph = build_trading_graph()


def _build_initial_state(symbol: str, market_data: dict) -> AgentState:
    """Stamp cycle identity + regime onto the state at graph entry.

    PRINCIPLE #6: cycle_id is mandatory. If we ever produce a state without
    one, that's a bug. This helper is the single place cycle_id is created
    for a live trading cycle.
    """
    cycle_id = new_cycle_id()
    cycle_started_at = utcnow()
    merged_market = {"symbol": symbol, **market_data}
    return {
        "cycle_id": cycle_id,
        "cycle_started_at": cycle_started_at,
        "subsystem": "legacy",
        "regime_fingerprint": compute_regime_fingerprint_stub(merged_market),
        "agent_id": "sage",
        "agent_name": "Sage",
        "messages": [],
        "market_data": merged_market,
        "signals": [],
        "risk_approved": False,
        "final_decision": None,
        "confidence": 0.0,
        "reasoning": "",
    }


async def run_trading_cycle(symbol: str, market_data: dict) -> AgentState:
    """Run a full analysis cycle for a symbol through all agents."""
    initial = _build_initial_state(symbol, market_data)
    cycle_id = initial["cycle_id"]
    logger.info(
        "trading_cycle_started",
        symbol=symbol,
        cycle_id=cycle_id,
        subsystem=initial["subsystem"],
        regime_fingerprint=initial["regime_fingerprint"],
    )

    if trading_graph is None:
        # Fallback: run agents sequentially without LangGraph. Still carries
        # the same cycle_id — that's the whole point of B1. Also threads the
        # constructor between Diana and Atlas (Week 2 / A1).
        state = initial
        market = state.get("market_data") or {}
        sym = market.get("symbol", "")
        base_agents = [marcus, vera, rex]
        xrp_agents = [xrp_analyst] if "XRP" in sym else []
        tail_agents = [polymarket_scout, diana, constructor, atlas]
        for agent in base_agents + xrp_agents + tail_agents:
            state = await agent.analyze_with_heartbeat(state)
        logger.info(
            "trading_cycle_complete",
            symbol=symbol,
            cycle_id=cycle_id,
            signals=len(state.get("signals", [])),
            approved=state.get("risk_approved"),
        )
        return state

    result: AgentState = await trading_graph.ainvoke(initial)
    logger.info(
        "trading_cycle_complete",
        symbol=symbol,
        cycle_id=cycle_id,
        signals=len(result.get("signals", [])),
        approved=result.get("risk_approved"),
    )
    return result


class SageAgent(BaseAgent):
    """Supervisor agent — wraps run_trading_cycle for legacy compatibility."""

    def __init__(self) -> None:
        super().__init__(
            "sage",
            "Sage",
            "Supervisor",
            model_name="langgraph-supervisor",
            prompt_template="sage:supervisor:v1",
        )

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        return await run_trading_cycle(symbol, market)
