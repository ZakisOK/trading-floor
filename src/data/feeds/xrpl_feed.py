"""
XRPL network data feed — fetches on-chain metrics for XRP fundamental analysis.
Uses public XRPL APIs (no API key required).
"""
import asyncio
import httpx
import structlog
from datetime import datetime, UTC
from src.streams.producer import produce
from src.streams.topology import MARKET_DATA

logger = structlog.get_logger()

XRPL_API = "https://data.ripple.com/v2"
XRPL_RPC = "https://s1.ripple.com:51234"


class XRPLFeed:
    """Fetches XRPL network metrics useful for fundamental analysis."""

    async def get_network_stats(self) -> dict:
        """Ledger close time, TPS, active accounts, escrow data."""
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(XRPL_RPC, json={
                    "method": "server_info",
                    "params": [{}]
                })
                info = resp.json().get("result", {}).get("info", {})
                return {
                    "ledger_index": info.get("validated_ledger", {}).get("seq", 0),
                    "base_fee_xrp": info.get("validated_ledger", {}).get("base_fee_xrp", 0),
                    "reserve_base_xrp": info.get("validated_ledger", {}).get("reserve_base_xrp", 0),
                    "tps": info.get("load_factor", 1),
                    "ts": datetime.now(UTC).isoformat(),
                }
            except Exception as e:
                logger.error("xrpl_network_stats_error", error=str(e))
                return {}

    async def get_xrp_metrics(self) -> dict:
        """
        Key XRP fundamental signals:
        - Escrow releases (Ripple's monthly unlock schedule)
        - DEX volume on XRPL
        - Active wallet count
        - Payment volume
        """
        async with httpx.AsyncClient(timeout=15) as client:
            metrics = {}
            try:
                # 24h payment volume
                resp = await client.get(f"{XRPL_API}/network/payment_volume?interval=day&limit=1")
                data = resp.json()
                if data.get("rows"):
                    metrics["payment_volume_xrp_24h"] = data["rows"][0].get("total", 0)
            except Exception:
                pass

            try:
                # Active accounts
                resp = await client.get(f"{XRPL_API}/network/active_accounts?interval=day&limit=1")
                data = resp.json()
                if data.get("rows"):
                    metrics["active_accounts_24h"] = data["rows"][0].get("count", 0)
            except Exception:
                pass

            metrics["ts"] = datetime.now(UTC).isoformat()
            return metrics

    async def get_odl_signals(self) -> dict:
        """
        On-Demand Liquidity (ODL) corridor activity.
        High ODL volume = bullish fundamental for XRP.
        Monitors USD/XRP, MXN/XRP, PHP/XRP corridors.
        """
        # ODL data via public XRPL DEX
        corridors = ["USD", "MXN", "PHP", "BRL"]
        signals = {"corridors": {}, "ts": datetime.now(UTC).isoformat()}
        async with httpx.AsyncClient(timeout=15) as client:
            for currency in corridors:
                try:
                    resp = await client.get(
                        f"{XRPL_API}/exchange_rates/XRP/{currency}?date=now"
                    )
                    data = resp.json()
                    if "rate" in data:
                        signals["corridors"][currency] = data["rate"]
                except Exception:
                    pass
        return signals
