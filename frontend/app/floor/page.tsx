"use client";
import { useState, useEffect, useRef } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const AGENTS = [
  { id: "marcus", name: "Marcus", role: "Fundamentals", color: "#9677D0", x: 0, y: 0 },
  { id: "vera",   name: "Vera",   role: "Technical",    color: "#643588", x: 1, y: 0 },
  { id: "rex",    name: "Rex",    role: "Sentiment",    color: "#9677D0", x: 2, y: 0 },
  { id: "diana",  name: "Diana",  role: "Risk",         color: "#ED6F91", x: 0, y: 1 },
  { id: "atlas",  name: "Atlas",  role: "Execution",    color: "#3EB6B0", x: 1, y: 1 },
  { id: "nova",   name: "Nova",   role: "Options",      color: "#26888A", x: 2, y: 1 },
  { id: "bull",   name: "Bull",   role: "Research↑",   color: "#E3A535", x: 0, y: 2 },
  { id: "bear",   name: "Bear",   role: "Research↓",   color: "#B87D1E", x: 1, y: 2 },
  { id: "sage",   name: "Sage",   role: "Supervisor",   color: "#F89318", x: 2, y: 2 },
  { id: "scout",  name: "Scout",  role: "Opportunities",color: "#38BDF8", x: 3, y: 1 },
];

interface Bubble { agentId: string; text: string; dir: string; id: number }
interface Signal { agent_id?: string; direction?: string; thesis?: string; _ts?: string }

// Isometric desk using SVG polygons
function IsoDesk({ color, active }: { color: string; active: boolean }) {
  const c = active ? color : "#2a2f3a";
  const glow = active ? color : "transparent";
  return (
    <svg width="90" height="60" viewBox="0 0 90 60" style={{ filter: active ? `drop-shadow(0 0 6px ${glow})` : "none", transition: "filter 0.4s" }}>
      {/* top face */}
      <polygon points="45,2 88,24 45,46 2,24" fill={c} opacity="0.9" />
      {/* left face */}
      <polygon points="2,24 45,46 45,58 2,36" fill={c} opacity="0.5" />
      {/* right face */}
      <polygon points="88,24 45,46 45,58 88,36" fill={c} opacity="0.65" />
      {/* screen */}
      <polygon points="35,12 55,22 55,32 35,22" fill="#0A0D13" opacity="0.8" />
      <polygon points="36,13 54,22 54,31 36,22" fill={active ? color : "#1a1f2a"} opacity="0.6" />
    </svg>
  );
}

function AgentDesk({ agent, bubble, active, onClick }: {
  agent: typeof AGENTS[0]; bubble: Bubble | null; active: boolean; onClick: () => void
}) {
  return (
    <div onClick={onClick} style={{ position: "relative", cursor: "pointer", userSelect: "none", display: "flex", flexDirection: "column", alignItems: "center" }}>
      {/* Speech bubble */}
      {bubble && (
        <div style={{
          position: "absolute", bottom: "100%", left: "50%", transform: "translateX(-50%)",
          background: "var(--bg-surface-2)", border: `1px solid ${agent.color}`,
          borderRadius: 8, padding: "6px 10px", fontSize: 11, maxWidth: 160, textAlign: "center",
          color: "var(--text-primary)", whiteSpace: "normal", zIndex: 10, marginBottom: 8,
          animation: "bubbleFadeIn 0.3s ease",
        }}>
          <span style={{ color: bubble.dir === "LONG" ? "var(--accent-profit)" : bubble.dir === "SHORT" ? "var(--accent-loss)" : "var(--text-secondary)", fontWeight: 700, marginRight: 4 }}>{bubble.dir}</span>
          {bubble.text.slice(0, 60)}{bubble.text.length > 60 ? "…" : ""}
        </div>
      )}
      <IsoDesk color={agent.color} active={active} />
      {/* Agent figure */}
      <div style={{ position: "absolute", top: 4, left: "50%", transform: "translateX(-50%)", display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{ width: 14, height: 14, borderRadius: "50%", background: agent.color, border: "2px solid var(--bg-void)" }} />
        <div style={{ width: 12, height: 16, background: agent.color, opacity: 0.7, borderRadius: "3px 3px 0 0", marginTop: 1 }} />
      </div>
      {/* Status dot */}
      <div style={{ position: "absolute", top: 2, right: 2, width: 7, height: 7, borderRadius: "50%", background: active ? "var(--status-normal)" : "var(--status-off)", boxShadow: active ? "0 0 4px var(--status-normal)" : "none" }} />
      {/* Label */}
      <div style={{ textAlign: "center", marginTop: 6 }}>
        <div style={{ fontWeight: 700, fontSize: 12, color: agent.color }}>{agent.name}</div>
        <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{agent.role}</div>
      </div>
    </div>
  );
}

export default function FloorPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const [bubbles, setBubbles] = useState<Map<string, Bubble>>(new Map());
  const [activeAgents, setActiveAgents] = useState<Set<string>>(new Set());
  const [bullThesis, setBullThesis] = useState("Awaiting analysis…");
  const [bearThesis, setBearThesis] = useState("Awaiting analysis…");
  const [consensus, setConsensus] = useState(0.5); // 0=full bear, 1=full bull
  const bubbleCounter = useRef(0);

  // Poll for signals
  useEffect(() => {
    const ws = new WebSocket(`${API.replace("http", "ws")}/ws`);
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        const signals: Signal[] = data.signals ?? (data.type === "signal" ? [data] : []);
        signals.forEach((sig) => {
          const agentId = sig.agent_id;
          if (!agentId) return;
          const id = ++bubbleCounter.current;
          const bubble: Bubble = { agentId, text: sig.thesis ?? "Signal emitted", dir: sig.direction ?? "NEUTRAL", id };
          setBubbles(prev => new Map(prev).set(agentId, bubble));
          setActiveAgents(prev => new Set(prev).add(agentId));
          setTimeout(() => {
            setBubbles(prev => { const m = new Map(prev); m.delete(agentId); return m; });
            setActiveAgents(prev => { const s = new Set(prev); s.delete(agentId); return s; });
          }, 5000);
          if (agentId === "bull") setBullThesis(sig.thesis ?? bullThesis);
          if (agentId === "bear") setBearThesis(sig.thesis ?? bearThesis);
        });
      } catch {}
    };
    return () => ws.close();
  }, []);

  const selectedAgent = AGENTS.find(a => a.id === selected);

  // Isometric grid layout — 4 columns, rows staggered
  const COL_W = 130, ROW_H = 110;
  const maxCols = Math.max(...AGENTS.map(a => a.x)) + 1;
  const maxRows = Math.max(...AGENTS.map(a => a.y)) + 1;
  const gridW = maxCols * COL_W + 60;
  const gridH = maxRows * ROW_H + 60;

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-void)", color: "var(--text-primary)", padding: "32px", fontFamily: "var(--font-sans)" }}>
      <style>{`@keyframes bubbleFadeIn{from{opacity:0;transform:translateX(-50%) translateY(6px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}`}</style>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 4 }}>Trading Floor</h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 13, marginBottom: 6, maxWidth: 700 }}>
          Spatial view of the desk. Each tile is an agent — when it lights up, that agent is actively analyzing a symbol. Speech bubbles show the most recent signal. Click any desk for details.
        </p>
        <p style={{ color: "var(--text-tertiary)", fontSize: 12, marginBottom: 24, maxWidth: 700 }}>
          This is the same data as Mission Control's Agent Cycle panel, rendered as a floor plan for at-a-glance awareness.
        </p>

        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
          {/* Floor grid */}
          <div style={{ flex: "1 1 500px", position: "relative", height: gridH, minWidth: gridW }}>
            {AGENTS.map(agent => (
              <div key={agent.id} style={{
                position: "absolute",
                left: agent.x * COL_W + (agent.y % 2 === 1 ? COL_W / 2 : 0),
                top: agent.y * ROW_H,
              }}>
                <AgentDesk
                  agent={agent}
                  bubble={bubbles.get(agent.id) ?? null}
                  active={activeAgents.has(agent.id)}
                  onClick={() => setSelected(selected === agent.id ? null : agent.id)}
                />
              </div>
            ))}
          </div>

          {/* Detail panel */}
          {selectedAgent && (
            <div className="glass-panel" style={{ flex: "0 0 260px", padding: 20 }}>
              <div style={{ fontWeight: 700, fontSize: 18, color: selectedAgent.color, marginBottom: 4 }}>{selectedAgent.name}</div>
              <div style={{ color: "var(--text-tertiary)", fontSize: 12, marginBottom: 16 }}>{selectedAgent.role}</div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8 }}>Status</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
                <div style={{ width: 8, height: 8, borderRadius: "50%", background: activeAgents.has(selectedAgent.id) ? "var(--status-normal)" : "var(--status-off)" }} />
                <span style={{ fontSize: 13 }}>{activeAgents.has(selectedAgent.id) ? "Active" : "Idle"}</span>
              </div>
              <button onClick={() => setSelected(null)} style={{ background: "var(--bg-surface-3)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", padding: "6px 14px", fontSize: 12, cursor: "pointer" }}>Close</button>
            </div>
          )}
        </div>

        {/* Bull vs Bear debate */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 16, marginTop: 28, alignItems: "center" }}>
          <div className="glass-panel" style={{ padding: 20, borderColor: "rgba(88,214,141,0.2)", background: "rgba(88,214,141,0.04)" }}>
            <div style={{ fontSize: 11, color: "var(--accent-profit)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>Bull — {AGENTS.find(a=>a.id==="bull")?.role}</div>
            <div style={{ fontSize: 13, color: "var(--text-primary)", lineHeight: 1.6 }}>{bullThesis}</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase" }}>Consensus</div>
            <div style={{ width: 12, height: 80, background: "var(--bg-surface-3)", borderRadius: 6, position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", bottom: 0, width: "100%", height: `${consensus * 100}%`, background: `linear-gradient(to top, var(--accent-loss), var(--accent-profit))`, transition: "height 0.5s" }} />
            </div>
          </div>
          <div className="glass-panel" style={{ padding: 20, borderColor: "rgba(248,81,73,0.2)", background: "rgba(248,81,73,0.04)" }}>
            <div style={{ fontSize: 11, color: "var(--accent-loss)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>Bear — {AGENTS.find(a=>a.id==="bear")?.role}</div>
            <div style={{ fontSize: 13, color: "var(--text-primary)", lineHeight: 1.6 }}>{bearThesis}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
