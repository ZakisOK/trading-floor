"use client";
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Portfolio { cash: number; positions_value: number; total: number; daily_pnl: number; trade_count?: number }
interface AgentInfo { id: string; name: string; role: string; color: string; status: string; elo: number }
interface Signal { agent?: string; direction: string; confidence: number; thesis: string; symbol?: string }
interface LogEntry { ts: string; msg: string; level: string }

function MiniEquity({ data }: { data: number[] }) {
  if (data.length < 2) return <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-tertiary)", fontSize: 13 }}>Run a backtest to see equity curve</div>;
  const W = 900, H = 180, pad = 6;
  const min = Math.min(...data), max = Math.max(...data), range = max - min || 1;
  const pts = data.map((v, i) => `${pad + (i / (data.length - 1)) * (W - pad * 2)},${H - pad - ((v - min) / range) * (H - pad * 2)}`).join(" ");
  const profit = data[data.length - 1] >= data[0];
  const color = profit ? "var(--accent-profit)" : "var(--accent-loss)";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: H, display: "block" }}>
      <defs><linearGradient id="mc-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity="0.2"/><stop offset="100%" stopColor={color} stopOpacity="0"/></linearGradient></defs>
      <polyline fill="url(#mc-fill)" stroke="none" points={`${pad},${H} ${pts} ${W - pad},${H}`} />
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={pts} strokeLinejoin="round" />
    </svg>
  );
}

const LOG_COLORS: Record<string, string> = {
  info: "var(--text-secondary)", warn: "var(--status-caution)",
  error: "var(--status-critical)", critical: "var(--accent-loss)",
};

export default function MissionControlPage() {
  const [portfolio, setPortfolio] = useState<Portfolio>({ cash: 10000, positions_value: 0, total: 10000, daily_pnl: 0 });
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [equityCurve] = useState<number[]>([]);
  const [mode, setMode] = useState("COMMANDER");
  const [health, setHealth] = useState<"ok" | "degraded" | "down">("ok");

  function addLog(msg: string, level = "info") {
    const ts = new Date().toLocaleTimeString();
    setLog(p => [{ ts, msg, level }, ...p].slice(0, 30));
  }

  const fetchAll = useCallback(async () => {
    try {
      const [port, agts, hlth] = await Promise.all([
        fetch(`${API}/api/orders/portfolio`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/agents`).then(r => r.json()).catch(() => []),
        fetch(`${API}/health`).then(r => r.json()).catch(() => null),
      ]);
      if (port) setPortfolio(port);
      if (agts?.length) setAgents(agts);
      if (hlth) { setMode(hlth.mode ?? "COMMANDER"); setHealth(hlth.status === "ok" ? "ok" : "degraded"); }
    } catch { setHealth("down"); }
  }, []);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 5000);
    addLog("Mission Control initialized", "info");
    return () => clearInterval(iv);
  }, [fetchAll]);

  // WebSocket for live events
  useEffect(() => {
    const ws = new WebSocket(`${API.replace("http", "ws")}/ws`);
    ws.onopen = () => addLog("WebSocket connected", "info");
    ws.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        if (d.signals) { setSignals(p => [...d.signals, ...p].slice(0, 20)); d.signals.forEach((s: Signal) => addLog(`${s.agent ?? "Agent"}: ${s.direction} ${s.symbol ?? ""} @ ${(s.confidence * 100).toFixed(0)}%`)); }
        if (d.type === "trade") addLog(`Trade: ${d.side} ${d.symbol} @ $${d.price}`, "warn");
        if (d.type === "kill_switch") addLog("KILL SWITCH ACTIVATED", "critical");
      } catch {}
    };
    ws.onclose = () => addLog("WebSocket disconnected", "warn");
    return () => ws.close();
  }, []);

  const mono = { fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" as const };
  const modeColor = mode === "COMMANDER" ? "var(--accent-primary)" : mode === "TRUSTED" ? "var(--status-standby)" : "var(--accent-loss)";
  const healthColor = health === "ok" ? "var(--status-normal)" : health === "degraded" ? "var(--status-caution)" : "var(--status-critical)";

  return (
    <div style={{ padding: "28px 32px", fontFamily: "var(--font-sans)", color: "var(--text-primary)", minHeight: "100vh", background: "var(--bg-void)" }}>
      {/* Top strip */}
      <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 24, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 2 }}>Portfolio Value</div>
          <div style={{ ...mono, fontSize: 32, fontWeight: 800, color: "var(--text-primary)" }}>${portfolio.total.toLocaleString("en", { minimumFractionDigits: 2 })}</div>
        </div>
        <div style={{ width: 1, height: 40, background: "var(--border-default)" }} />
        <div>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 2 }}>Daily P&L</div>
          <div style={{ ...mono, fontSize: 20, fontWeight: 700, color: portfolio.daily_pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)" }}>
            {portfolio.daily_pnl >= 0 ? "+" : ""}${portfolio.daily_pnl.toFixed(2)}
          </div>
        </div>
        <div style={{ width: 1, height: 40, background: "var(--border-default)" }} />
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: modeColor, boxShadow: `0 0 6px ${modeColor}` }} />
          <span style={{ fontSize: 13, fontWeight: 700, color: modeColor }}>{mode}</span>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: healthColor, boxShadow: `0 0 4px ${healthColor}` }} />
          <span style={{ fontSize: 12, color: "var(--text-tertiary)", textTransform: "capitalize" }}>System {health}</span>
        </div>
      </div>

      {/* Agent grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(165px, 1fr))", gap: 10, marginBottom: 20 }}>
        {agents.map(a => (
          <div key={a.id} className="glass-panel" style={{ padding: "12px 14px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <span style={{ fontWeight: 700, fontSize: 13, color: a.color }}>{a.name}</span>
              <div style={{ width: 7, height: 7, borderRadius: "50%", marginTop: 3, background: a.status === "active" ? "var(--status-normal)" : "var(--status-off)", boxShadow: a.status === "active" ? "0 0 4px var(--status-normal)" : "none" }} />
            </div>
            <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 6 }}>{a.role}</div>
            <div style={{ ...mono, fontSize: 14, color: "var(--text-primary)" }}>ELO {a.elo.toFixed(0)}</div>
          </div>
        ))}
      </div>

      {/* Equity curve */}
      <div className="glass-panel" style={{ padding: 20, marginBottom: 20 }}>
        <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 8 }}>Equity Curve</div>
        <MiniEquity data={equityCurve} />
      </div>

      {/* Signals + Log */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div className="glass-panel" style={{ padding: 20 }}>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 10 }}>Recent Signals</div>
          {signals.length === 0 ? <div style={{ color: "var(--text-tertiary)", fontSize: 13, textAlign: "center", padding: 12 }}>No signals yet</div> : (
            signals.slice(0, 10).map((s, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                <span style={{ fontSize: 11, padding: "1px 7px", borderRadius: 4, fontWeight: 700, background: s.direction === "LONG" ? "rgba(88,214,141,0.15)" : "rgba(248,81,73,0.15)", color: s.direction === "LONG" ? "var(--accent-profit)" : "var(--accent-loss)" }}>{s.direction}</span>
                <span style={{ fontSize: 12, color: "var(--text-secondary)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.thesis}</span>
                <span style={{ ...mono, fontSize: 11, color: "var(--text-tertiary)" }}>{(s.confidence * 100).toFixed(0)}%</span>
              </div>
            ))
          )}
        </div>
        <div className="glass-panel" style={{ padding: 20 }}>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 10 }}>Activity Log</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {log.slice(0, 20).map((e, i) => (
              <div key={i} style={{ display: "flex", gap: 8, fontSize: 12, ...mono }}>
                <span style={{ color: "var(--text-tertiary)", minWidth: 64 }}>{e.ts}</span>
                <span style={{ color: LOG_COLORS[e.level] ?? "var(--text-secondary)" }}>{e.msg}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
