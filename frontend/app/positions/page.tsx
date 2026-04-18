"use client";
import { useState, useEffect, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_MS = 5000; // match the 5-second monitor cycle

interface LivePosition {
  symbol: string;
  side: string;
  quantity: number;
  avg_price: number;
  entry_time: string;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  stop_loss: number;
  take_profit: number;
  trailing_stop: number | null;
  distance_to_stop_pct: number;   // 0 = at stop, 1 = at entry
  distance_to_target_pct: number; // 0 = at target, 1 = at entry
}

interface RiskMetrics {
  daily_pnl: number;
  portfolio_value: number;
  total_exposure: number;
  drawdown_pct: number;
  open_positions: string | number;
  updated_at: string | null;
}

const mono = { fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" as const };


function PnlLabel({ val, pct }: { val: number; pct: number }) {
  const color = val >= 0 ? "var(--accent-profit)" : "var(--accent-loss)";
  return (
    <div>
      <div style={{ ...mono, fontSize: 18, fontWeight: 700, color }}>
        {val >= 0 ? "+" : ""}${val.toFixed(4)}
      </div>
      <div style={{ ...mono, fontSize: 11, color, opacity: 0.8 }}>
        {val >= 0 ? "+" : ""}{(pct * 100).toFixed(2)}%
      </div>
    </div>
  );
}

/** Green/red progress bar showing how far price is from stop vs target. */
function DistanceBar({ pos }: { pos: LivePosition }) {
  const pnlPct = pos.unrealized_pnl_pct;
  const isProfit = pnlPct >= 0;
  const fill = isProfit ? "var(--accent-profit)" : "var(--accent-loss)";

  // distance_to_stop_pct: 1 = far from stop, 0 = at stop
  const stopFill = Math.max(0, Math.min(1, pos.distance_to_stop_pct)) * 100;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-tertiary)", marginBottom: 4 }}>
        <span>STOP ${pos.stop_loss.toFixed(4)}{pos.trailing_stop ? " (trailing)" : ""}</span>
        <span>TARGET ${pos.take_profit.toFixed(4)}</span>
      </div>
      <div style={{ height: 6, background: "var(--bg-surface-3)", borderRadius: 3, overflow: "hidden", position: "relative" }}>
        {/* stop danger zone bar — fills red from left as price approaches stop */}
        <div style={{
          position: "absolute", left: 0, top: 0, height: "100%",
          width: `${100 - stopFill}%`,
          background: "rgba(248,81,73,0.35)",
          transition: "width 0.8s ease",
        }} />
        {/* price cursor */}
        <div style={{
          position: "absolute", top: 0, height: "100%", width: 2,
          left: `${stopFill}%`,
          background: fill,
          transition: "left 0.8s ease",
        }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-tertiary)", marginTop: 3 }}>
        <span style={{ color: "var(--accent-loss)" }}>{(100 - stopFill).toFixed(0)}% to stop</span>
        <span style={{ color: "var(--accent-profit)" }}>{(pos.distance_to_target_pct * 100).toFixed(0)}% to target</span>
      </div>
    </div>
  );
}


function PositionCard({ pos }: { pos: LivePosition }) {
  const isProfit = pos.unrealized_pnl >= 0;
  const borderColor = isProfit ? "rgba(88,214,141,0.25)" : "rgba(248,81,73,0.25)";
  const entryTime = new Date(pos.entry_time).toLocaleTimeString();

  return (
    <div style={{
      background: "var(--bg-surface-1)",
      border: `1px solid ${borderColor}`,
      borderRadius: "var(--radius-md)",
      padding: "20px 24px",
      display: "flex",
      flexDirection: "column",
      gap: 16,
    }}>
      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ ...mono, fontSize: 20, fontWeight: 700 }}>{pos.symbol}</div>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2 }}>
            LONG · {pos.quantity.toFixed(6)} · entered {entryTime}
          </div>
        </div>
        <PnlLabel val={pos.unrealized_pnl} pct={pos.unrealized_pnl_pct} />
      </div>

      {/* Price row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <div style={{ background: "var(--bg-surface-2)", borderRadius: "var(--radius-sm)", padding: "10px 14px" }}>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 4 }}>Entry Price</div>
          <div style={{ ...mono, fontSize: 15, fontWeight: 600 }}>${pos.avg_price.toFixed(6)}</div>
        </div>
        <div style={{ background: "var(--bg-surface-2)", borderRadius: "var(--radius-sm)", padding: "10px 14px" }}>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 4 }}>Current Price</div>
          <div style={{ ...mono, fontSize: 15, fontWeight: 600, color: isProfit ? "var(--accent-profit)" : "var(--accent-loss)" }}>
            ${pos.current_price.toFixed(6)}
          </div>
        </div>
      </div>

      {/* Distance bar */}
      <DistanceBar pos={pos} />

      {/* Trailing stop indicator */}
      {pos.trailing_stop && (
        <div style={{ fontSize: 11, color: "var(--accent-primary)", display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--accent-primary)", display: "inline-block" }} />
          Trailing stop active at ${pos.trailing_stop.toFixed(6)} (breakeven)
        </div>
      )}
    </div>
  );
}


function RiskBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = Math.min(1, Math.abs(value) / max) * 100;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-secondary)", marginBottom: 4 }}>
        <span>{label}</span>
        <span style={{ ...mono, color }}>{(value * 100).toFixed(2)}%</span>
      </div>
      <div style={{ height: 4, background: "var(--bg-surface-3)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 2, transition: "width 1s ease" }} />
      </div>
    </div>
  );
}

interface TradeHistoryItem {
  symbol: string;
  side: string;
  status: "open" | "closed";
  entry_ts: string | null;
  exit_ts: string | null;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  pnl: number | null;
  pnl_pct: number | null;
  exit_reason: string | null;
  entry_agent: string | null;
}

export default function PositionsPage() {
  const [positions, setPositions] = useState<LivePosition[]>([]);
  const [history, setHistory] = useState<TradeHistoryItem[]>([]);
  const [risk, setRisk] = useState<RiskMetrics | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [posRes, riskRes, histRes] = await Promise.all([
        fetch(`${API}/api/execution/positions`),
        fetch(`${API}/api/execution/risk-metrics`),
        fetch(`${API}/api/orders/history`),
      ]);
      if (!posRes.ok) throw new Error(`Positions API ${posRes.status}`);
      const [pos, riskData, hist] = await Promise.all([posRes.json(), riskRes.json(), histRes.json()]);
      setPositions(pos);
      setRisk(riskData);
      setHistory(Array.isArray(hist) ? hist : []);
      setLastUpdate(new Date());
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fetch failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, POLL_MS);
    return () => clearInterval(iv);
  }, [fetchData]);

  const card = {
    background: "var(--bg-surface-1)",
    border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-md)",
    padding: "16px 20px",
  };

  const drawdownPct = risk ? Math.abs(Number(risk.drawdown_pct)) : 0;
  const drawdownColor = drawdownPct > 0.04 ? "var(--accent-loss)" : drawdownPct > 0.02 ? "#f0a500" : "var(--accent-profit)";

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-void)", color: "var(--text-primary)", padding: "32px", fontFamily: "var(--font-sans)" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>

        {/* Page header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 28 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 4 }}>Live Positions</h1>
            <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
              Real-time monitor — exits fire within 5 seconds of stop or target hit
            </p>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>Last updated</div>
            <div style={{ ...mono, fontSize: 12, color: "var(--text-secondary)" }}>
              {lastUpdate ? lastUpdate.toLocaleTimeString() : "—"}
            </div>
            <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 2 }}>
              auto-refresh every 5s
            </div>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div style={{ marginBottom: 16, padding: "10px 16px", background: "rgba(248,81,73,0.1)", border: "1px solid var(--accent-loss)", borderRadius: "var(--radius-sm)", color: "var(--accent-loss)", fontSize: 13 }}>
            {error} — monitors may not be running (.\run.ps1 monitors)
          </div>
        )}


        {/* Risk metrics strip */}
        {risk && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, marginBottom: 24 }}>
            {[
              { l: "Portfolio Value", v: `$${Number(risk.portfolio_value).toLocaleString("en", { minimumFractionDigits: 2 })}` },
              { l: "Daily P&L", v: null, pnl: Number(risk.daily_pnl) },
              { l: "Total Exposure", v: `$${Number(risk.total_exposure).toFixed(2)}` },
              { l: "Open Positions", v: String(risk.open_positions) },
            ].map(m => (
              <div key={m.l} style={card}>
                <div style={{ fontSize: 10, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 6 }}>{m.l}</div>
                <div style={{ ...mono, fontSize: 17, fontWeight: 700 }}>
                  {m.pnl !== undefined ? (
                    <span style={{ color: m.pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)" }}>
                      {m.pnl >= 0 ? "+" : ""}${m.pnl.toFixed(4)}
                    </span>
                  ) : m.v}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Drawdown bar */}
        {risk && (
          <div style={{ ...card, marginBottom: 24 }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 12 }}>
              Daily Drawdown vs Limit
            </div>
            <RiskBar
              label={`Drawdown (limit: 5%)`}
              value={-drawdownPct}
              max={0.05}
              color={drawdownColor}
            />
          </div>
        )}

        {/* Position cards */}
        {loading ? (
          <div style={{ textAlign: "center", color: "var(--text-tertiary)", padding: 60, fontSize: 14 }}>
            Loading positions...
          </div>
        ) : positions.length === 0 ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>—</div>
            <div style={{ color: "var(--text-tertiary)", fontSize: 14 }}>No open positions</div>
            <div style={{ color: "var(--text-tertiary)", fontSize: 12, marginTop: 6 }}>
              The monitor is running and will fire exits the moment a stop or target is hit.
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))", gap: 16 }}>
            {positions.map(p => <PositionCard key={p.symbol} pos={p} />)}
          </div>
        )}

        {/* Order history — closed trades */}
        <div style={{ marginTop: 32 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Order History
          </div>
          <div style={{ ...card, padding: 0, overflow: "hidden" }}>
            <div style={{
              display: "grid",
              gridTemplateColumns: "70px 100px 80px 90px 90px 110px 100px 1fr",
              gap: 10, padding: "10px 16px", fontSize: 10,
              color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em",
              borderBottom: "1px solid var(--border-subtle)",
            }}>
              <span>Status</span>
              <span>Symbol</span>
              <span>Side</span>
              <span>Entry</span>
              <span>Exit</span>
              <span>P&L</span>
              <span>Reason</span>
              <span>When</span>
            </div>
            {history.length === 0 ? (
              <div style={{ padding: 24, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
                No trades yet. When Atlas fills an order it&apos;ll show here.
              </div>
            ) : (
              history.slice(0, 50).map((t, i) => (
                <div key={i} style={{
                  display: "grid",
                  gridTemplateColumns: "70px 100px 80px 90px 90px 110px 100px 1fr",
                  gap: 10, padding: "10px 16px", fontSize: 12,
                  borderBottom: "1px solid var(--border-subtle)",
                  alignItems: "baseline",
                }}>
                  <span style={{
                    fontSize: 10, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase",
                    color: t.status === "open" ? "#f59e0b" : "var(--text-tertiary)",
                  }}>
                    {t.status}
                  </span>
                  <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{t.symbol}</span>
                  <span style={{ fontWeight: 700, color: "var(--accent-profit)" }}>{t.side}</span>
                  <span style={{ ...mono, color: "var(--text-secondary)" }}>${t.entry_price.toFixed(t.entry_price < 10 ? 4 : 2)}</span>
                  <span style={{ ...mono, color: "var(--text-secondary)" }}>
                    {t.exit_price != null ? `$${t.exit_price.toFixed(t.exit_price < 10 ? 4 : 2)}` : "—"}
                  </span>
                  <span style={{ ...mono, color: t.pnl == null ? "var(--text-tertiary)" : t.pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)", fontWeight: 600 }}>
                    {t.pnl == null ? "open" : `${t.pnl >= 0 ? "+" : ""}$${t.pnl.toFixed(2)}`}
                  </span>
                  <span style={{ fontSize: 10, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.03em" }}>
                    {t.exit_reason || "—"}
                  </span>
                  <span style={{ ...mono, color: "var(--text-tertiary)", fontSize: 10 }}>
                    {t.entry_ts ? new Date(t.entry_ts).toLocaleString() : "—"}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
