"use client";
import { useState, useEffect, useCallback } from "react";
import { PageShell, SectionHeader } from "@/components/PageShell";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Mode = "COMMANDER" | "TRUSTED" | "YOLO";

interface Portfolio { cash: number; positions_value: number; total: number; daily_pnl: number; }
interface Position {
  symbol: string; side: string; quantity: number; avg_price: number;
  current_price?: number; unrealized_pnl?: number;
}
interface RiskMetrics {
  day_pnl?: number; total_pnl?: number; unrealized_pnl?: number; realized_pnl?: number;
  drawdown_pct?: number; total_exposure?: number; portfolio_value?: number; venue?: string;
}

const MODE_DESC: Record<Mode, string> = {
  COMMANDER: "Operator approves each trade. Max 2% risk / trade, 5% daily loss.",
  TRUSTED: "Auto-execute above 75% confidence. Max 3% risk / trade, 7% daily loss.",
  YOLO: "Full autonomous. Max 5% risk / trade, 12% daily loss. Type YOLO to confirm.",
};

function fmt(n: number | undefined | null, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function fmtSignedDollar(n: number | undefined | null) {
  if (n == null || isNaN(n)) return "—";
  const s = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${s}$${fmt(Math.abs(n))}`;
}

// Half-circle gauge, mock-styled
function GaugeArc({ pct, color }: { pct: number; color: string }) {
  const r = 70, cx = 90, cy = 90;
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
    <svg width="180" height="100" viewBox="0 0 180 100">
      <path d={`M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`} fill="none" stroke="var(--line-fine)" strokeWidth="6" strokeLinecap="round" />
      {pct > 0 && <path d={`M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${xE} ${yE}`} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round" />}
      <text x="90" y="88" textAnchor="middle" fill={color} fontSize="22" fontFamily="var(--font-mono)" fontWeight="400" letterSpacing="-.04em">
        {(pct * 100).toFixed(1)}%
      </text>
    </svg>
  );
}

export default function RiskPage() {
  const [portfolio, setPortfolio] = useState<Portfolio>({ cash: 10000, positions_value: 0, total: 10000, daily_pnl: 0 });
  const [risk, setRisk] = useState<RiskMetrics>({});
  const [positions, setPositions] = useState<Position[]>([]);
  const [mode, setMode] = useState<Mode>("TRUSTED");
  const [yoloInput, setYoloInput] = useState("");
  const [showYoloConfirm, setShowYoloConfirm] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [p, r, pos, cfg] = await Promise.all([
        fetch(`${API}/api/execution/portfolio`).then(r => r.json()),
        fetch(`${API}/api/execution/risk-metrics`).then(r => r.json()),
        fetch(`${API}/api/execution/positions`).then(r => r.json()),
        fetch(`${API}/api/settings`).then(r => r.json()),
      ]);
      setPortfolio(p);
      setRisk(r);
      setPositions(Array.isArray(pos) ? pos : pos?.positions ?? []);
      if (cfg?.system?.autonomy_mode) setMode(cfg.system.autonomy_mode);
    } catch { /* swallow */ }
  }, []);

  useEffect(() => { fetchAll(); const iv = setInterval(fetchAll, 5000); return () => clearInterval(iv); }, [fetchAll]);

  const maxDailyLoss = mode === "YOLO" ? 0.12 : mode === "TRUSTED" ? 0.07 : 0.05;
  const maxRisk = mode === "YOLO" ? 0.05 : mode === "TRUSTED" ? 0.03 : 0.02;
  const maxGross = mode === "YOLO" ? 3.0 : mode === "TRUSTED" ? 2.0 : 1.5;
  const dailyLossPct = portfolio.total > 0 ? Math.abs(Math.min(risk.day_pnl ?? portfolio.daily_pnl, 0)) / portfolio.total : 0;
  const lossGauge = dailyLossPct / maxDailyLoss;
  const grossPct = portfolio.total > 0 ? (risk.total_exposure ?? 0) / portfolio.total : 0;
  const grossGauge = grossPct / maxGross;
  const gaugeColor = lossGauge < 0.4 ? "var(--accent-profit)" : lossGauge < 0.8 ? "var(--status-serious)" : "var(--accent-loss)";
  const grossColor = grossGauge < 0.6 ? "var(--accent-profit)" : grossGauge < 0.9 ? "var(--status-serious)" : "var(--accent-loss)";

  async function handleModeChange(m: Mode) {
    if (m === "YOLO" && mode !== "YOLO") { setShowYoloConfirm(true); return; }
    setMode(m); setShowYoloConfirm(false);
    try {
      await fetch(`${API}/api/settings`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system: { autonomy_mode: m } }),
      });
    } catch { /* swallow */ }
  }
  function confirmYolo() {
    if (yoloInput === "YOLO") { handleModeChange("YOLO"); setShowYoloConfirm(false); setYoloInput(""); }
  }

  return (
    <PageShell
      crumbs={["The Firm", "Intelligence", "Risk"]}
      status={<>
        <div className="st"><span className={`d ${dailyLossPct >= maxDailyLoss * 0.8 ? "warn" : "ok"}`} /> mode {mode}</div>
        <div className="st">venue {risk.venue ?? "sim"}</div>
      </>}
    >
      {/* Mode banner */}
      <div className="mode-row">
        <span className="flag">SIM · {mode}</span>
        <div className="msg">{MODE_DESC[mode]}</div>
        <div className="tools">
          <div className="seg">
            {(["COMMANDER", "TRUSTED", "YOLO"] as Mode[]).map(m => (
              <button key={m} className={mode === m ? "on" : ""} onClick={() => handleModeChange(m)}>
                {m.charAt(0) + m.slice(1).toLowerCase()}
              </button>
            ))}
          </div>
        </div>
      </div>
      {showYoloConfirm && (
        <div className="card card-pad" style={{ borderColor: "var(--accent-loss)" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: ".14em", textTransform: "uppercase", color: "var(--accent-loss)", marginBottom: 8 }}>
            Confirm YOLO mode
          </div>
          <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 10 }}>
            Type <b>YOLO</b> below. Caps relax to 5% / 12% / 300% gross. No undo.
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={yoloInput}
              onChange={e => setYoloInput(e.target.value)}
              placeholder="Type YOLO"
              style={{ flex: 1, background: "var(--bg-surface-2)", border: "1px solid var(--accent-loss)", borderRadius: 6, color: "var(--text-primary)", padding: "8px 12px", fontFamily: "var(--font-mono)" }}
            />
            <button className="btn-ghost" onClick={confirmYolo} style={{ color: "var(--accent-loss)", borderColor: "var(--accent-loss)" }}>Confirm</button>
            <button className="btn-ghost" onClick={() => { setShowYoloConfirm(false); setYoloInput(""); }}>Cancel</button>
          </div>
        </div>
      )}

      {/* Briefing */}
      <div className="briefing">
        <div className="left">
          <div className="eyebrow"><span className="num">01</span><span>·</span><span>Risk snapshot</span>
            <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>Refreshed every 5s</span>
          </div>
          <p className="headline">
            Today's drawdown is <span className={lossGauge >= 0.8 ? "dn" : "up"}>{fmt(dailyLossPct * 100, 2)}%</span> of the
            <b> {fmt(maxDailyLoss * 100, 0)}%</b> {mode.toLowerCase()}-mode cap.
            Gross exposure sits at <b>{fmt(grossPct * 100, 0)}%</b> of book.
          </p>
          <div className="figure-stack">
            <span className="lbl">Portfolio</span>
            <span className="big">
              ${fmt(Math.floor(portfolio.total), 0)}
              <span className="cents">.{String(Math.floor((portfolio.total % 1) * 100)).padStart(2, "0")}</span>
            </span>
            <span className="delta">
              <span className={`v ${(risk.day_pnl ?? 0) >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(risk.day_pnl)}</span><span>today</span>
              <span className="pip" />
              <span className={`v ${(risk.total_pnl ?? 0) >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(risk.total_pnl)}</span><span>since inception</span>
            </span>
          </div>
        </div>
        <div className="right">
          <div className="cell"><div className="k"><span>Cash</span><span className="n">02</span></div><div className="v">${fmt(portfolio.cash, 0)}</div><div className="sub"><span>Available</span></div></div>
          <div className="cell"><div className="k"><span>Exposure</span><span className="n">03</span></div><div className="v">${fmt(risk.total_exposure, 0)}</div><div className="sub"><span>{fmt(grossPct * 100, 0)}% of book</span><span className="bar-mini"><span className="fill" style={{ width: `${Math.min(100, grossPct * 100)}%` }} /></span></div></div>
          <div className="cell"><div className="k"><span>Unrealized</span><span className="n">04</span></div><div className={`v ${(risk.unrealized_pnl ?? 0) >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(risk.unrealized_pnl)}</div><div className="sub"><span>{positions.length} open</span></div></div>
          <div className="cell"><div className="k"><span>Realized</span><span className="n">05</span></div><div className={`v ${(risk.realized_pnl ?? 0) >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(risk.realized_pnl)}</div><div className="sub"><span>Since inception</span></div></div>
        </div>
      </div>

      {/* Gauges */}
      <section>
        <SectionHeader n="02" label="Gauges" title="Cap utilization" sub={`${mode} caps: ${fmt(maxRisk * 100, 0)}% / trade · ${fmt(maxDailyLoss * 100, 0)}% daily · ${fmt(maxGross * 100, 0)}% gross`} />
        <div className="perf">
          <div className="card card-pad" style={{ textAlign: "center" }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: ".2em", textTransform: "uppercase", color: "var(--text-tertiary)", marginBottom: 8 }}>
              Daily loss vs cap
            </div>
            <GaugeArc pct={lossGauge} color={gaugeColor} />
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
              {fmt(dailyLossPct * 100, 2)}% of {fmt(maxDailyLoss * 100, 0)}% limit used
            </div>
          </div>
          <div className="card card-pad" style={{ textAlign: "center" }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: ".2em", textTransform: "uppercase", color: "var(--text-tertiary)", marginBottom: 8 }}>
              Gross exposure vs cap
            </div>
            <GaugeArc pct={grossGauge} color={grossColor} />
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
              {fmt(grossPct * 100, 0)}% of {fmt(maxGross * 100, 0)}% limit used
            </div>
          </div>
        </div>
      </section>

      {/* Positions */}
      <section>
        <SectionHeader n="03" label="Book" title="Open positions" sub={`${positions.length} position${positions.length !== 1 ? "s" : ""}`} />
        <div className="card positions-card">
          <table className="positions">
            <thead>
              <tr>
                <th style={{ width: 28 }}>#</th>
                <th>Symbol</th>
                <th>Side</th>
                <th className="r">Qty</th>
                <th className="r">Entry</th>
                <th className="r">Mark</th>
                <th className="r">Unreal P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign: "center", padding: "28px 14px", color: "var(--text-tertiary)" }}>No open positions</td></tr>
              )}
              {positions.map((p, i) => {
                const upnl = p.unrealized_pnl ?? 0;
                const isLong = p.side === "LONG";
                return (
                  <tr key={p.symbol + i}>
                    <td style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 10.5 }}>{String(i + 1).padStart(2, "0")}</td>
                    <td className="sym">{p.symbol}</td>
                    <td className={`side ${isLong ? "long" : "short"}`}><span>{p.side}</span></td>
                    <td className="r mono">{fmt(p.quantity, 4)}</td>
                    <td className="r mono">${fmt(p.avg_price, 4)}</td>
                    <td className="r mono strong">${fmt(p.current_price, 4)}</td>
                    <td className={`r pnl ${upnl >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(upnl)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </PageShell>
  );
}
