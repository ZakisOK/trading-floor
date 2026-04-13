"""
graph.py — LangGraph multi-agent trading pipeline (v3: macro regime + data validator).

Pipeline:
  detect_regime
    |
  macro_regime_overlay  (Gap 3: Dalio — elevates macro above technical)
    |
  validate_market_data  (Gap 4: Simons — data quality firewall)
    |
  run_parallel_signals  (16 agents via asyncio.gather)
    |
  orthogonalize_signals (PCA + sequential residualization)
    |
  vera -> rex -> polymarket_scout -> nova -> END

Nova publishes conviction packet to stream:trade_desk:inbox.
Atlas is called by TradeDeskAgent (Desk 2), not here.
"""
from __future__ import annotations

import asyncio
import json

import structlog

from src.agents.base import AgentState, BaseAgent

logger = structlog.get_logger()

try:
    from langgraph.graph import StateGraph, END as _END  # type: ignore[import]
    _LANGGRAPH_AVAILABLE = True
except ImportError:
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
from src.agents.sentiment_analyst import SentimentAnalystAgent
from src.agents.cot_analyst import COTAnalystAgent
from src.agents.eia_analyst import EIAAnalystAgent
from src.agents.carry_agent import CarryAgent
from src.agents.macro_analyst import MacroAnalystAgent
from src.agents.options_flow_agent import OptionsFlowAgent

try:
    from src.agents.momentum_agent import MomentumAgent
    _MOMENTUM_AVAILABLE = True
except ImportError:
    _MOMENTUM_AVAILABLE = False

from src.signals.regime_detector import RegimeDetector
from src.signals.orthogonalization import SignalOrthogonalizer
from src.data.validator import validate_market_data

marcus             = MarcusAgent()
vera               = VeraAgent()
rex                = RexAgent()
nova               = NovaAgent()
atlas              = AtlasAgent()
xrp_analyst        = XRPAnalystAgent()
polymarket_scout   = PolymarketScoutAgent()
commodities_analyst = CommoditiesAnalystAgent()
copy_trade_scout   = CopyTradeScoutAgent()
sentiment_analyst  = SentimentAnalystAgent()
cot_analyst        = COTAnalystAgent()
eia_analyst        = EIAAnalystAgent()
carry_agent        = CarryAgent()
macro_analyst      = MacroAnalystAgent()
options_flow_agent = OptionsFlowAgent()
momentum_agent     = MomentumAgent() if _MOMENTUM_AVAILABLE else None

regime_detector       = RegimeDetector()
signal_orthogonalizer = SignalOrthogonalizer()


# ---------------------------------------------------------------------------
# Node 1: Technical regime detection (ATR ratio)
# ---------------------------------------------------------------------------

async def _detect_regime(state: AgentState) -> AgentState:
    """
    Detect market regime (TRENDING / RANGING / VOLATILE) from ATR ratio.
    Stores result as technical_regime; macro overlay in next node sets effective_regime.
    """
    market = state.get("market_data") or {}
    symbol = market.get("symbol", "UNKNOWN")
    prices = market.get("prices", [market.get("close", 100.0)])
    if not isinstance(prices, list):
        prices = [prices]

    try:
        regime = await regime_detector.detect_and_publish(symbol, prices)
    except Exception as exc:
        logger.warning("regime_detection_failed", symbol=symbol, err=str(exc))
        regime = "RANGING"

    logger.info("technical_regime_detected", symbol=symbol, regime=regime)
    return AgentState(**{**dict(state), "market_regime": regime, "technical_regime": regime})


# ---------------------------------------------------------------------------
# Node 2: Macro regime overlay (Gap 3 — Dalio recommendation)
# ---------------------------------------------------------------------------

async def _macro_regime_overlay(state: AgentState) -> AgentState:
    """
    Override technical regime using macro_analyst's RISK_ON / RISK_OFF score.

    Rules:
      RISK_OFF (score < -0.3) -> effective_regime = VOLATILE (regardless of ATR)
      RISK_ON  (score >  0.3) + technical RANGING -> effective_regime = TRENDING
      Otherwise               -> effective_regime = technical_regime

    Writes risk:regime_override to Redis when an override fires.
    """
    technical_regime = state.get("technical_regime", "RANGING")
    market = state.get("market_data") or {}
    symbol = market.get("symbol", "UNKNOWN")

    macro_regime_label = "NEUTRAL"
    effective_regime   = technical_regime
    override_reason    = None

    try:
        from src.core.redis import get_redis
        redis = get_redis()
        raw = await redis.get(f"signals:macro_analyst:latest")
        if raw:
            macro_data = json.loads(raw) if isinstance(raw, str) else raw
            score = float(macro_data.get("score", 0.0))

            if score < -0.3:
                macro_regime_label = "RISK_OFF"
                effective_regime   = "VOLATILE"
                override_reason    = f"macro RISK_OFF (score={score:.3f}) -> VOLATILE"
            elif score > 0.3:
                macro_regime_label = "RISK_ON"
                if technical_regime == "RANGING":
                    effective_regime = "TRENDING"
                    override_reason  = f"macro RISK_ON (score={score:.3f}) + RANGING -> TRENDING"

            if override_reason:
                logger.info(
                    "macro_regime_override",
                    symbol=symbol,
                    technical=technical_regime,
                    effective=effective_regime,
                    reason=override_reason,
                )
                from datetime import UTC, datetime
                await redis.set(
                    "risk:regime_override",
                    json.dumps({
                        "symbol": symbol,
                        "technical_regime": technical_regime,
                        "macro_regime": macro_regime_label,
                        "effective_regime": effective_regime,
                        "reason": override_reason,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }),
                    ex=600,
                )

    except Exception as exc:
        logger.warning("macro_regime_overlay_error", symbol=symbol, err=str(exc))

    updated = dict(state)
    updated["market_regime"]   = effective_regime   # downstream agents read market_regime
    updated["macro_regime"]    = macro_regime_label
    updated["effective_regime"] = effective_regime
    if updated.get("market_data"):
        updated["market_data"] = {**updated["market_data"], "regime": effective_regime}

    return AgentState(**updated)


# ---------------------------------------------------------------------------
# Node 3: Data quality validation (Gap 4 — Simons recommendation)
# ---------------------------------------------------------------------------

async def _validate_data(state: AgentState) -> AgentState:
    """
    Run every market data bar through the data quality firewall before signals run.
    Filters out stale, zero, incoherent, or split-affected bars.
    Suspicious-volume bars are tagged but not dropped.
    """
    market = state.get("market_data") or {}
    symbol = market.get("symbol", "UNKNOWN")

    # Build a single-symbol dict for the validator
    symbol_bars: dict = {symbol: market} if market else {}
    clean_bars   = await validate_market_data(symbol_bars)

    if not clean_bars:
        logger.warning(
            "data_validator_rejected_all",
            symbol=symbol,
            reason="bar failed quality checks — skipping cycle",
        )
        updated = dict(state)
        updated["skip_cycle"] = True
        updated["final_decision"] = None
        updated["risk_approved"] = False
        return AgentState(**updated)

    # Re-inject validated (possibly tagged) bar back into state
    validated_bar = clean_bars.get(symbol, market)
    updated = dict(state)
    updated["market_data"] = validated_bar
    updated["skip_cycle"]  = False
    return AgentState(**updated)


# ---------------------------------------------------------------------------
# Node 4: Parallel signal generation
# ---------------------------------------------------------------------------

async def _noop(s: AgentState) -> AgentState:
    return s


async def _run_parallel_signals(state: AgentState) -> AgentState:
    """Run all 16 signal agents concurrently. Skip if data was rejected."""
    if state.get("skip_cycle"):
        return state

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
# Node 5: Signal orthogonalization
# ---------------------------------------------------------------------------

async def _orthogonalize_signals(state: AgentState) -> AgentState:
    if state.get("skip_cycle"):
        return state
    try:
        return await signal_orthogonalizer.transform_state(state)
    except Exception as exc:
        logger.warning("orthogonalization_failed", err=str(exc))
        return state


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_trading_graph():
    if not _LANGGRAPH_AVAILABLE:
        return None

    graph = StateGraph(AgentState)

    graph.add_node("detect_regime",         _detect_regime)
    graph.add_node("macro_regime_overlay",  _macro_regime_overlay)
    graph.add_node("validate_data",         _validate_data)
    graph.add_node("run_parallel_signals",  _run_parallel_signals)
    graph.add_node("orthogonalize_signals", _orthogonalize_signals)
    graph.add_node("vera",                  vera.analyze)
    graph.add_node("rex",                   rex.analyze)
    graph.add_node("polymarket_scout",      polymarket_scout.analyze)
    graph.add_node("nova",                  nova.analyze)

    graph.set_entry_point("detect_regime")
    graph.add_edge("detect_regime",         "macro_regime_overlay")
    graph.add_edge("macro_regime_overlay",  "validate_data")
    graph.add_edge("validate_data",         "run_parallel_signals")
    graph.add_edge("run_parallel_signals",  "orthogonalize_signals")
    graph.add_edge("orthogonalize_signals", "vera")
    graph.add_edge("vera",                  "rex")
    graph.add_edge("rex",                   "polymarket_scout")
    graph.add_edge("polymarket_scout",      "nova")
    graph.add_edge("nova",                  _END)

    return graph.compile()


trading_graph = build_trading_graph()
