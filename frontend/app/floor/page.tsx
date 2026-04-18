"use client";
import { useState, useEffect, useRef, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS_URL = API.replace(/^http/, "ws") + "/ws/stream";

type AgentId =
  | "marcus" | "vera" | "rex" | "xrp_analyst" | "polymarket_scout"
  | "diana" | "nova" | "atlas" | "bull" | "bear" | "sage" | "scout";

interface AgentDef {
  id: AgentId;
  name: string;
  role: string;
  desk: "research" | "execution" | "oversight";
  color: string;
  x: number; // grid col (0..5)
  y: number; // grid row (0..3)
}

// Layout: 3 desks as visual zones, agents placed within
const AGENTS: AgentDef[] = [
  // Desk 1 — Alpha Research (top row)
  { id: "marcus", name: "Marcus", role: "Fundamentals", desk: "research", color: "#9677D0", x: 0, y: 0 },
  { id: "vera", name: "Vera", role: "Technical", desk: "research", color: "#643588", x: 1, y: 0 },
  { id: "rex", name: "Rex", role: "Sentiment", desk: "research", color: "#c084fc", x: 2, y: 0 },
  { id: "xrp_analyst", name: "XRP Analyst", role: "Symbol Specialist", desk: "research", color: "#a855f7", x: 3, y: 0 },
  { id: "polymarket_scout", name: "Polymarket", role: "Prediction", desk: "research", color: "#7c3aed", x: 4, y: 0 },
  { id: "nova", name: "Nova", role: "Synthesizer", desk: "research", color: "#3EB6B0", x: 5, y: 0 },

  // Desk 2 — Trade Execution (middle row)
  { id: "diana", name: "Diana", role: "Risk Check", desk: "execution", color: "#ED6F91", x: 2, y: 1 },
  { id: "atlas", name: "Atlas", role: "Execution", desk: "execution", color: "#22C55E", x: 3, y: 1 },

  // Desk 3 — Portfolio Oversight (bottom row)
  { id: "sage", name: "Sage", role: "Supervisor", desk: "oversight", color: "#F89318", x: 1, y: 2 },
  { id: "scout", name: "Scout", role: "Opportunities", desk: "oversight", color: "#38BDF8", x: 3, y: 2 },
  { id: "bull", name: "Bull", role: "Bull Case", desk: "oversight", color: "#E3A535", x: 0, y: 2 },
  { id: "bear", name: "Bear", role: "Bear Case", desk: "oversight", color: "#B87D1E", x: 4, y: 2 },
];

const COL_W = 150;
const ROW_H = 170;
const GRID_W = 6 * COL_W;
const GRID_H = 3 * ROW_H + 60;

const DESKS = {
  research: { label: "Alpha Research", color: "#9677D0", rowStart: 0, rowEnd: 0 },
  execution: { label: "Trade Execution", color: "#22C55E", rowStart: 1, rowEnd: 1 },
  oversight: { label: "Portfolio Oversight", color: "#F89318", rowStart: 2, rowEnd: 2 },
};

interface AgentState {
  id: string;
  status: string;
  current_task: string | null;
  last_heartbeat: string | null;
  elo: number;
  trades_win?: number;
  trades_loss?: number;
}

interface Bubble {
  id: number;
  agentId: AgentId;
  symbol: string;
  direction: string;
  thesis: string;
  bornAt: number;
}

interface Particle {
  id: number;
  from: AgentId;
  to: AgentId;
  direction: string;
  bornAt: number;
  durationMs: number;
}

function agentPos(id: AgentId): { cx: number; cy: number } {
  const a = AGENTS.find((x) => x.id === id);
  if (!a) return { cx: 0, cy: 0 };
  return {
    cx: a.x * COL_W + COL_W / 2,
    cy: a.y * ROW_H + ROW_H / 2 + 30,
  };
}

export default function FloorPage() {
  const [agents, setAgents] = useState<Record<string, AgentState>>({});
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [particles, setParticles] = useState<Particle[]>([]);
  const [selected, setSelected] = useState<AgentId | null>(null);
  const [, tick] = useState(0); // re-render for particle animation
  const wsRef = useRef<WebSocket | null>(null);
  const idRef = useRef(1);

  // Poll agent status
  const fetchAgents = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/agents`);
      if (!r.ok) return;
      const list = await r.json();
      const map: Record<string, AgentState> = {};
      for (const a of list) map[a.id] = a;
      setAgents(map);
    } catch {}
  }, []);

  useEffect(() => {
    fetchAgents();
    const iv = setInterval(fetchAgents, 2_000);
    return () => clearInterval(iv);
  }, [fetchAgents]);

  // WebSocket for live signals
  useEffect(() => {
    let retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      try {
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;
        ws.onmessage = (e) => {
          try {
            const d = JSON.parse(e.data);
            if (d.type === "signal") {
              const agentId = (d.agent_id as AgentId) || (d.agent_name ?? "").toLowerCase();
              const validAgent = AGENTS.find((a) => a.id === agentId);
              if (!validAgent) return;
              const bubbleId = idRef.current++;
              const newBubble: Bubble = {
                id: bubbleId,
                agentId: agentId,
                symbol: d.symbol || "?",
                direction: d.direction || "NEUTRAL",
                thesis: (d.thesis || "").slice(0, 100),
                bornAt: Date.now(),
              };
              setBubbles((prev) => [...prev.filter((b) => b.agentId !== agentId), newBubble]);

              // Particle toward Nova (research desk) or Diana (if execution-relevant)
              const target: AgentId = ["diana", "atlas"].includes(agentId) ? "sage" : "nova";
              if (agentId !== target) {
                const p: Particle = {
                  id: idRef.current++,
                  from: agentId,
                  to: target,
                  direction: d.direction || "NEUTRAL",
                  bornAt: Date.now(),
                  durationMs: 1500,
                };
                setParticles((prev) => [...prev, p]);
              }
            }
          } catch {}
        };
        ws.onclose = () => { retry = setTimeout(connect, 5_000); };
        ws.onerror = () => ws.close();
      } catch {}
    };
    connect();
    return () => {
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  // Animation frame loop for particles + bubble expiry
  useEffect(() => {
    let raf: number;
    const loop = () => {
      const now = Date.now();
      setBubbles((prev) => prev.filter((b) => now - b.bornAt < 8_000));
      setParticles((prev) => prev.filter((p) => now - p.bornAt < p.durationMs + 200));
      tick((t) => t + 1);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div style={{ padding: "28px 32px", maxWidth: 1400, margin: "0 auto", minHeight: "100vh" }}>
      <style>{`
        @keyframes pulse { 0% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.05); opacity: 0.85; } 100% { transform: scale(1); opacity: 1; } }
        @keyframes bubbleIn { from { opacity: 0; transform: translateX(-50%) translateY(8px); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }
        @keyframes bubbleOut { from { opacity: 1; } to { opacity: 0; } }
      `}</style>

      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", letterSpacing: "-0.02em", margin: "0 0 6px 0" }}>
          Trading Floor — Live
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-tertiary)", margin: 0, maxWidth: 800 }}>
          The room where the agents work. Desks glow when an agent is active. Thought bubbles pop when signals emit. Particles show data flowing from analysts to Nova (synthesis), Diana (risk check), and Atlas (execution).
        </p>
      </div>

      <div style={{ position: "relative", width: "100%", overflowX: "auto" }}>
        <div style={{ position: "relative", width: GRID_W, height: GRID_H, margin: "0 auto" }}>
          {/* Desk zone backgrounds */}
          {Object.entries(DESKS).map(([k, d]) => (
            <div key={k} style={{
              position: "absolute",
              left: 0,
              top: d.rowStart * ROW_H + 30,
              width: GRID_W,
              height: ROW_H - 10,
              background: `linear-gradient(90deg, ${d.color}08, transparent 80%)`,
              borderLeft: `3px solid ${d.color}44`,
              borderRadius: 8,
            }}>
              <div style={{
                position: "absolute", top: 8, left: 12,
                fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
                color: d.color, textTransform: "uppercase", opacity: 0.8,
              }}>
                {d.label}
              </div>
            </div>
          ))}

          {/* SVG for particles */}
          <svg width={GRID_W} height={GRID_H} style={{ position: "absolute", left: 0, top: 0, pointerEvents: "none" }}>
            {particles.map((p) => {
              const elapsed = Date.now() - p.bornAt;
              const progress = Math.min(1, elapsed / p.durationMs);
              const from = agentPos(p.from);
              const to = agentPos(p.to);
              const x = from.cx + (to.cx - from.cx) * progress;
              const y = from.cy + (to.cy - from.cy) * progress;
              const color = p.direction === "LONG" ? "#22C55E" : p.direction === "SHORT" ? "#EF4444" : "#94A3B8";
              return (
                <g key={p.id}>
                  <line x1={from.cx} y1={from.cy} x2={to.cx} y2={to.cy} stroke={color} strokeOpacity="0.15" strokeWidth="1" strokeDasharray="4 4" />
                  <circle cx={x} cy={y} r={5} fill={color} opacity={1 - progress * 0.4}>
                    <animate attributeName="r" from="5" to="8" dur="0.6s" repeatCount="indefinite" />
                  </circle>
                </g>
              );
            })}
          </svg>

          {/* Agent desks */}
          {AGENTS.map((a) => {
            const st = agents[a.id];
            const active = st?.status === "active";
            const bubble = bubbles.find((b) => b.agentId === a.id);
            return (
              <div key={a.id} style={{
                position: "absolute",
                left: a.x * COL_W + (COL_W - 110) / 2,
                top: a.y * ROW_H + 45,
                width: 110,
                textAlign: "center",
                cursor: "pointer",
                userSelect: "none",
              }} onClick={() => setSelected(selected === a.id ? null : a.id)}>
                {bubble && (
                  <div style={{
                    position: "absolute", bottom: "calc(100% - 8px)", left: "50%", transform: "translateX(-50%)",
                    background: "rgba(20,25,35,0.95)", border: `1px solid ${a.color}`,
                    borderRadius: 8, padding: "6px 10px", fontSize: 11, minWidth: 140, maxWidth: 180,
                    zIndex: 10, animation: "bubbleIn 0.3s ease",
                    boxShadow: `0 4px 14px ${a.color}33`,
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                      <span style={{ fontWeight: 700, color: bubble.direction === "LONG" ? "#22C55E" : bubble.direction === "SHORT" ? "#EF4444" : "#94A3B8" }}>
                        {bubble.direction}
                      </span>
                      <span style={{ fontSize: 9, color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>
                        {bubble.symbol}
                      </span>
                    </div>
                    <div style={{ color: "var(--text-secondary)", lineHeight: 1.35, fontSize: 10 }}>
                      {bubble.thesis}{bubble.thesis.length >= 100 ? "…" : ""}
                    </div>
                  </div>
                )}

                <div style={{
                  position: "relative",
                  width: 80, height: 60, margin: "0 auto",
                  animation: active ? "pulse 1.8s ease-in-out infinite" : "none",
                }}>
                  <svg width="80" height="60" viewBox="0 0 80 60">
                    <defs>
                      <linearGradient id={`grad-${a.id}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={a.color} stopOpacity={active ? 1 : 0.4} />
                        <stop offset="100%" stopColor={a.color} stopOpacity={active ? 0.6 : 0.2} />
                      </linearGradient>
                    </defs>
                    <polygon points="40,4 76,22 40,40 4,22" fill={`url(#grad-${a.id})`} stroke={a.color} strokeOpacity={active ? 1 : 0.3} />
                    <polygon points="4,22 40,40 40,52 4,34" fill={a.color} opacity={active ? 0.35 : 0.15} />
                    <polygon points="76,22 40,40 40,52 76,34" fill={a.color} opacity={active ? 0.55 : 0.25} />
                    <polygon points="30,12 50,20 50,28 30,20" fill="#0A0D13" opacity="0.9" />
                    <polygon points="31,13 49,20 49,27 31,20" fill={a.color} opacity={active ? 0.7 : 0.3} />
                    {active && (
                      <circle cx="72" cy="10" r="4" fill="#22C55E">
                        <animate attributeName="opacity" values="1;0.2;1" dur="1.2s" repeatCount="indefinite" />
                      </circle>
                    )}
                  </svg>
                </div>

                <div style={{
                  fontSize: 12, fontWeight: 700, color: active ? "var(--text-primary)" : "var(--text-secondary)",
                  marginTop: 6, letterSpacing: "-0.01em",
                }}>
                  {a.name}
                </div>
                <div style={{ fontSize: 9, color: "var(--text-tertiary)", marginTop: 1 }}>
                  {a.role}
                </div>
                {st?.current_task && (
                  <div style={{
                    fontSize: 9, color: a.color, marginTop: 3,
                    fontFamily: "var(--font-mono, monospace)",
                    padding: "1px 6px", background: `${a.color}22`, borderRadius: 3, display: "inline-block",
                  }}>
                    {st.current_task}
                  </div>
                )}
                {st && (
                  <div style={{ fontSize: 9, color: "var(--text-tertiary)", marginTop: 2 }}>
                    ELO {Math.round(st.elo)}
                    {st.trades_win != null && st.trades_win + (st.trades_loss || 0) > 0 && (
                      <span> · {st.trades_win}W-{st.trades_loss || 0}L</span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {selected && agents[selected] && (
        <div className="glass-panel" style={{
          position: "fixed", right: 24, top: 100, width: 300,
          padding: 20, zIndex: 100,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
                {AGENTS.find((a) => a.id === selected)?.name}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                {AGENTS.find((a) => a.id === selected)?.role}
              </div>
            </div>
            <button onClick={() => setSelected(null)} style={{
              background: "transparent", border: "1px solid var(--border-default)",
              color: "var(--text-tertiary)", padding: "4px 10px", borderRadius: 4,
              fontSize: 11, cursor: "pointer",
            }}>Close</button>
          </div>
          <div style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 8, color: "var(--text-secondary)" }}>
            <div>Status: <strong style={{ color: agents[selected].status === "active" ? "#22C55E" : "var(--text-tertiary)" }}>{agents[selected].status}</strong></div>
            {agents[selected].current_task && <div>Working on: <strong>{agents[selected].current_task}</strong></div>}
            <div>ELO: {Math.round(agents[selected].elo)}</div>
            {agents[selected].trades_win != null && (
              <div>Record: {agents[selected].trades_win}W / {agents[selected].trades_loss || 0}L</div>
            )}
            {agents[selected].last_heartbeat && (
              <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
                Last heartbeat: {new Date(agents[selected].last_heartbeat).toLocaleTimeString()}
              </div>
            )}
          </div>
        </div>
      )}

      <div style={{
        marginTop: 32, fontSize: 11, color: "var(--text-tertiary)",
        display: "flex", gap: 18, justifyContent: "center",
      }}>
        <span><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "#22C55E", marginRight: 5, verticalAlign: "middle" }} />Active</span>
        <span><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "var(--border-subtle)", marginRight: 5, verticalAlign: "middle" }} />Idle</span>
        <span>Green particles = bullish signal · red = bearish</span>
      </div>
    </div>
  );
}
