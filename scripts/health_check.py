"""
Health check — run this before starting the system.

Verifies: Redis connection, DB connection, all modules importable,
required env vars set, exchange connectivity, XRPL RPC, Polymarket API,
and yfinance data.

Usage:
    python scripts/health_check.py

Exit code 0 = all critical checks passed.
Exit code 1 = one or more critical checks failed.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── colour helpers ──────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

PASS = f"{GREEN}PASS{RESET}"
FAIL = f"{RED}FAIL{RESET}"
WARN = f"{YELLOW}WARN{RESET}"

_failures: list[str] = []


def ok(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{PASS}] {label}{suffix}")


def fail(label: str, detail: str = "", critical: bool = True) -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{FAIL}] {label}{suffix}")
    if critical:
        _failures.append(label)


def warn(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{WARN}] {label}{suffix}")


# ── 1. Environment variables ────────────────────────────────────────────────

def check_env_vars() -> None:
    print("\n[1] Environment variables")
    required = {
        "ANTHROPIC_API_KEY": True,
        "DATABASE_URL": True,
        "REDIS_URL": True,
    }
    optional = {
        "EIA_API_KEY": "Commodities feed",
        "FRED_API_KEY": "Macro data feed",
    }
    for var, critical in required.items():
        val = os.environ.get(var, "")
        if val and val not in ("your_anthropic_api_key_here", "change_me"):
            ok(var)
        else:
            fail(var, "not set or placeholder", critical=critical)
    for var, purpose in optional.items():
        val = os.environ.get(var, "")
        if val:
            ok(var, purpose)
        else:
            warn(var, f"optional — {purpose}")


# ── 2. Module imports ────────────────────────────────────────────────────────

def check_imports() -> None:
    print("\n[2] Module imports")
    modules = [
        ("src.agents.graph",               "GraphAgent / run_trading_cycle"),
        ("src.agents.nova",                "NovaAgent"),
        ("src.agents.xrp_analyst",         "XRPAnalystAgent"),
        ("src.agents.polymarket_scout",    "PolymarketScoutAgent"),
        ("src.data.feeds.xrpl_feed",       "XRPLFeed"),
        ("src.data.feeds.polymarket_feed", "PolymarketFeed"),
        ("src.data.feeds.feed_manager",    "feed_manager"),
        ("src.execution.trade_desk",       "TradeDeskAgent"),
        ("src.execution.position_monitor", "position_monitor"),
        ("src.execution.risk_monitor",     "risk_monitor"),
        ("src.oversight.portfolio_chief",  "PortfolioChief run()"),
        ("src.learning.agent_memory",      "AgentMemory"),
        ("src.learning.calibration",       "calibration"),
        ("src.api.routers.execution",      "execution router"),
        ("src.api.routers.market",         "market router"),
    ]
    for mod, label in modules:
        try:
            __import__(mod)
            ok(mod, label)
        except Exception as e:
            fail(mod, str(e)[:80])



# ── 3. Redis ─────────────────────────────────────────────────────────────────

async def check_redis() -> None:
    print("\n[3] Redis connection")
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = aioredis.from_url(url, socket_connect_timeout=3)
        pong = await r.ping()
        await r.aclose()
        if pong:
            ok("Redis ping", url)
        else:
            fail("Redis ping", "no response")
    except Exception as e:
        fail("Redis connection", str(e)[:80])


# ── 4. PostgreSQL ─────────────────────────────────────────────────────────────

async def check_postgres() -> None:
    print("\n[4] PostgreSQL connection")
    try:
        import asyncpg  # type: ignore[import]
        url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://tradingfloor:tradingfloor_dev@localhost:5432/tradingfloor",
        )
        # asyncpg uses postgres:// scheme
        pg_url = url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncio.wait_for(asyncpg.connect(pg_url), timeout=5)
        ver = await conn.fetchval("SELECT version()")
        await conn.close()
        ok("PostgreSQL connected", ver.split(",")[0])
    except Exception as e:
        fail("PostgreSQL connection", str(e)[:80])


# ── 5. Exchange (CCXT public endpoint) ───────────────────────────────────────

async def check_exchange() -> None:
    print("\n[5] Exchange connectivity (CCXT / Binance public)")
    try:
        import ccxt.async_support as ccxt  # type: ignore[import]
        exchange = ccxt.binance({"enableRateLimit": True})
        ticker = await asyncio.wait_for(exchange.fetch_ticker("BTC/USDT"), timeout=10)
        await exchange.close()
        price = ticker.get("last", 0)
        ok("Binance ticker (BTC/USDT)", f"last=${price:,.0f}")
    except Exception as e:
        fail("CCXT / Binance public", str(e)[:80])


# ── 6. XRPL RPC ──────────────────────────────────────────────────────────────

async def check_xrpl() -> None:
    print("\n[6] XRPL RPC (s1.ripple.com)")
    try:
        import httpx  # type: ignore[import]
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                "https://s1.ripple.com:51234",
                json={"method": "server_info", "params": [{}]},
            )
            data = resp.json()
            seq = data.get("result", {}).get("info", {}).get("validated_ledger", {}).get("seq")
            ok("XRPL RPC reachable", f"ledger_seq={seq}")
    except Exception as e:
        warn("XRPL RPC", f"{str(e)[:80]} (non-critical — feed uses fallback)")


# ── 7. Polymarket API ─────────────────────────────────────────────────────────

async def check_polymarket() -> None:
    print("\n[7] Polymarket API")
    try:
        import httpx  # type: ignore[import]
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params={"active": True, "limit": 1},
            )
            if resp.status_code == 200:
                ok("Polymarket API reachable", "gamma-api.polymarket.com")
            else:
                warn("Polymarket API", f"HTTP {resp.status_code}")
    except Exception as e:
        warn("Polymarket API", f"{str(e)[:80]} (non-critical — feed uses fallback)")


# ── 8. yfinance spot check ───────────────────────────────────────────────────

async def check_yfinance() -> None:
    print("\n[8] yfinance (GC=F gold futures)")
    try:
        import yfinance as yf  # type: ignore[import]

        loop = asyncio.get_event_loop()
        ticker = await loop.run_in_executor(None, lambda: yf.Ticker("GC=F").fast_info)
        price = getattr(ticker, "last_price", None)
        if price:
            ok("yfinance data", f"GC=F last=${price:,.2f}")
        else:
            warn("yfinance", "price returned None (market may be closed)")
    except Exception as e:
        fail("yfinance", str(e)[:80])



# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    # Load .env if present
    try:
        from dotenv import load_dotenv  # type: ignore[import]
        load_dotenv()
    except ImportError:
        pass  # python-dotenv optional

    print("=" * 60)
    print("  The Trading Floor — Pre-flight Health Check")
    print("=" * 60)

    # Synchronous checks first
    check_env_vars()
    check_imports()

    # Async checks
    await check_redis()
    await check_postgres()
    await check_exchange()
    await check_xrpl()
    await check_polymarket()
    await check_yfinance()

    # Summary
    print("\n" + "=" * 60)
    if _failures:
        print(f"  [{FAIL}] {len(_failures)} critical check(s) failed:")
        for f in _failures:
            print(f"           - {f}")
        print("  Fix the above before starting the system.")
        print("=" * 60 + "\n")
        sys.exit(1)
    else:
        print(f"  [{PASS}] All critical checks passed. System is ready.")
        print("=" * 60 + "\n")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
