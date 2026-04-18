"use client";
import { useState, useEffect, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Agent {
  id: string; name: string; role: string; color: string;
  status: string; elo: number; current_task: string | null; last_heartbeat: string | null;
}
interface Signal {
  symbol: string; direction: string; confidence: string; thesis: string; ts: string;
}

const STATUS_COLOR: Record<string, string> = {
  active: "var(--status-normal)", idle: "var(--status-off)",
  error: "var(--status-critical)", running: "var(--status-standby)",
};

function AgentCard({ agent, onRun }: { agent: Agent; onRun: (id: string) => void }) {
  return (
    <div className="glass-panel" style={{ padding: 16, cursor: "pointer", transition: "border-color 0.2s", position: "relative" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, color: agent.color }}>{agent.name}</div>
          <div style={{ color: "var(--text-tertiary)", fontSize: 11, marginTop: 2 }}>{agent.role}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{
            width: 8, height: 8, borderRadius: "50%",
            background: STATUS_COLOR[agent.status] ?? STATUS_COLOR.idle,
            boxShadow: agent.status === "active" ? `0 0 6px ${STATUS_COLOR.active}` : "none",
          }} />
          <span style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "capitalize" }}>{agent.status}</span>
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 2 }}>ELO</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 16, fontVariantNumeric: "tabular-nums", color: "var(--text-primary)" }}>
            {agent.elo.toFixed(0)}
          </div>
        </div>
        <button onClick={() => onRun(agent.id)} style={{
          background: "var(--bg-surface-3)", border: "1px solid var(--border-default)",
          borderRadius: "var(--radius-sm)", color: "var(--text-secondary)",
          padding: "5px 12px", fontSize: 12, cursor: "pointer",
        }}>Run</button>
      </div>
      {agent.current_task && (
        <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-tertiary)", borderTop: "1px solid var(--border-subtle)", paddingTop: 8 }}>
          {agent.current_task}
        </div>
      )}
    </div>
  );
}

function ConsensusMeter({ signals }: { signals: Signal[] }) {
  const longs = signals.filter(s => s.direction === "LONG").length;
  const shorts = signals.filter(s => s.direction === "SHORT").length;
  const total = signals.length || 1;
  const bullPct = (longs / total) * 100;
  const bearPct = (shorts / total) * 100;
  return (
    <div style={{ padding: "12px 20px", background: "var(--bg-surface-1)", borderRadius: "var(--radius-md)", border: "1px solid var(--border-default)" }}>
      <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Signal Consensus</div>
      <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", background: "var(--bg-surface-3)" }}>
        <div style={{ width: `${bullPct}%`, background: "var(--accent-profit)", transition: "width 0.5s" }} />
        <div style={{ width: `${bearPct}%`, background: "var(--accent-loss)", transition: "width 0.5s" }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 11, fontFamily: "var(--font-mono)" }}>
        <span style={{ color: "var(--accent-profit)" }}>▲ {longs} LONG</span>
        <span style={{ color: "var(--text-tertiary)" }}>{signals.length} signals</span>
        <span style={{ color: "var(--accent-loss)" }}>▼ {shorts} SHORT</span>
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [cycleResult, setCycleResult] = useState<string | null>(null);

  const fetchAgents = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/agents`);
      setAgents(await r.json());
    } catch {}
  }, []);

  useEffect(() => {
    fetchAgents();
    const iv = setInterval(fetchAgents, 5000);
    return () => clearInterval(iv);
  }, [fetchAgents]);

  async function runAgent(agentId: string) {
    setRunning(agentId);
    try {
      const r = await fetch(`${API}/api/agents/${agentId}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: "BTC/USDT", close: 65000 }),
      });
      const data = await r.json();
      const newSignals = data.signals ?? [];
      setSignals(prev => [...newSignals, ...prev].slice(0, 30));
    } catch {}
    setRunning(null);
  }

  async function runFullCycle() {
    setRunning("cycle");
    setCycleResult(null);
    try {
      const r = await fetch(`${API}/api/agents/cycle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: "BTC/USDT", close: 65000 }),
      });
      const data = await r.json();
      setSignals(prev => [...(data.signals ?? []), ...prev].slice(0, 30));
      setCycleResult(`${data.final_decision ?? "NEUTRAL"} — confidence ${(data.confidence * 100).toFixed(0)}%`);
    } catch {}
    setRunning(null);
  }

  const baseStyle = { minHeight: "100vh", background: "var(--bg-void)", color: "var(--text-primary)", padding: "32px", fontFamily: "var(--font-sans)" };
  return (
    <div style={baseStyle}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 32 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 4 }}>Agent Floor</h1>
            <p style={{ color: "var(--text-secondary)", marginBottom: 8 }}>10 autonomous trading agents — live status + ELO</p>
            <p style={{ color: "var(--text-tertiary)", fontSize: 12, maxWidth: 700, margin: 0 }}>
              The paper-trading loop already fires cycles automatically (XRP every 2 min, others every 5 min). Use <strong>Run Full Cycle</strong> below to trigger one cycle on-demand on the default symbol — useful for testing prompt changes without waiting for the scheduler. Each agent card shows their live status, current task, ELO, and win/loss record.
            </p>
          </div>
          <button onClick={runFullCycle} disabled={running === "cycle"} style={{
            background: running === "cycle" ? "var(--bg-surface-3)" : "var(--accent-primary)",
            color: "#fff", border: "none", borderRadius: "var(--radius-sm)",
            padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: running === "cycle" ? "not-allowed" : "pointer",
          }}>
            {running === "cycle" ? "Running Cycle…" : "Trigger Cycle Now"}
          </button>
        </div>

        {cycleResult && (
          <div style={{ marginBottom: 20, padding: "12px 20px", background: "rgba(94,106,210,0.15)", border: "1px solid var(--accent-primary)", borderRadius: "var(--radius-md)", fontFamily: "var(--font-mono)", fontSize: 14 }}>
            Cycle complete: <strong>{cycleResult}</strong>
          </div>
        )}

        {/* Agent grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12, marginBottom: 28 }}>
          {agents.map(a => (
            <AgentCard key={a.id} agent={a} onRun={runAgent} />
          ))}
        </div>

        <ConsensusMeter signals={signals} />

        {/* Signal feed */}
        {signals.length > 0 && (
          <div className="glass-panel" style={{ padding: 20, marginTop: 20 }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 12 }}>Live Signal Feed</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {signals.slice(0, 10).map((s, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 12px", background: "var(--bg-surface-2)", borderRadius: "var(--radius-sm)" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-secondary)", minWidth: 80 }}>{s.symbol}</span>
                  <span style={{
                    fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4,
                    background: s.direction === "LONG" ? "rgba(88,214,141,0.15)" : s.direction === "SHORT" ? "rgba(248,81,73,0.15)" : "var(--bg-surface-3)",
                    color: s.direction === "LONG" ? "var(--accent-profit)" : s.direction === "SHORT" ? "var(--accent-loss)" : "var(--text-secondary)",
                  }}>{s.direction}</span>
                  <span style={{ fontSize: 12, color: "var(--text-secondary)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.thesis}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-tertiary)" }}>
                    {(parseFloat(s.confidence) * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
