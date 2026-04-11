"""
graph.py — LangGraph multi-agent trading pipeline (v2: full parallel signal generation).

Pipeline:
  detect_regime
    ↓
  run_parallel_signals  (10 agents via asyncio.gather)
    marcus · sentiment_analyst · momentum_agent · cot_analyst
    eia_analyst · carry_agent · macro_analyst · options_flow_agent
    copy_trade_scout · [xrp_analyst if XRP]
    ↓
  orthogonalize_signals (PCA decorrelation — prevents correlation collapse)
    ↓
  vera → rex → polymarket_scout → nova → END

Nova publishes conviction packet to stream:trade_desk:inbox.
Atlas is called by TradeDeskAgent (Desk 2), not here.
"""
from __future__ import annotations

import asyncio

import structlog

from src.agents.base import AgentState, BaseAgent

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# LangGraph — lazy import so app boots without it installed
# ---------------------------------------------------------------------------
try:
    from langgraph.graph import StateGraph, END as _END  # type: ignore[import]
    _LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _LANGGRAPH_AVAILABLE = False
    _END = "__end__"

# ---------------------------------------------------------------------------
# Core pipeline agents (existing)
# ---------------------------------------------------------------------------
from src.agents.marcus import MarcusAgent
from src.agents.vera import VeraAgent
from src.agents.rex import RexAgent
from src.agents.nova import NovaAgent
from src.agents.atlas import AtlasAgent
from src.agents.xrp_analyst import XRPAnalystAgent
from src.agents.polymarket_scout import PolymarketScoutAgent
from src.agents.commodities_analyst import CommoditiesAnalystAgent
from src.agents.copy_trade_scout import CopyTradeScoutAgent

# ---------------------------------------------------------------------------
# New parallel signal agents (Phase 1-2)
# ---------------------------------------------------------------------------
from src.agents.sentiment_analyst import SentimentAnalystAgent
from src.agents.cot_analyst import COTAnalystAgent
from src.agents.eia_analyst import EIAAnalystAgent
from src.agents.carry_agent import CarryAgent
from src.agents.macro_analyst import MacroAnalystAgent
from src.agents.options_flow_agent import OptionsFlowAgent

try:
    from src.agents.momentum_agent import MomentumAgent
    _MOMENTUM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MOMENTUM_AVAILABLE = False

# ---------------------------------------------------------------------------
# Pre/post-signal infrastructure
# ---------------------------------------------------------------------------
from src.signals.regime_detector import RegimeDetector
from src.signals.orthogonalization import SignalOrthogonalizer

# ---------------------------------------------------------------------------
# Instantiate all agents (singletons for the lifetime of the process)
# ---------------------------------------------------------------------------
marcus            = MarcusAgent()
vera              = VeraAgent()
rex               = RexAgent()
nova              = NovaAgent()
atlas             = AtlasAgent()
xrp_analyst       = XRPAnalystAgent()
polymarket_scout  = PolymarketScoutAgent()
commodities_analyst = CommoditiesAnalystAgent()
copy_trade_scout  = CopyTradeScoutAgent()

sentiment_analyst = SentimentAnalystAgent()
cot_analyst       = COTAnalystAgent()
eia_analyst       = EIAAnalystAgent()
carry_agent       = CarryAgent()
macro_analyst     = MacroAnalystAgent()
options_flow_agent = OptionsFlowAgent()
momentum_agent    = MomentumAgent() if _MOMENTUM_AVAILABLE else None

# Infrastructure singletons
regime_detector      = RegimeDetector()
signal_orthogonalizer = SignalOrthogonalizer()


# ---------------------------------------------------------------------------
# Node 1: Regime detection — runs BEFORE all signal agents
# ---------------------------------------------------------------------------

async def _detect_regime(state: AgentState) -> AgentState:
    """
    Detect market regime (TRENDING / RANGING / VOLATILE) from ATR ratio.
    Writes result to Redis key market:regime:{symbol} (TTL 10 min).
    Injects regime label into state["market_regime"] for all downstream agents.
    """
    market  = state.get("market_data") or {}
    symbol  = market.get("symbol", "UNKNOWN")
    prices  = market.get("prices", [market.get("close", 100.0)])
    if not isinstance(prices, list):
        prices = [prices]

    try:
        regime = await regime_detector.detect_and_publish(symbol, prices)
    except Exception as exc:
        logger.warning("regime_detection_failed", symbol=symbol, err=str(exc))
        regime = "RANGING"

    logger.info("regime_detected", symbol=symbol, regime=regime)
    return AgentState(**{**dict(state), "market_regime": regime})


# ---------------------------------------------------------------------------
# Node 2: Parallel signal generation — all 10 agents concurrently
# ---------------------------------------------------------------------------

async def _noop(s: AgentState) -> AgentState:
    """Pass-through coroutine for conditionally disabled agents."""
    return s


async def _run_parallel_signals(state: AgentState) -> AgentState:
    """
    Run all signal-generating agents via asyncio.gather.

    Gating rules (agents self-gate internally; this adds outer guards):
      - xrp_analyst   → only when "XRP" in symbol
      - momentum_agent → only when MomentumAgent could be imported
      - cot_analyst    → self-gates on non-commodity symbols
      - eia_analyst    → self-gates on non-report days / times
      - options_flow   → self-gates on unsupported symbols
      - macro_analyst  → reads Redis cache, never re-hits FRED per cycle
    """
    market = state.get("market_data") or {}
    symbol = market.get("symbol", "")

    xrp_coro      = xrp_analyst.analyze(state) if "XRP" in symbol else _noop(state)
    momentum_coro = momentum_agent.analyze(state) if momentum_agent is not None else _noop(state)

    coroutines = [
        marcus.analyze(state),
        sentiment_analyst.analyze(state),
        momentum_coro,
        cot_analyst.analyze(state),
        eia_analyst.analyze(state),
        carry_agent.analyze(state),
        macro_analyst.analyze(state),
        options_flow_agent.analyze(state),
        copy_trade_scout.analyze(state),
        xrp_coro,
    ]

    results = await asyncio.gather(*coroutines, return_exceptions=True)

    merged_signals: list = list(state.get("signals", []))
    merged_market  = dict(market)

    for r in results:
        if isinstance(r, Exception):
            logger.warning("parallel_agent_error", err=str(r))
            continue
        if not isinstance(r, dict):
            continue
        merged_signals.extend(r.get("signals", []))
        if r.get("market_data"):
            merged_market.update(r["market_data"])

    logger.info(
        "parallel_signals_collected",
        symbol=symbol,
        raw_signal_count=len(merged_signals),
        regime=state.get("market_regime"),
    )
    return AgentState(**{**dict(state), "signals": merged_signals, "market_data": merged_market})


# ---------------------------------------------------------------------------
# Node 3: Signal orthogonalization — PCA decorrelation before vera
# ---------------------------------------------------------------------------

async def _orthogonalize_signals(state: AgentState) -> AgentState:
    """
    Apply PCA decorrelation so vera sees truly independent signals.
    Falls back to raw signals when PCA history < 30 days.
    Effective signal count (from eigenvalue decomposition) is injected
    into state["effective_signal_count"] for dashboard display.
    """
    try:
        return await signal_orthogonalizer.transform_state(state)
    except Exception as exc:
        logger.warning("orthogonalization_failed", err=str(exc))
        return state


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_trading_graph():  # type: ignore[return]
    """
    Build and compile the LangGraph v2 research workflow.

    detect_regime → run_parallel_signals → orthogonalize_signals
      → vera → rex → polymarket_scout → nova → END
    """
    if not _LANGGRAPH_AVAILABLE:
        return None

    graph = StateGraph(AgentState)

    graph.add_node("detect_regime",        _detect_regime)
    graph.add_node("run_parallel_signals", _run_parallel_signals)
    graph.add_node("orthogonalize_signals", _orthogonalize_signals)
    graph.add_node("vera",              vera.analyze)
    graph.add_node("rex",               rex.analyze)
    graph.add_node("polymarket_scout",  polymarket_scout.analyze)
    graph.add_node("nova",              nova.analyze)

    graph.set_entry_point("detect_regime")
    graph.add_edge("detect_regime",         "run_parallel_signals")
    graph.add_edge("run_parallel_signals",  "orthogonalize_signals")
    graph.add_edge("orthogonalize_signals", "vera")
    graph.add_edge("vera",                  "rex")
    graph.add_edge("rex",                   "polymarket_scout")
    graph.add_edge("polymarket_scout",      "nova")
    graph.add_edge("nova",                  _END)

    return graph.compile()


trading_graph = build_trading_graph()


async def run_trading_cycle(symbol: str, market_data: dict) -> AgentState:
    """Run a full research cycle for a symbol through all Desk 1 agents."""
    initial: AgentState = {
        "agent_id":    "graph",
        "agent_name":  "Research Graph",
        "messages":    [],
        "market_data": {"symbol": symbol, **market_data},
        "market_regime": "UNKNOWN",
        "signals":     [],
        "risk_approved":  False,
        "final_decision": None,
        "confidence":  0.0,
        "reasoning":   "",
    }

    if trading_graph is None:
        # Sequential fallback when LangGraph not installed
        state: AgentState = initial
        state = await _detect_regime(state)
        state = await _run_parallel_signals(state)
        state = await _orthogonalize_signals(state)
        state = await vera.analyze(state)
        state = await rex.analyze(state)
        state = await polymarket_scout.analyze(state)
        state = await nova.analyze(state)
        return state

    result: AgentState = await trading_graph.ainvoke(initial)
    logger.info(
        "research_cycle_complete",
        symbol=symbol,
        regime=result.get("market_regime"),
        raw_signals=len(result.get("signals", [])),
        effective_signals=result.get("effective_signal_count"),
        approved=result.get("risk_approved"),
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
