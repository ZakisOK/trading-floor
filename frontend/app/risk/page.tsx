"use client";
import { useState, useEffect, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Mode = "COMMANDER" | "TRUSTED" | "YOLO";

interface Portfolio {
  cash: number; positions_value: number; total: number; daily_pnl: number;
}
interface Position {
  symbol: string; side: string; quantity: number; avg_price: number;
  current_price?: number; unrealized_pnl?: number;
}

const MODE_COLOR: Record<Mode, string> = {
  COMMANDER: "var(--accent-primary)",
  TRUSTED: "var(--status-standby)",
  YOLO: "var(--accent-loss)",
};
const MODE_DESC: Record<Mode, string> = {
  COMMANDER: "All trades require your approval",
  TRUSTED: "Auto-execute above 75% confidence",
  YOLO: "Full autonomous — paper only",
};

function GaugeArc({ pct, color }: { pct: number; color: string }) {
  const r = 60, cx = 80, cy = 80;
  const startAngle = -180, sweep = 180;
  const angle = startAngle + sweep * Math.min(pct, 1);
  const toRad = (d: number) => (d * Math.PI) / 180;
  const x1 = cx + r * Math.cos(toRad(startAngle));
  const y1 = cy + r * Math.sin(toRad(startAngle));
  const x2 = cx + r * Math.cos(toRad(-1));
  const y2 = cy + r * Math.sin(toRad(-1));
  const xE = cx + r * Math.cos(toRad(angle));
  const yE = cy + r * Math.sin(toRad(angle));
  const largeArc = sweep * pct > 180 ? 1 : 0;
  return (
    <svg width="160" height="90" viewBox="0 0 160 90">
      <path d={`M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`} fill="none" stroke="var(--bg-surface-3)" strokeWidth="10" strokeLinecap="round" />
      {pct > 0 && <path d={`M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${xE} ${yE}`} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" />}
      <text x="80" y="76" textAnchor="middle" fill={color} fontSize="18" fontFamily="var(--font-mono)" fontWeight="700">{(pct * 100).toFixed(1)}%</text>
    </svg>
  );
}

export default function RiskPage() {
  const [portfolio, setPortfolio] = useState<Portfolio>({ cash: 10000, positions_value: 0, total: 10000, daily_pnl: 0 });
  const [positions, setPositions] = useState<Position[]>([]);
  const [mode, setMode] = useState<Mode>("COMMANDER");
  const [yoloInput, setYoloInput] = useState("");
  const [showYoloConfirm, setShowYoloConfirm] = useState(false);

  const fetchPortfolio = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/orders/portfolio`);
      setPortfolio(await r.json());
      const p = await fetch(`${API}/api/orders/positions`);
      setPositions(await p.json());
    } catch {}
  }, []);

  useEffect(() => { fetchPortfolio(); const iv = setInterval(fetchPortfolio, 5000); return () => clearInterval(iv); }, [fetchPortfolio]);

  const maxDailyLoss = 0.05;
  const dailyLossPct = portfolio.total > 0 ? Math.abs(Math.min(portfolio.daily_pnl, 0)) / portfolio.total : 0;
  const gaugeColor = dailyLossPct < 0.02 ? "var(--accent-profit)" : dailyLossPct < 0.04 ? "var(--status-caution)" : "var(--accent-loss)";

  function handleModeChange(m: Mode) {
    if (m === "YOLO") { setShowYoloConfirm(true); return; }
    setMode(m); setShowYoloConfirm(false);
  }
  function confirmYolo() {
    if (yoloInput === "YOLO") { setMode("YOLO"); setShowYoloConfirm(false); setYoloInput(""); }
  }

  const s = { fontFamily: "var(--font-sans)", minHeight: "100vh", background: "var(--bg-void)", color: "var(--text-primary)", padding: "32px" };
  const card = { background: "var(--bg-surface-1)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: "16px 20px" };
  const mono = { fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" as const };

  return (
    <div style={s}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 4 }}>Risk Dashboard</h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: 28 }}>Portfolio exposure and operating mode</p>

        {/* Portfolio metrics */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 24 }}>
          {[
            { label: "Total Value", val: `$${portfolio.total.toLocaleString("en", {minimumFractionDigits:2, maximumFractionDigits:2})}`, color: "var(--text-primary)" },
            { label: "Cash", val: `$${portfolio.cash.toLocaleString("en", {minimumFractionDigits:2, maximumFractionDigits:2})}`, color: "var(--text-primary)" },
            { label: "Positions", val: `$${portfolio.positions_value.toLocaleString("en", {minimumFractionDigits:2, maximumFractionDigits:2})}`, color: "var(--text-secondary)" },
            { label: "Daily P&L", val: `${portfolio.daily_pnl >= 0 ? "+" : ""}$${portfolio.daily_pnl.toFixed(2)}`, color: portfolio.daily_pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)" },
          ].map(m => (
            <div key={m.label} style={card}>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 6 }}>{m.label}</div>
              <div style={{ ...mono, fontSize: 20, fontWeight: 700, color: m.color }}>{m.val}</div>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 24 }}>
          {/* Risk gauge */}
          <div className="glass-panel" style={{ padding: 20, textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 8 }}>Daily Loss vs Limit (5%)</div>
            <GaugeArc pct={dailyLossPct / maxDailyLoss} color={gaugeColor} />
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
              {(dailyLossPct * 100).toFixed(2)}% of {(maxDailyLoss * 100).toFixed(0)}% limit used
            </div>
          </div>

          {/* Mode selector */}
          <div className="glass-panel" style={{ padding: 20 }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 12 }}>Operating Mode</div>
            <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
              {(["COMMANDER", "TRUSTED", "YOLO"] as Mode[]).map(m => (
                <button key={m} onClick={() => handleModeChange(m)} style={{
                  flex: 1, padding: "8px 0", borderRadius: "var(--radius-sm)", fontSize: 12, fontWeight: 700,
                  cursor: "pointer", transition: "all 0.2s",
                  background: mode === m ? MODE_COLOR[m] : "var(--bg-surface-2)",
                  color: mode === m ? "#fff" : "var(--text-secondary)",
                  border: `1px solid ${mode === m ? MODE_COLOR[m] : "var(--border-default)"}`,
                }}>{m}</button>
              ))}
            </div>
            <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>{MODE_DESC[mode]}</div>
            {showYoloConfirm && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 12, color: "var(--accent-loss)", marginBottom: 6 }}>Type YOLO to confirm autonomous mode</div>
                <div style={{ display: "flex", gap: 8 }}>
                  <input value={yoloInput} onChange={e => setYoloInput(e.target.value)} placeholder="Type YOLO"
                    style={{ flex: 1, background: "var(--bg-surface-2)", border: "1px solid var(--accent-loss)", borderRadius: "var(--radius-sm)", color: "var(--text-primary)", padding: "6px 10px", fontSize: 13 }} />
                  <button onClick={confirmYolo} style={{ background: "var(--accent-loss)", color: "#fff", border: "none", borderRadius: "var(--radius-sm)", padding: "6px 14px", cursor: "pointer", fontSize: 13 }}>Confirm</button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Positions table */}
        <div className="glass-panel" style={{ padding: 20 }}>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 12 }}>Open Positions</div>
          {positions.length === 0 ? (
            <div style={{ color: "var(--text-tertiary)", fontSize: 13, textAlign: "center", padding: "20px 0" }}>No open positions</div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", ...mono, fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border-default)", color: "var(--text-tertiary)" }}>
                  {["Symbol","Side","Qty","Avg Entry","Current","Unrealized P&L"].map(h =>
                    <th key={h} style={{ padding: "6px 12px", textAlign: "left", fontWeight: 500 }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {positions.map((p, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                    <td style={{ padding: "8px 12px" }}>{p.symbol}</td>
                    <td style={{ padding: "8px 12px", color: p.side === "LONG" ? "var(--accent-profit)" : "var(--accent-loss)" }}>{p.side}</td>
                    <td style={{ padding: "8px 12px" }}>{p.quantity?.toFixed(4)}</td>
                    <td style={{ padding: "8px 12px" }}>${p.avg_price?.toFixed(2)}</td>
                    <td style={{ padding: "8px 12px" }}>{p.current_price ? `$${p.current_price.toFixed(2)}` : "—"}</td>
                    <td style={{ padding: "8px 12px", color: (p.unrealized_pnl ?? 0) >= 0 ? "var(--accent-profit)" : "var(--accent-loss)" }}>
                      {p.unrealized_pnl != null ? `${p.unrealized_pnl >= 0 ? "+" : ""}$${p.unrealized_pnl.toFixed(2)}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
