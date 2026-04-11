"""Redis Streams topology — canonical stream name registry for the whole firm."""

# ---------------------------------------------------------------------------
# Desk 1 — Alpha Research
# ---------------------------------------------------------------------------
MARKET_DATA = "stream:market_data"
SIGNALS_RAW = "stream:signals:raw"
SIGNALS_VALIDATED = "stream:signals:validated"
AGENT_TASKS = "stream:agent:tasks"
AGENT_RESULTS = "stream:agent:results"
AGENT_LESSONS = "stream:agent:lessons"       # Learning layer → agents (lesson injection)

# ---------------------------------------------------------------------------
# Desk 1 → Desk 2 handoff
# ---------------------------------------------------------------------------
TRADE_DESK_INBOX = "stream:trade_desk:inbox"  # Nova conviction packets → Desk 2

# ---------------------------------------------------------------------------
# Desk 2 — Trade Execution
# ---------------------------------------------------------------------------
ORDERS = "stream:orders"
TRADES = "stream:trades"
TRADE_OUTCOMES = "stream:trade_outcomes"      # Desk 2 → Learning layer (closed trades)

# ---------------------------------------------------------------------------
# Desk 3 — Portfolio Oversight
# ---------------------------------------------------------------------------
PORTFOLIO_EVENTS = "stream:portfolio:events"  # Portfolio Chief broadcasts

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
PNL = "stream:pnl"
AUDIT = "stream:audit"
ALERTS = "stream:alerts"

# ---------------------------------------------------------------------------
# Consumer groups
# ---------------------------------------------------------------------------
CONSUMER_GROUPS: dict[str, str] = {
    "market_analysts": "cg:market_analysts",
    "risk_managers": "cg:risk_managers",
    "executors": "cg:executors",
    "portfolio": "cg:portfolio",
    "ws_broadcast": "cg:ws_broadcast",
    "audit_writer": "cg:audit_writer",
    "trade_desk": "cg:trade_desk",           # Desk 2 consumer group
    "learning_layer": "cg:learning_layer",   # Learning layer consumer group
}
