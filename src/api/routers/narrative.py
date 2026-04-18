"""Narrative feed — human-readable story of what the firm is doing.

Synthesizes discrete events from Redis streams and schedule state into
one-line sentences that read like a trading desk's daily log.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter

from src.core.redis import get_redis

router = APIRouter(prefix="/api/narrative", tags=["narrative"])


def _fmt_price(sym: str, p: float) -> str:
    if p < 1:
        return f"${p:.4f}"
    if p < 100:
        return f"${p:.2f}"
    return f"${p:,.0f}"


def _parse_iso(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


async def _narrate_cycles(redis) -> list[dict]:
    raw = await redis.lrange("schedule:completions", 0, 19)
    events: list[dict] = []
    for item in raw:
        try:
            c = json.loads(item)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        ts = _parse_iso(c.get("finished_at"))
        sym = c.get("symbol", "?")
        decision = (c.get("decision") or "NEUTRAL").upper()
        sigs = c.get("signals", 0)
        approved = c.get("approved", False)
        duration = c.get("duration_s", 0)

        if decision == "NEUTRAL":
            text = f"Cycle on {sym} — {sigs} signals but no conviction, passed."
        elif not approved:
            text = f"Cycle on {sym} wanted {decision} but Diana rejected (below threshold)."
        else:
            text = f"Cycle on {sym} → consensus {decision} ({sigs} signals) — passed risk check."
        events.append({
            "ts": c.get("finished_at"),
            "kind": "cycle",
            "severity": "info" if approved else "muted",
            "text": text,
            "duration_s": duration,
        })
    return events


async def _narrate_trades(redis) -> list[dict]:
    """Trade fills from stream:trades."""
    raw = await redis.xrevrange("stream:trades", count=15)
    events: list[dict] = []
    for _id, fields in raw:
        sym = fields.get("symbol", "?")
        side = fields.get("side", "?")
        try:
            price = float(fields.get("filled_price") or 0)
            qty = float(fields.get("quantity") or 0)
        except ValueError:
            price = qty = 0
        agent = fields.get("agent_id", "atlas")
        strategy = fields.get("strategy", "")
        if strategy.startswith("auto_exit:"):
            reason = strategy.split(":", 1)[1]
            text = f"Closed {sym} at {_fmt_price(sym, price)} ({reason} hit)."
            sev = "win" if "target" in reason else "loss" if "stop" in reason else "info"
        else:
            side_word = "bought" if side == "BUY" else "sold"
            text = f"{agent.capitalize()} {side_word} {qty:.4f} {sym} at {_fmt_price(sym, price)}."
            sev = "trade"
        events.append({
            "ts": None,  # stream ids are ms-precision but xrevrange returned in order
            "kind": "trade",
            "severity": sev,
            "text": text,
        })
    return events


async def _narrate_pnl(redis) -> list[dict]:
    raw = await redis.xrevrange("stream:pnl", count=10)
    events: list[dict] = []
    for _id, fields in raw:
        sym = fields.get("symbol", "?")
        reason = fields.get("reason", "")
        try:
            pnl = float(fields.get("pnl") or 0)
            entry = float(fields.get("entry_price") or 0)
            exit_p = float(fields.get("exit_price") or 0)
        except ValueError:
            pnl = entry = exit_p = 0
        sign = "+" if pnl >= 0 else ""
        text = (f"{sym} position closed on {reason} — entry {_fmt_price(sym, entry)} → "
                f"exit {_fmt_price(sym, exit_p)}, P&L {sign}${pnl:.2f}.")
        events.append({
            "ts": None,
            "kind": "pnl",
            "severity": "win" if pnl > 0 else "loss" if pnl < 0 else "info",
            "text": text,
        })
    return events


async def _narrate_pending(redis) -> list[dict]:
    raw = await redis.hgetall("approval:pending") or {}
    events: list[dict] = []
    for v in raw.values():
        try:
            p = json.loads(v)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        contributors = ", ".join(p.get("contributing_agents") or []) or "consensus"
        text = (f"{p['side']} {p['symbol']} queued for approval — "
                f"{contributors} aligned at {int(p['confidence'] * 100)}% conviction.")
        events.append({
            "ts": p.get("created_at"),
            "kind": "pending",
            "severity": "warn",
            "text": text,
        })
    return events


@router.get("")
async def narrative() -> dict:
    """Return a merged, time-sorted list of plain-English events."""
    redis = get_redis()
    cycles = await _narrate_cycles(redis)
    trades = await _narrate_trades(redis)
    pnls = await _narrate_pnl(redis)
    pendings = await _narrate_pending(redis)

    all_events = cycles + trades + pnls + pendings
    # Stable sort by ts (None sorts last)
    all_events.sort(key=lambda e: e.get("ts") or "", reverse=True)

    # Summary stats for the top of the narrative
    now = datetime.now(UTC)
    cycles_ok = sum(1 for e in cycles if e["severity"] == "info")
    cycles_rejected = sum(1 for e in cycles if e["severity"] == "muted")
    wins = sum(1 for e in pnls if e["severity"] == "win")
    losses = sum(1 for e in pnls if e["severity"] == "loss")
    pending_count = len(pendings)

    return {
        "ts": now.isoformat(),
        "summary": {
            "cycles_completed": cycles_ok + cycles_rejected,
            "cycles_approved": cycles_ok,
            "cycles_rejected": cycles_rejected,
            "wins": wins,
            "losses": losses,
            "pending": pending_count,
        },
        "events": all_events[:40],
    }
