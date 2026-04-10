MARKET_DATA = "stream:market_data"
SIGNALS_RAW = "stream:signals:raw"
SIGNALS_VALIDATED = "stream:signals:validated"
ORDERS = "stream:orders"
TRADES = "stream:trades"
AGENT_TASKS = "stream:agent:tasks"
AGENT_RESULTS = "stream:agent:results"
PNL = "stream:pnl"
AUDIT = "stream:audit"
ALERTS = "stream:alerts"

CONSUMER_GROUPS: dict[str, str] = {
    "market_analysts": "cg:market_analysts",
    "risk_managers": "cg:risk_managers",
    "executors": "cg:executors",
    "portfolio": "cg:portfolio",
    "ws_broadcast": "cg:ws_broadcast",
    "audit_writer": "cg:audit_writer",
}
