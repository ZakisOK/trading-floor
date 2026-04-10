"use client";
import { useState, useEffect, useRef } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface BacktestResult {
  job_id: string;
  status: string;
  symbol?: string;
  strategy?: string;
  sharpe_ratio?: number;
  sortino_ratio?: number;
  max_drawdown_pct?: number;
  win_rate?: number;
  profit_factor?: number;
  total_trades?: number;
  total_return_pct?: number;
  cagr?: number;
  equity_curve?: number[];
  trades?: Array<{ pnl: number; pnl_pct: number; entry: string; exit: string; reason: string }>;
  error?: string;
}

function fmt(n: number | undefined, dec = 2): string {
  if (n === undefined || n === null) return "—";
  if (!isFinite(n)) return "∞";
  return n.toFixed(dec);
}

function MetricCard({ label, value, suffix = "", color }: { label: string; value: string; suffix?: string; color?: string }) {
  return (
    <div style={{ background: "var(--bg-surface-1)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: "16px 20px" }}>
      <div style={{ color: "var(--text-tertiary)", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>{label}</div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: "22px", fontVariantNumeric: "tabular-nums", color: color ?? "var(--text-primary)", fontWeight: 600 }}>
        {value}<span style={{ fontSize: "13px", color: "var(--text-secondary)", marginLeft: 2 }}>{suffix}</span>
      </div>
    </div>
  );
}

function EquityCurve({ data }: { data: number[] }) {
  if (!data || data.length < 2) return null;
  const W = 800, H = 160, pad = 8;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (W - pad * 2);
    const y = H - pad - ((v - min) / range) * (H - pad * 2);
    return `${x},${y}`;
  }).join(" ");
  const profit = data[data.length - 1] >= data[0];
  const color = profit ? "var(--accent-profit)" : "var(--accent-loss)";
  const fillId = "eq-fill";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: H, display: "block" }}>
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline fill={`url(#${fillId})`} stroke="none"
        points={`${pad},${H} ${pts} ${W - pad},${H}`} />
      <polyline fill="none" stroke={color} strokeWidth="1.5"
        points={pts} strokeLinejoin="round" />
    </svg>
  );
}

export default function BacktestPage() {
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [exchange, setExchange] = useState("binance");
  const [timeframe, setTimeframe] = useState("1h");
  const [strategy, setStrategy] = useState("sma_crossover");
  const [hours, setHours] = useState(168);
  const [equity, setEquity] = useState(10000);
  const [fastPeriod, setFastPeriod] = useState(10);
  const [slowPeriod, setSlowPeriod] = useState(20);
  const [rsiPeriod, setRsiPeriod] = useState(14);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function runBacktest() {
    setLoading(true);
    setResult(null);
    const params = strategy === "sma_crossover"
      ? { fast: fastPeriod, slow: slowPeriod }
      : { period: rsiPeriod };
    const res = await fetch(`${API}/api/backtest/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, exchange, timeframe, strategy, params, initial_equity: equity, hours }),
    });
    const { job_id } = await res.json();
    pollRef.current = setInterval(async () => {
      const r = await fetch(`${API}/api/backtest/result/${job_id}`);
      const data: BacktestResult = await r.json();
      if (data.status !== "running") {
        clearInterval(pollRef.current!);
        setResult(data);
        setLoading(false);
      }
    }, 1500);
  }

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const inputStyle = {
    background: "var(--bg-surface-2)", border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-sm)", color: "var(--text-primary)",
    padding: "8px 12px", fontSize: "14px", fontFamily: "var(--font-mono)", width: "100%",
  };
  const labelStyle = { color: "var(--text-secondary)", fontSize: "12px", marginBottom: 4, display: "block" };

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-void)", color: "var(--text-primary)", padding: "32px", fontFamily: "var(--font-sans)" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 4 }}>Backtesting Studio</h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: 32 }}>Test strategies against historical data</p>

        {/* Config Panel */}
        <div className="glass-panel" style={{ padding: 24, marginBottom: 24 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16, marginBottom: 20 }}>
            <div><label style={labelStyle}>Symbol</label>
              <select style={inputStyle} value={symbol} onChange={e => setSymbol(e.target.value)}>
                {["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT"].map(s => <option key={s}>{s}</option>)}
              </select></div>
            <div><label style={labelStyle}>Exchange</label>
              <select style={inputStyle} value={exchange} onChange={e => setExchange(e.target.value)}>
                {["binance","coinbase","kraken"].map(s => <option key={s}>{s}</option>)}
              </select></div>
            <div><label style={labelStyle}>Timeframe</label>
              <select style={inputStyle} value={timeframe} onChange={e => setTimeframe(e.target.value)}>
                {["1m","5m","15m","1h","4h","1d"].map(s => <option key={s}>{s}</option>)}
              </select></div>
            <div><label style={labelStyle}>Strategy</label>
              <select style={inputStyle} value={strategy} onChange={e => setStrategy(e.target.value)}>
                <option value="sma_crossover">SMA Crossover</option>
                <option value="rsi_mean_reversion">RSI Mean Reversion</option>
              </select></div>
            <div><label style={labelStyle}>Lookback (hours)</label>
              <input type="number" style={inputStyle} value={hours} min={24} max={8760} onChange={e => setHours(+e.target.value)} /></div>
            <div><label style={labelStyle}>Initial Equity ($)</label>
              <input type="number" style={inputStyle} value={equity} min={100} onChange={e => setEquity(+e.target.value)} /></div>
          </div>
          {strategy === "sma_crossover" && (
            <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
              <div style={{ flex: 1 }}><label style={labelStyle}>Fast Period</label>
                <input type="number" style={inputStyle} value={fastPeriod} min={2} max={100} onChange={e => setFastPeriod(+e.target.value)} /></div>
              <div style={{ flex: 1 }}><label style={labelStyle}>Slow Period</label>
                <input type="number" style={inputStyle} value={slowPeriod} min={5} max={200} onChange={e => setSlowPeriod(+e.target.value)} /></div>
            </div>
          )}
          {strategy === "rsi_mean_reversion" && (
            <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
              <div style={{ flex: 1 }}><label style={labelStyle}>RSI Period</label>
                <input type="number" style={inputStyle} value={rsiPeriod} min={2} max={50} onChange={e => setRsiPeriod(+e.target.value)} /></div>
            </div>
          )}
          <button onClick={runBacktest} disabled={loading} style={{
            background: loading ? "var(--bg-surface-3)" : "var(--accent-primary)", color: "#fff",
            border: "none", borderRadius: "var(--radius-sm)", padding: "10px 28px",
            fontSize: 14, fontWeight: 600, cursor: loading ? "not-allowed" : "pointer", transition: "opacity 0.2s",
          }}>
            {loading ? "Running…" : "Run Backtest"}
          </button>
        </div>

        {/* Loading spinner */}
        {loading && (
          <div style={{ textAlign: "center", padding: 48, color: "var(--text-secondary)" }}>
            <div style={{ fontSize: 32, marginBottom: 12, animation: "spin 1s linear infinite", display: "inline-block" }}>⟳</div>
            <div>Running backtest…</div>
            <style>{`@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}`}</style>
          </div>
        )}

        {/* Error */}
        {result?.status === "error" && (
          <div style={{ background: "rgba(248,81,73,0.1)", border: "1px solid var(--accent-loss)", borderRadius: "var(--radius-md)", padding: "16px 20px", color: "var(--accent-loss)" }}>
            Error: {result.error}
          </div>
        )}

        {/* Results */}
        {result?.status === "done" && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, marginBottom: 24 }}>
              <MetricCard label="Total Return" value={fmt(result.total_return_pct)} suffix="%" color={(result.total_return_pct ?? 0) >= 0 ? "var(--accent-profit)" : "var(--accent-loss)"} />
              <MetricCard label="CAGR" value={fmt(result.cagr)} suffix="%" />
              <MetricCard label="Sharpe Ratio" value={fmt(result.sharpe_ratio)} />
              <MetricCard label="Sortino Ratio" value={fmt(result.sortino_ratio)} />
              <MetricCard label="Max Drawdown" value={fmt(result.max_drawdown_pct)} suffix="%" color="var(--accent-loss)" />
              <MetricCard label="Win Rate" value={fmt(result.win_rate)} suffix="%" color={(result.win_rate ?? 0) >= 50 ? "var(--accent-profit)" : "var(--accent-loss)"} />
              <MetricCard label="Profit Factor" value={fmt(result.profit_factor)} />
              <MetricCard label="Total Trades" value={String(result.total_trades ?? 0)} />
            </div>

            {/* Equity Curve */}
            <div className="glass-panel" style={{ padding: 20, marginBottom: 24 }}>
              <div style={{ color: "var(--text-secondary)", fontSize: 12, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.06em" }}>Equity Curve</div>
              <EquityCurve data={result.equity_curve ?? []} />
            </div>

            {/* Trade List */}
            {result.trades && result.trades.length > 0 && (
              <div className="glass-panel" style={{ padding: 20 }}>
                <div style={{ color: "var(--text-secondary)", fontSize: 12, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.06em" }}>Last {Math.min(result.trades.length, 20)} Trades</div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: 13 }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-default)", color: "var(--text-tertiary)", textAlign: "left" }}>
                        {["Entry", "Exit", "P&L", "P&L %", "Reason"].map(h => <th key={h} style={{ padding: "6px 12px", fontWeight: 500 }}>{h}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.slice(-20).reverse().map((t, i) => (
                        <tr key={i} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                          <td style={{ padding: "6px 12px", color: "var(--text-secondary)" }}>{new Date(t.entry).toLocaleString()}</td>
                          <td style={{ padding: "6px 12px", color: "var(--text-secondary)" }}>{new Date(t.exit).toLocaleString()}</td>
                          <td style={{ padding: "6px 12px", color: t.pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)", fontVariantNumeric: "tabular-nums" }}>{t.pnl >= 0 ? "+" : ""}{t.pnl.toFixed(2)}</td>
                          <td style={{ padding: "6px 12px", color: t.pnl_pct >= 0 ? "var(--accent-profit)" : "var(--accent-loss)", fontVariantNumeric: "tabular-nums" }}>{t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%</td>
                          <td style={{ padding: "6px 12px", color: "var(--text-tertiary)", fontSize: 11 }}>{t.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
