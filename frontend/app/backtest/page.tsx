"use client";
import { useState, useEffect, useRef } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface WindowResult {
  window_index: number;
  in_sample_sharpe: number;
  out_of_sample_sharpe: number;
  in_sample_bars: number;
  out_of_sample_bars: number;
  in_sample_trades: number;
  out_of_sample_trades: number;
  in_sample_start?: string;
  out_of_sample_end?: string;
}

interface WalkForwardResult {
  symbol: string;
  strategy_name: string;
  n_windows: number;
  in_sample_sharpe: number;
  out_of_sample_sharpe: number;
  degradation_ratio: number;
  window_results: WindowResult[];
  is_robust: boolean;
  total_bars: number;
}

interface ValidityFlags {
  risk_level: string;
  is_trustworthy: boolean;
  sharpe_confidence_penalty_pct: number;
  adjusted_sharpe: number;
  warnings: string[];
  labels: string[];
}

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
  memorization_risk?: string;
  validity_flags?: ValidityFlags;
  walk_forward?: WalkForwardResult;
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

function MemorizationRiskBadge({ risk, flags }: { risk: string; flags?: ValidityFlags }) {
  const colors: Record<string, { bg: string; border: string; text: string; dot: string }> = {
    HIGH:    { bg: "rgba(248,81,73,0.12)",  border: "rgba(248,81,73,0.4)",  text: "#f85149", dot: "#f85149" },
    MEDIUM:  { bg: "rgba(210,153,34,0.12)", border: "rgba(210,153,34,0.4)", text: "#d9a428", dot: "#d9a428" },
    LOW:     { bg: "rgba(63,185,80,0.12)",  border: "rgba(63,185,80,0.4)",  text: "#3fb950", dot: "#3fb950" },
    UNKNOWN: { bg: "rgba(139,148,158,0.12)",border: "rgba(139,148,158,0.3)",text: "#8b949e", dot: "#8b949e" },
  };
  const c = colors[risk] ?? colors.UNKNOWN;
  const label = risk === "UNKNOWN" ? "Assessing..." : `${risk} memorization risk`;
  const adjSharpe = flags?.adjusted_sharpe;
  const penalty = flags?.sharpe_confidence_penalty_pct ?? 0;

  return (
    <div style={{ background: c.bg, border: `1px solid ${c.border}`, borderRadius: "var(--radius-md)", padding: "14px 18px", marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: flags?.warnings?.length ? 10 : 0 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: c.dot, flexShrink: 0, display: "inline-block" }} />
        <span style={{ color: c.text, fontWeight: 700, fontSize: 13, textTransform: "uppercase", letterSpacing: "0.06em" }}>
          {label}
        </span>
        {penalty > 0 && (
          <span style={{ marginLeft: "auto", color: "var(--text-secondary)", fontSize: 12, fontFamily: "var(--font-mono)" }}>
            Adj. Sharpe: {fmt(adjSharpe)} <span style={{ opacity: 0.6 }}>(-{penalty}% confidence)</span>
          </span>
        )}
      </div>
      {flags?.warnings?.map((w, i) => (
        <div key={i} style={{ color: "var(--text-secondary)", fontSize: 12, marginTop: 4, paddingLeft: 16 }}>⚠ {w}</div>
      ))}
    </div>
  );
}

function WalkForwardChart({ wf }: { wf: WalkForwardResult }) {
  const windows = wf.window_results;
  if (!windows || windows.length === 0) return null;
  const allValues = windows.flatMap(w => [w.in_sample_sharpe, w.out_of_sample_sharpe]);
  const minV = Math.min(...allValues, 0);
  const maxV = Math.max(...allValues, 0.1);
  const range = maxV - minV || 1;
  const W = 600, H = 140, padL = 40, padR = 16, padT = 12, padB = 28;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;
  const n = windows.length;
  const barWidth = Math.floor(chartW / (n * 2 + 1));
  const gap = Math.floor(barWidth * 0.3);
  const zeroY = padT + chartH - ((0 - minV) / range) * chartH;

  const toY = (v: number) => padT + chartH - ((v - minV) / range) * chartH;
  const toH = (v: number) => Math.abs(toY(v) - zeroY);

  const robustColor = wf.is_robust ? "#3fb950" : "#f85149";

  return (
    <div style={{ background: "var(--bg-surface-1)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: "20px", marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ color: "var(--text-secondary)", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.06em" }}>Walk-Forward Validation</div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 12 }}>
          <span style={{ color: "var(--text-secondary)" }}>IS Sharpe <span style={{ color: "#58a6ff" }}>■</span></span>
          <span style={{ color: "var(--text-secondary)" }}>OOS Sharpe <span style={{ color: "#3fb950" }}>■</span></span>
          <span style={{ fontWeight: 700, color: robustColor, fontSize: 11, textTransform: "uppercase" }}>
            {wf.is_robust ? "✓ ROBUST" : "✗ OVERFIT"}
          </span>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 12 }}>
        {[
          { label: "Avg IS Sharpe",  value: fmt(wf.in_sample_sharpe) },
          { label: "Avg OOS Sharpe", value: fmt(wf.out_of_sample_sharpe), color: wf.out_of_sample_sharpe > 0 ? "#3fb950" : "#f85149" },
          { label: "Degradation",    value: isFinite(wf.degradation_ratio) ? `${fmt(wf.degradation_ratio)}x` : "∞x",
            color: wf.degradation_ratio < 2 ? "#3fb950" : wf.degradation_ratio < 3 ? "#d9a428" : "#f85149" },
        ].map(m => (
          <div key={m.label} style={{ textAlign: "center" }}>
            <div style={{ color: "var(--text-tertiary)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em" }}>{m.label}</div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 18, fontWeight: 600, color: m.color ?? "var(--text-primary)" }}>{m.value}</div>
          </div>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: H }}>
        {/* Zero line */}
        <line x1={padL} y1={zeroY} x2={W - padR} y2={zeroY} stroke="var(--border-default)" strokeWidth="1" strokeDasharray="3,3" />
        {/* Y axis label 0 */}
        <text x={padL - 4} y={zeroY + 4} textAnchor="end" fill="var(--text-tertiary)" fontSize="9">0</text>
        {windows.map((w, i) => {
          const groupX = padL + i * (chartW / n) + chartW / (n * 2) - barWidth - gap / 2;
          const isY = toY(w.in_sample_sharpe);
          const oosY = toY(w.out_of_sample_sharpe);
          const isH = toH(w.in_sample_sharpe);
          const oosH = toH(w.out_of_sample_sharpe);
          const oosColor = w.out_of_sample_sharpe >= 0 ? "#3fb950" : "#f85149";
          return (
            <g key={i}>
              <rect x={groupX} y={w.in_sample_sharpe >= 0 ? isY : zeroY} width={barWidth} height={isH} fill="#58a6ff" opacity={0.75} rx="2" />
              <rect x={groupX + barWidth + gap} y={w.out_of_sample_sharpe >= 0 ? oosY : zeroY} width={barWidth} height={oosH} fill={oosColor} opacity={0.8} rx="2" />
              <text x={groupX + barWidth + gap / 2} y={H - 4} textAnchor="middle" fill="var(--text-tertiary)" fontSize="9">W{w.window_index}</text>
            </g>
          );
        })}
      </svg>
      <div style={{ color: "var(--text-tertiary)", fontSize: 11, marginTop: 8 }}>
        Degradation threshold: &lt;2.0x = robust, 2–3x = caution, &gt;3.0x = overfit. Current: {isFinite(wf.degradation_ratio) ? fmt(wf.degradation_ratio) + "x" : "∞"}.
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
  const [exchange, setExchange] = useState("coinbase");
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
                {["coinbase","kraken"].map(s => <option key={s}>{s}</option>)}
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
            <div style={{ fontSize: 32, marginBottom: 12, animation: "spin 1s linear infinite", display: "inline-block" }}>⏳</div>
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
            {/* Memorization Risk Badge — always show when results are present */}
            <MemorizationRiskBadge
              risk={result.memorization_risk ?? "UNKNOWN"}
              flags={result.validity_flags}
            />

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, marginBottom: 24 }}>
              <MetricCard label="Total Return" value={fmt(result.total_return_pct)} suffix="%" color={(result.total_return_pct ?? 0) >= 0 ? "var(--accent-profit)" : "var(--accent-loss)"} />
              <MetricCard label="CAGR" value={fmt(result.cagr)} suffix="%" />
              <MetricCard label="Sharpe (raw)" value={fmt(result.sharpe_ratio)} />
              <MetricCard
                label="Sharpe (adjusted)"
                value={fmt(result.validity_flags?.adjusted_sharpe ?? result.sharpe_ratio)}
                color={result.memorization_risk === "HIGH" ? "var(--accent-loss)" : result.memorization_risk === "MEDIUM" ? "#d9a428" : undefined}
              />
              <MetricCard label="Sortino Ratio" value={fmt(result.sortino_ratio)} />
              <MetricCard label="Max Drawdown" value={fmt(result.max_drawdown_pct)} suffix="%" color="var(--accent-loss)" />
              <MetricCard label="Win Rate" value={fmt(result.win_rate)} suffix="%" color={(result.win_rate ?? 0) >= 50 ? "var(--accent-profit)" : "var(--accent-loss)"} />
              <MetricCard label="Profit Factor" value={fmt(result.profit_factor)} />
              <MetricCard label="Total Trades" value={String(result.total_trades ?? 0)} />
            </div>

            {/* Walk-Forward Validation Chart */}
            {result.walk_forward && <WalkForwardChart wf={result.walk_forward} />}

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
