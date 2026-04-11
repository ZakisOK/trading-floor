"""
Copy Trade Scout â€” monitors public trader positions and generates copy signals.

Sources:
  1. Binance Futures leaderboard (public API) â€” top traders by 30-day ROI
  2. XRPL whale wallet movements (>500k XRP threshold)
  3. COT commercial positioning â€” "smart money" in commodity futures
  4. (Optional) Unusual options flow â€” unusualwhales.com free tier

Signal logic: copy signals are NOT auto-executed. They flow through the normal
research pipeline â€” Diana and Nova evaluate them alongside agent analysis.
Confidence scales with the number of confirming sources.

XRPL whale tracking rationale: large XRP wallet movements (Ripple escrow releases,
exchange inflows/outflows, institution accumulation) precede price moves by hours.
Monitoring the top 20 wallets provides genuine edge over retail.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, UTC
from typing import Any

import httpx

from src.agents.base import BaseAgent, AgentState
from src.data.feeds.commodities_feed import CommoditiesFeed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XRPL whale wallets to monitor
# Source: XRPL rich list + known Ripple operational wallets
# ---------------------------------------------------------------------------
XRPL_WHALE_WALLETS = [
    "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh",  # Genesis / blackhole wallet
    "r3kmLJN5D28dHuH8vZNUZpMC4JrmHcbfAs",  # Ripple operational wallet
    "rN7n3473SaZBCG4dFL75SFZv9Uf5BT7Lz",  # Known Ripple distribution wallet
    "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe",  # Ripple escrow 1
    "rBepXUV89vvKTHJsuXw2sxBapBCGFQVNep",  # Ripple escrow 2
    "rhub8VRN55s94qWKDv6jmDy1pUykJzF3wq",  # Bitstamp hot wallet
    "rEb8TK3gBgk5auZkwc6sHnwrGVJH8DuaLh",  # Binance hot wallet
    "rKiCet8SdvWxPXnAgYarFUXMh1zCPz432Y",  # Kraken XRP wallet
]

WHALE_THRESHOLD_XRP = 500_000   # 500k XRP = ~$300k at $0.60 â€” meaningful flow
XRPL_RPC_URL = "https://xrplcluster.com"  # Public XRPL full history cluster

# ---------------------------------------------------------------------------
# Binance leaderboard config
# ---------------------------------------------------------------------------
BINANCE_LEADERBOARD_URL = (
    "https://www.binance.com/bapi/futures/v3/public/future/leaderboard/getOtherLeaderboardBaseInfo"
)
BINANCE_TOP_N = 10  # how many top traders to sample


class CopyTradeScoutAgent(BaseAgent):
    """
    Multi-source copy trade intelligence agent.

    Monitors Binance top traders, XRPL whale wallets, and COT smart money
    to generate copy trade signals. All signals are advisory â€” they pass through
    Nova for final conviction scoring before any action is taken.
    """

    def __init__(self) -> None:
        super().__init__("copy_trade_scout", "Copy Trade Scout", "Signal Intelligence")
        self._http = httpx.AsyncClient(
            timeout=20.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TradingFloor/1.0)",
                "Accept": "application/json",
            },
        )
        self._cof_feed = CommoditiesFeed()
        self._enabled_binance = os.getenv("BINANCE_LEADERBOARD_ENABLED", "true").lower() == "true"
        self._enabled_xrpl = os.getenv("XRPL_WHALE_TRACKING", "true").lower() == "true"
        self._min_confidence = float(os.getenv("COPY_TRADE_MIN_CONFIDENCE", "0.65"))

    # ------------------------------------------------------------------
    # Binance Futures leaderboard
    # ------------------------------------------------------------------

    async def get_binance_top_traders(self, symbol: str = "XRPUSDT") -> list[dict]:
        """
        Fetch Binance Futures leaderboard â€” top traders by 30-day ROI.

        The leaderboard is public and shows position direction (LONG/SHORT) for
        traders who have enabled position sharing. We sample the top N traders
        and tally their current positioning as a crowd signal.

        Returns a list of trader position dicts.
        """
        if not self._enabled_binance:
            return []

        try:
            # Step 1: Get leaderboard UIDs
            resp = await self._http.post(
                BINANCE_LEADERBOARD_URL,
                json={
                    "tradeType": "PERPETUAL",
                    "statisticsType": "ROI",
                    "periodType": "MONTHLY",
                    "isShared": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            traders = data.get("data", [])[:BINANCE_TOP_N]

            positions = []
            for trader in traders:
                enc_uid = trader.get("encryptedUid")
                if not enc_uid:
                    continue
                try:
                    pos_resp = await self._http.post(
                        "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPosition",
                        json={"encryptedUid": enc_uid, "tradeType": "PERPETUAL"},
                    )
                    pos_resp.raise_for_status()
                    pos_data = pos_resp.json().get("data", {})
                    trader_positions = pos_data.get("otherPositionRetList", [])

                    for pos in trader_positions:
                        sym = pos.get("symbol", "")
                        if symbol.upper().replace("/", "") in sym.upper():
                            positions.append({
                                "trader_uid": enc_uid[:8] + "...",  # truncate for privacy
                                "roi_30d": trader.get("roi", 0),
                                "pnl_30d": trader.get("pnl", 0),
                                "symbol": sym,
                                "amount": pos.get("amount", 0),
                                "entry_price": pos.get("entryPrice", 0),
                                "direction": "LONG" if pos.get("amount", 0) > 0 else "SHORT",
                                "leverage": pos.get("leverage", 1),
                                "unrealized_pnl": pos.get("unrealizedProfit", 0),
                            })
                except Exception as inner_exc:
                    logger.debug("binance_trader_fetch err=%s", inner_exc)
                    continue

            logger.info("binance_leaderboard symbol=%s traders_sampled=%d positions_found=%d",
                        symbol, len(traders), len(positions))
            return positions

        except httpx.HTTPError as exc:
            logger.warning("binance_leaderboard_error err=%s", exc)
            return []
        except Exception as exc:
            logger.warning("binance_leaderboard_parse err=%s", exc)
            return []

    # ------------------------------------------------------------------
    # XRPL whale wallet monitoring
    # ------------------------------------------------------------------

    async def get_xrpl_whale_moves(self) -> list[dict]:
        """
        Watch XRPL whale wallets for large XRP movements.

        Uses the XRPL public RPC (account_tx) to pull recent transactions
        for each tracked wallet. Filters for transactions > WHALE_THRESHOLD_XRP.

        Exchange inflow (whale sends XRP to exchange wallet) = likely selling pressure.
        Exchange outflow (exchange sends to whale wallet) = likely accumulation.

        Returns a list of whale move signals with direction interpretation.
        """
        if not self._enabled_xrpl:
            return []

        whale_moves = []
        exchange_wallets = {
            "rhub8VRN55s94qWKDv6jmDy1pUykJzF3wq": "Bitstamp",
            "rEb8TK3gBgk5auZkwc6sHnwrGVJH8DuaLh": "Binance",
            "rKiCet8SdvWxPXnAgYarFUXMh1zCPz432Y": "Kraken",
        }

        for wallet in XRPL_WHALE_WALLETS[:6]:  # Limit to 6 to avoid rate limits
            try:
                payload = {
                    "method": "account_tx",
                    "params": [{
                        "account": wallet,
                        "limit": 20,
                        "ledger_index_min": -1,
                        "ledger_index_max": -1,
                        "forward": False,
                    }],
                }
                resp = await self._http.post(XRPL_RPC_URL, json=payload)
                resp.raise_for_status()
                result = resp.json().get("result", {})

                transactions = result.get("transactions", [])
                for tx_wrapper in transactions:
                    tx = tx_wrapper.get("tx", {})

                    # Only look at Payment transactions in XRP (not tokens)
                    if tx.get("TransactionType") != "Payment":
                        continue
                    amount = tx.get("Amount")
                    if isinstance(amount, dict):
                        continue  # IOU token, skip
                    if not amount:
                        continue

                    # Amount is in drops (1 XRP = 1,000,000 drops)
                    xrp_amount = int(amount) / 1_000_000
                    if xrp_amount < WHALE_THRESHOLD_XRP:
                        continue

                    sender = tx.get("Account", "")
                    receiver = tx.get("Destination", "")
                    date_ts = tx.get("date", 0)

                    # Interpret flow direction
                    to_exchange = receiver in exchange_wallets
                    from_exchange = sender in exchange_wallets
                    exchange_name = exchange_wallets.get(receiver) or exchange_wallets.get(sender, "unknown")

                    if to_exchange:
                        direction = "BEARISH"  # Whale sending to exchange = likely sell
                        interpretation = f"{xrp_amount:,.0f} XRP flowing TO {exchange_name} â€” potential sell pressure"
                    elif from_exchange:
                        direction = "BULLISH"  # Withdrawal from exchange = accumulation
                        interpretation = f"{xrp_amount:,.0f} XRP withdrawn FROM {exchange_name} â€” accumulation signal"
                    else:
                        direction = "NEUTRAL"  # Wallet-to-wallet, unclear
                        interpretation = f"{xrp_amount:,.0f} XRP whale-to-whale transfer"

                    whale_moves.append({
                        "wallet": wallet[:12] + "...",
                        "amount_xrp": round(xrp_amount, 0),
                        "sender": sender[:12] + "...",
                        "receiver": receiver[:12] + "...",
                        "direction": direction,
                        "interpretation": interpretation,
                        "to_exchange": to_exchange,
                        "from_exchange": from_exchange,
                        "exchange": exchange_name,
                        "ledger_date": date_ts,
                    })

            except Exception as exc:
                logger.debug("xrpl_whale_fetch wallet=%s err=%s", wallet[:12], exc)
                continue

        logger.info("xrpl_whale_scan wallets_checked=%d large_moves_found=%d",
                    len(XRPL_WHALE_WALLETS[:6]), len(whale_moves))
        return whale_moves

    # ------------------------------------------------------------------
    # COT smart money positioning
    # ------------------------------------------------------------------

    async def get_cot_smart_money(self, commodity: str) -> dict:
        """
        Commercial hedgers in COT data are the "smart money" in commodities.

        Standard interpretation: commercials are almost always net SHORT because
        they hedge their physical long inventory. The signal fires when:
          - Commercials are net LONG (extremely rare) â†’ strong contrarian BULLISH
          - Commercials are at their most net-short in 12 months â†’ oversupply peak
          - Commercials rapidly covering shorts â†’ bullish momentum incoming

        Returns: {"net_position": int, "signal": str, "strength": float, "reasoning": str}
        """
        try:
            cot = await self._cof_feed.get_cot_data(commodity)
            if not cot.get("cot_available"):
                return {
                    "net_position": 0,
                    "signal": "NEUTRAL",
                    "strength": 0.0,
                    "reasoning": f"COT data unavailable: {cot.get('reason')}",
                }
            return {
                "net_position": cot.get("commercial_net", 0),
                "net_pct_oi": cot.get("commercial_net_pct", 0.0),
                "signal": cot.get("signal", "NEUTRAL"),
                "strength": cot.get("strength", 0.0),
                "reasoning": cot.get("reasoning", ""),
                "spec_net_pct": cot.get("speculator_net_pct", 0.0),
                "open_interest": cot.get("open_interest", 0),
            }
        except Exception as exc:
            logger.warning("cot_smart_money_error commodity=%s err=%s", commodity, exc)
            return {"net_position": 0, "signal": "NEUTRAL", "strength": 0.0, "reasoning": str(exc)}

    # ------------------------------------------------------------------
    # Signal aggregation
    # ------------------------------------------------------------------

    def _aggregate_signals(
        self,
        binance_positions: list[dict],
        whale_moves: list[dict],
        cot_data: dict | None,
        symbol: str,
    ) -> dict[str, Any]:
        """
        Combine signals from all sources into a single direction/confidence.

        Weighting:
          - Binance top trader consensus: 35% weight
          - XRPL whale flow: 35% weight
          - COT smart money: 30% weight

        Confidence scales with number of confirming sources.
        """
        scores: dict[str, float] = {"BULLISH": 0.0, "BEARISH": 0.0, "NEUTRAL": 0.0}
        source_details = []

        # --- Binance leaderboard consensus ---
        if binance_positions:
            long_count = sum(1 for p in binance_positions if p.get("direction") == "LONG")
            short_count = sum(1 for p in binance_positions if p.get("direction") == "SHORT")
            total = long_count + short_count
            if total > 0:
                long_pct = long_count / total
                short_pct = short_count / total
                if long_pct > 0.6:
                    scores["BULLISH"] += 0.35 * long_pct
                    source_details.append(f"Binance top traders {long_pct:.0%} LONG ({long_count}/{total})")
                elif short_pct > 0.6:
                    scores["BEARISH"] += 0.35 * short_pct
                    source_details.append(f"Binance top traders {short_pct:.0%} SHORT ({short_count}/{total})")
                else:
                    scores["NEUTRAL"] += 0.35
                    source_details.append(f"Binance top traders mixed ({long_count}L/{short_count}S)")

        # --- XRPL whale flow ---
        if whale_moves:
            bull_moves = [m for m in whale_moves if m.get("direction") == "BULLISH"]
            bear_moves = [m for m in whale_moves if m.get("direction") == "BEARISH"]
            bull_volume = sum(m.get("amount_xrp", 0) for m in bull_moves)
            bear_volume = sum(m.get("amount_xrp", 0) for m in bear_moves)
            total_volume = bull_volume + bear_volume or 1

            if bull_volume > bear_volume * 1.5:
                strength = min(0.35, 0.35 * bull_volume / total_volume)
                scores["BULLISH"] += strength
                source_details.append(f"XRPL whales: {bull_volume:,.0f} XRP accumulated vs {bear_volume:,.0f} outflow")
            elif bear_volume > bull_volume * 1.5:
                strength = min(0.35, 0.35 * bear_volume / total_volume)
                scores["BEARISH"] += strength
                source_details.append(f"XRPL whales: {bear_volume:,.0f} XRP flowing to exchanges")
            else:
                scores["NEUTRAL"] += 0.35 * 0.5
                source_details.append(f"XRPL whale flow mixed: bull {bull_volume:,.0f} / bear {bear_volume:,.0f} XRP")

        # --- COT smart money ---
        if cot_data and cot_data.get("signal") != "NEUTRAL":
            cot_signal = cot_data.get("signal", "NEUTRAL")
            cot_strength = float(cot_data.get("strength", 0.0))
            scores[cot_signal] = scores.get(cot_signal, 0.0) + 0.30 * cot_strength
            source_details.append(f"COT smart money: {cot_signal} (strength={cot_strength:.2f})")
        elif cot_data:
            scores["NEUTRAL"] += 0.30 * 0.5

        # Pick direction
        direction = max(scores, key=scores.get)  # type: ignore[arg-type]
        raw_confidence = scores.get(direction, 0.0)

        # Boost confidence when multiple sources agree
        confirming_sources = sum(
            1 for d, s in scores.items()
            if d == direction and s > 0.1
        )
        if confirming_sources >= 2:
            raw_confidence = min(0.95, raw_confidence * 1.25)

        return {
            "direction": direction,
            "confidence": round(raw_confidence, 3),
            "source_count": len(source_details),
            "sources": source_details,
            "score_breakdown": {k: round(v, 3) for k, v in scores.items()},
        }

    # ------------------------------------------------------------------
    # Main analyze loop
    # ------------------------------------------------------------------

    async def analyze(self, state: AgentState) -> AgentState:
        """
        Run copy trade intelligence scan for the current symbol.

        For XRP: runs Binance leaderboard + XRPL whale tracking.
        For commodities: runs COT smart money signal.
        Always emits a signal if confidence > COPY_TRADE_MIN_CONFIDENCE.
        """
        import asyncio
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "")

        is_xrp = "XRP" in symbol.upper()
        is_commodity = symbol.endswith("=F")

        if not (is_xrp or is_commodity):
            # For other assets, run a lightweight Binance leaderboard check
            pass

        try:
            # Gather data based on asset type
            tasks = []
            if is_xrp:
                tasks.append(self.get_binance_top_traders("XRPUSDT"))
                tasks.append(self.get_xrpl_whale_moves())
                cot_task = None
            elif is_commodity:
                async def _empty_list() -> list:
                    return []
                tasks.append(_empty_list())  # no binance for commodities
                tasks.append(_empty_list())  # no whale tracking for commodities
                cot_task = self.get_cot_smart_money(symbol)
            else:
                tasks.append(self.get_binance_top_traders(
                    symbol.replace("/", "").replace("-", "")
                ))
                tasks.append(_empty_list())
                cot_task = None

            results = await asyncio.gather(*tasks, return_exceptions=True)
            binance_positions = results[0] if not isinstance(results[0], Exception) else []
            whale_moves = results[1] if not isinstance(results[1], Exception) else []
            cot_data = None
            if cot_task:
                try:
                    cot_data = await cot_task
                except Exception:
                    cot_data = None

            # Aggregate into a single signal
            aggregated = self._aggregate_signals(binance_positions, whale_moves, cot_data, symbol)

            direction = aggregated["direction"]
            confidence = aggregated["confidence"]
            sources = aggregated.get("sources", [])
            thesis = f"Copy trade consensus: {direction} | Sources: {'; '.join(sources[:3])}"

            # Only emit if confidence clears threshold
            if confidence >= self._min_confidence:
                await self.emit_signal(
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    thesis=thesis,
                    strategy="copy_trade_scout",
                    entry=float(market.get("close", 0)) or None,
                )

            updated = dict(state)
            copy_signal = {
                "agent": self.name,
                "direction": direction,
                "confidence": confidence,
                "thesis": thesis,
                "signal_type": "copy_trade",
                "binance_positions": len(binance_positions),
                "whale_moves": len(whale_moves),
                "cot_signal": (cot_data or {}).get("signal", "N/A"),
                "sources": sources,
                "score_breakdown": aggregated.get("score_breakdown", {}),
                "min_confidence_met": confidence >= self._min_confidence,
            }
            updated["signals"] = state.get("signals", []) + [copy_signal]

            logger.info(
                "copy_trade_scout_done",
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                binance_count=len(binance_positions),
                whale_count=len(whale_moves),
            )
            return AgentState(**updated)

        except Exception as exc:
            logger.error("copy_trade_scout_error symbol=%s err=%s", symbol, exc)
            return state

    async def close(self) -> None:
        await self._http.aclose()
        await self._cof_feed.close()
