"use client";
import { useState, useEffect, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Point {
  ts: string;
  portfolio_value: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  day_pnl?: number;
  open_positions: number;
}

interface DailyPoint {
  date: string;
  start_portfolio: number;
  end_portfolio: number;
  day_pnl: number;
  total_pnl: number;
}

function fmt$(n: number, decimals = 2) {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "+";
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(decimals)}`;
}

export function RunningPnL() {
  const [points, setPoints] = useState<Point[]>([]);
  const [daily, setDaily] = useState<DailyPoint[]>([]);
  const [range, setRange] = useState<"1h" | "4h" | "12h" | "daily">("1h");

  const fetchData = useCallback(async () => {
    try {
      const limit = range === "1h" ? 120 : range === "4h" ? 480 : range === "12h" ? 1440 : 120;
      const [hist, day] = await Promise.all([
        fetch(`${API}/api/execution/pnl-history?limit=${limit}`).then((r) => r.json()),
        fetch(`${API}/api/execution/pnl-daily?days=30`).then((r) => r.json()),
      ]);
      setPoints(hist.points || []);
      setDaily(day.days || []);
    } catch {}
  }, [range]);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 10_000);
    return () => clearInterval(iv);
  }, [fetchData]);

  const latest = points[points.length - 1];

  return (
    <div className="glass-panel" style={{ padding: "18px 20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            Running P&L
          </div>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 2 }}>
            Starting capital: $10,000. Total = portfolio value now − $10,000. Updated every 30s.
          </div>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {(["1h", "4h", "12h", "daily"] as const).map((r) => (
            <button key={r} onClick={() => setRange(r)} style={{
              padding: "3px 9px", fontSize: 10, fontWeight: 600, borderRadius: 3,
              background: r === range ? "var(--accent-primary)" : "transparent",
              color: r === range ? "#fff" : "var(--text-tertiary)",
              border: `1px solid ${r === range ? "var(--accent-primary)" : "var(--border-default)"}`,
              cursor: "pointer",
            }}>{r}</button>
          ))}
        </div>
      </div>

      {latest ? (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10, marginBottom: 14 }}>
            <Metric
              label="Today"
              value={fmt$(latest.day_pnl ?? 0)}
              color={(latest.day_pnl ?? 0) >= 0 ? "var(--accent-profit)" : "var(--accent-loss)"}
            />
            <Metric
              label="Unrealized"
              value={fmt$(latest.unrealized_pnl)}
              color={latest.unrealized_pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)"}
            />
            <Metric
              label="Realized"
              value={fmt$(latest.realized_pnl)}
              color={latest.realized_pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)"}
              sub="commissions + closed"
            />
            <Metric
              label="Total"
              value={fmt$(latest.total_pnl)}
              sub={`since $10,000`}
              color={latest.total_pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)"}
            />
          </div>

          {range === "daily" ? <DailyBars days={daily} /> : <PnlChart points={points} />}

          <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 8, display: "flex", justifyContent: "space-between" }}>
            <span>Portfolio: ${latest.portfolio_value.toFixed(2)}</span>
            <span>{latest.open_positions} open · {range === "daily" ? `${daily.length} days` : `${points.length} snapshots`}</span>
          </div>
        </>
      ) : (
        <div style={{ fontSize: 11, color: "var(--text-tertiary)", padding: "20px 0", textAlign: "center" }}>
          No snapshots yet — risk_monitor writes one every 30s.
        </div>
      )}
    </div>
  );
}

function DailyBars({ days }: { days: DailyPoint[] }) {
  if (days.length === 0) {
    return <div style={{ height: 90, color: "var(--text-tertiary)", fontSize: 11, display: "flex", alignItems: "center", justifyContent: "center" }}>
      No daily data yet.
    </div>;
  }
  const W = 600, H = 110, pad = 20;
  const max = Math.max(1, ...days.map((d) => Math.abs(d.day_pnl)));
  const barW = (W - 2 * pad) / days.length - 4;
  const mid = H / 2;
  return (
    <div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: "block" }}>
        <line x1={pad} x2={W - pad} y1={mid} y2={mid} stroke="var(--border-subtle)" strokeDasharray="2 4" strokeWidth="0.5" />
        {days.map((d, i) => {
          const x = pad + i * (barW + 4);
          const h = Math.abs(d.day_pnl) / max * (mid - 12);
          const color = d.day_pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)";
          const y = d.day_pnl >= 0 ? mid - h : mid;
          return (
            <g key={d.date}>
              <rect x={x} y={y} width={barW} height={Math.max(1, h)} fill={color} opacity="0.7" />
              <text x={x + barW / 2} y={H - 4} fill="var(--text-tertiary)" fontSize="8" textAnchor="middle">
                {d.date.slice(5)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Metric({ label, value, color, sub }: { label: string; value: string; color: string; sub?: string }) {
  return (
    <div>
      <div style={{ fontSize: 9, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color, fontFamily: "var(--font-mono, monospace)" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 9, color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>{sub}</div>}
    </div>
  );
}

function PnlChart({ points }: { points: Point[] }) {
  if (points.length < 2) {
    return <div style={{ height: 90, color: "var(--text-tertiary)", fontSize: 11, display: "flex", alignItems: "center", justifyContent: "center" }}>
      Building history… (need at least 2 snapshots, ~1 minute)
    </div>;
  }
  const W = 600, H = 90, pad = 4;
  const totals = points.map((p) => p.total_pnl);
  const min = Math.min(0, ...totals);
  const max = Math.max(0, ...totals);
  const range = max - min || 1;
  const yScale = (v: number) => H - pad - ((v - min) / range) * (H - 2 * pad);
  const xScale = (i: number) => pad + (i / (points.length - 1)) * (W - 2 * pad);

  const linePts = points.map((p, i) => `${xScale(i)},${yScale(p.total_pnl)}`).join(" ");
  const fillPts = `${xScale(0)},${yScale(0)} ${linePts} ${xScale(points.length - 1)},${yScale(0)}`;
  const endsPositive = totals[totals.length - 1] >= totals[0];
  const color = endsPositive ? "var(--accent-profit)" : "var(--accent-loss)";

  // Baseline at 0
  const zeroY = yScale(0);

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id="pnl-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <line x1={pad} x2={W - pad} y1={zeroY} y2={zeroY} stroke="var(--border-subtle)" strokeDasharray="2 4" strokeWidth="0.5" />
      <polygon points={fillPts} fill="url(#pnl-fill)" />
      <polyline points={linePts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}
