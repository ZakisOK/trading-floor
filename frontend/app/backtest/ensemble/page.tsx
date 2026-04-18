"use client";
import { useState, useEffect, useRef, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Trade {
  symbol: string;
  direction: string;
  entry_ts: string;
  entry_price: number;
  exit_ts: string;
  exit_price: number;
  quantity: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
  entry_confidence: number;
  entry_agents: string[];
}

interface Decision {
  ts: string;
  decision: string;
  confidence: number;
  price: number;
  signals: number;
}

interface EnsembleResult {
  job_id: string;
  status: "pending" | "running" | "complete" | "failed";
  symbol: string;
  timeframe: string;
  start: string | null;
  end: string | null;
  initial_equity: number;
  final_equity: number;
  total_return_pct: number;
  win_rate: number;
  max_drawdown_pct: number;
  bars_processed: number;
  bars_total: number;
  trades: Trade[];
  equity_curve: { ts: string; equity: number }[];
  decisions: Decision[];
  error: string | null;
}

const SYMBOLS = [
  "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT",
  "ADA/USDT", "AVAX/USDT", "DOGE/USDT", "LINK/USDT",
  "DOT/USDT", "MATIC/USDT", "UNI/USDT",
];

function fmt(n: number | null | undefined, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function pct(n: number | null | undefined) {
  if (n == null || isNaN(n)) return "—";
  return `${(n * 100).toFixed(2)}%`;
}
function directionColor(d: string) {
  if (d === "LONG") return "var(--accent-profit)";
  if (d === "SHORT") return "var(--accent-loss)";
  return "var(--text-tertiary)";
}

function EquityChart({ points }: { points: { ts: string; equity: number }[] }) {
  if (points.length < 2) return <div style={{ color: "var(--text-tertiary)", fontSize: 12 }}>Waiting for data…</div>;
  const W = 900, H = 180, pad = 32;
  const xs = points.map((_, i) => pad + (i / (points.length - 1)) * (W - 2 * pad));
  const ys = points.map((p) => p.equity);
  const min = Math.min(...ys), max = Math.max(...ys);
  const range = max - min || 1;
  const yScale = (v: number) => H - pad - ((v - min) / range) * (H - 2 * pad);
  const start = ys[0];
  const polyPts = xs.map((x, i) => `${x},${yScale(ys[i])}`).join(" ");
  const endColor = ys[ys.length - 1] >= start ? "var(--accent-profit)" : "var(--accent-loss)";
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ background: "var(--bg-panel)", borderRadius: 6, border: "1px solid var(--border-subtle)" }}>
      <line x1={pad} x2={W - pad} y1={yScale(start)} y2={yScale(start)} stroke="var(--border-subtle)" strokeDasharray="3 3" />
      <polyline fill="none" stroke={endColor} strokeWidth="1.5" points={polyPts} />
      <text x={pad} y={14} fill="var(--text-tertiary)" fontSize="10">${fmt(min, 0)}</text>
      <text x={pad} y={H - 4} fill="var(--text-tertiary)" fontSize="10">${fmt(max, 0)}</text>
    </svg>
  );
}

export default function EnsembleBacktestPage() {
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [timeframe, setTimeframe] = useState("1d");
  const [days, setDays] = useState(30);
  const [equity, setEquity] = useState(10000);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<EnsembleResult | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPoll(), [stopPoll]);

  async function run() {
    stopPoll();
    setResult(null);
    setRunning(true);
    const r = await fetch(`${API}/api/backtest/ensemble/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, timeframe, days, initial_equity: equity }),
    });
    const { job_id } = await r.json();
    pollRef.current = setInterval(async () => {
      const rr = await fetch(`${API}/api/backtest/ensemble/result/${job_id}`);
      if (!rr.ok) return;
      const data: EnsembleResult = await rr.json();
      setResult(data);
      if (data.status === "complete" || data.status === "failed") {
        stopPoll();
        setRunning(false);
      }
    }, 2000);
  }

  const inputStyle: React.CSSProperties = {
    background: "var(--bg-surface-2)", border: "1px solid var(--border-default)",
    borderRadius: 4, color: "var(--text-primary)", padding: "7px 10px",
    fontSize: 13, fontFamily: "var(--font-mono)", width: "100%",
  };
  const labelStyle: React.CSSProperties = { color: "var(--text-secondary)", fontSize: 11, marginBottom: 3, display: "block", textTransform: "uppercase", letterSpacing: "0.05em" };

  const progress = result?.bars_total ? (result.bars_processed / result.bars_total) : 0;

  return (
    <div style={{ padding: "28px 32px", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
          <span style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
            Ensemble Backtest
          </span>
          <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 3, fontWeight: 600, background: "rgba(94,106,210,0.15)", color: "var(--accent-primary)", letterSpacing: "0.05em", textTransform: "uppercase" }}>
            Agent Replay
          </span>
        </div>
        <p style={{ fontSize: 13, color: "var(--text-tertiary)", margin: 0 }}>
          Replay historical bars through the full agent ensemble — Marcus, Vera, Rex, Diana, Atlas — and simulate entries/exits with the same 3% stop / 6% target rules as the live paper loop.
        </p>
      </div>

      <div className="glass-panel" style={{ padding: 20, marginBottom: 20 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 14, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>Symbol</label>
            <select style={inputStyle} value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {SYMBOLS.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Timeframe</label>
            <select style={inputStyle} value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              <option value="1d">1d — cheap, fast</option>
              <option value="4h">4h</option>
              <option value="1h">1h — expensive</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>Days</label>
            <input style={inputStyle} type="number" min={1} max={365} value={days} onChange={(e) => setDays(+e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>Initial Equity ($)</label>
            <input style={inputStyle} type="number" min={100} value={equity} onChange={(e) => setEquity(+e.target.value)} />
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button onClick={run} disabled={running} style={{
            background: running ? "var(--bg-surface-3)" : "var(--accent-primary)", color: "#fff",
            border: "none", borderRadius: 4, padding: "9px 22px", fontSize: 13, fontWeight: 600,
            cursor: running ? "not-allowed" : "pointer",
          }}>
            {running ? "Running…" : "Run Backtest"}
          </button>
          <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
            {timeframe === "1d" ? "~30-60 sec for 30 days" : timeframe === "4h" ? "several minutes" : "10+ minutes — lots of LLM calls"}
          </span>
        </div>
      </div>

      {running && result && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 4 }}>
            Processing bars — {result.bars_processed} / {result.bars_total}
          </div>
          <div style={{ height: 4, background: "var(--border-subtle)", borderRadius: 2, overflow: "hidden" }}>
            <div style={{ width: `${progress * 100}%`, height: "100%", background: "var(--accent-primary)", transition: "width 0.3s" }} />
          </div>
        </div>
      )}

      {result?.status === "failed" && (
        <div style={{ padding: 16, border: "1px solid var(--accent-loss)", borderRadius: 6, color: "var(--accent-loss)", fontSize: 13, marginBottom: 16 }}>
          {result.error || "Backtest failed"}
          {result.error?.includes("No OHLCV") && (
            <div style={{ marginTop: 8, color: "var(--text-secondary)" }}>
              Run <code>python scripts/ingest_ohlcv.py</code> on the droplet to backfill history, then try again.
            </div>
          )}
        </div>
      )}

      {result && result.bars_processed > 0 && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10, marginBottom: 16 }}>
            {[
              { label: "Final Equity", value: `$${fmt(result.final_equity, 0)}` },
              { label: "Total Return", value: pct(result.total_return_pct), color: result.total_return_pct >= 0 ? "var(--accent-profit)" : "var(--accent-loss)" },
              { label: "Win Rate", value: pct(result.win_rate) },
              { label: "Max Drawdown", value: pct(result.max_drawdown_pct), color: "var(--accent-loss)" },
              { label: "Trades", value: String(result.trades.length) },
            ].map(({ label, value, color }) => (
              <div key={label} className="glass-panel" style={{ padding: "12px 14px" }}>
                <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 3, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: color || "var(--text-primary)" }}>{value}</div>
              </div>
            ))}
          </div>

          <div className="glass-panel" style={{ padding: 16, marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>Equity curve</div>
            <EquityChart points={result.equity_curve} />
          </div>

          {result.trades.length > 0 && (
            <div className="glass-panel" style={{ padding: 16, marginBottom: 16 }}>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>Trades</div>
              <div style={{ maxHeight: 300, overflowY: "auto" }}>
                <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ color: "var(--text-tertiary)", textAlign: "left" }}>
                      <th style={{ padding: "6px 8px", fontWeight: 600 }}>Entry</th>
                      <th style={{ padding: "6px 8px", fontWeight: 600 }}>Dir</th>
                      <th style={{ padding: "6px 8px", fontWeight: 600 }}>In</th>
                      <th style={{ padding: "6px 8px", fontWeight: 600 }}>Out</th>
                      <th style={{ padding: "6px 8px", fontWeight: 600 }}>P&L</th>
                      <th style={{ padding: "6px 8px", fontWeight: 600 }}>Reason</th>
                      <th style={{ padding: "6px 8px", fontWeight: 600 }}>Agents</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <tr key={i} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                        <td style={{ padding: "6px 8px", fontFamily: "monospace", color: "var(--text-tertiary)", fontSize: 11 }}>{new Date(t.entry_ts).toLocaleDateString()}</td>
                        <td style={{ padding: "6px 8px", fontWeight: 700, color: directionColor(t.direction) }}>{t.direction}</td>
                        <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>${fmt(t.entry_price, 2)}</td>
                        <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>${fmt(t.exit_price, 2)}</td>
                        <td style={{ padding: "6px 8px", fontWeight: 700, color: t.pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)" }}>
                          {t.pnl >= 0 ? "+" : ""}${fmt(t.pnl, 2)} ({pct(t.pnl_pct)})
                        </td>
                        <td style={{ padding: "6px 8px", fontSize: 10, color: "var(--text-tertiary)", textTransform: "uppercase" }}>{t.exit_reason}</td>
                        <td style={{ padding: "6px 8px", fontSize: 10, color: "var(--text-secondary)" }}>{t.entry_agents.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {result.decisions.length > 0 && (
            <div className="glass-panel" style={{ padding: 16 }}>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>Per-bar decisions</div>
              <div style={{ maxHeight: 240, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
                {result.decisions.map((d, i) => (
                  <div key={i} style={{ display: "grid", gridTemplateColumns: "120px 70px 90px 100px 70px", gap: 10, fontSize: 11 }}>
                    <span style={{ color: "var(--text-tertiary)", fontFamily: "monospace" }}>{new Date(d.ts).toLocaleDateString()}</span>
                    <span style={{ fontWeight: 700, color: directionColor(d.decision) }}>{d.decision}</span>
                    <span style={{ color: "var(--text-secondary)" }}>{(d.confidence * 100).toFixed(0)}% conf</span>
                    <span style={{ color: "var(--text-tertiary)" }}>${fmt(d.price, 2)}</span>
                    <span style={{ color: "var(--text-tertiary)" }}>{d.signals} agents</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
