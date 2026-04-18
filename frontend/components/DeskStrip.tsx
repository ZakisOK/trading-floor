"use client";

interface Agent {
  id: string;
  name: string;
  status?: string;
  current_task?: string | null;
  last_heartbeat?: string | null;
}

const DESKS = [
  {
    key: "research",
    label: "Alpha Research",
    subtitle: "Desk 1",
    icon: "🔬",
    agents: ["marcus", "vera", "rex", "xrp_analyst", "polymarket_scout", "nova"],
    color: "#5E6AD2",
    description: "Generates signals, debates conviction, synthesizes via Nova",
  },
  {
    key: "execution",
    label: "Trade Execution",
    subtitle: "Desk 2",
    icon: "⚡",
    agents: ["diana", "atlas"],
    color: "#22C55E",
    description: "Consumes Nova packets, risk-checks, executes",
  },
  {
    key: "oversight",
    label: "Portfolio Oversight",
    subtitle: "Desk 3",
    icon: "🛡",
    agents: ["sage", "scout"],
    color: "#F59E0B",
    description: "Monitors exposure, drawdown, cross-agent calibration",
  },
] as const;

function formatAgentName(id: string) {
  if (id === "xrp_analyst") return "XRP Analyst";
  if (id === "polymarket_scout") return "Polymarket Scout";
  return id.charAt(0).toUpperCase() + id.slice(1);
}

export function DeskStrip({ agents }: { agents: Agent[] }) {
  const byId = new Map(agents.map((a) => [a.id, a]));

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, marginBottom: 24 }}>
      {DESKS.map((desk) => {
        const deskAgents = desk.agents.map((id) => byId.get(id)).filter(Boolean) as Agent[];
        const activeCount = deskAgents.filter((a) => a.status === "active").length;
        const online = activeCount > 0;
        const currentTasks = deskAgents
          .filter((a) => a.current_task)
          .map((a) => `${formatAgentName(a.id)}: ${a.current_task}`);
        return (
          <div key={desk.key} className="glass-panel" style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
              <span style={{ fontSize: 22, lineHeight: 1 }}>{desk.icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>{desk.label}</span>
                  <span style={{
                    fontSize: 9, fontWeight: 600, padding: "1px 5px", borderRadius: 3,
                    background: `${desk.color}22`, color: desk.color, letterSpacing: "0.05em",
                  }}>
                    {desk.subtitle}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: "var(--text-tertiary)", lineHeight: 1.4 }}>{desk.description}</div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <div style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: online ? "#22c55e" : "var(--text-tertiary)",
                  boxShadow: online ? "0 0 6px #22c55e" : "none",
                }} />
                <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
                  {activeCount}/{deskAgents.length}
                </span>
              </div>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {deskAgents.map((a) => (
                <span key={a.id} style={{
                  fontSize: 10, padding: "2px 7px", borderRadius: 10,
                  background: a.status === "active" ? `${desk.color}22` : "rgba(255,255,255,0.05)",
                  color: a.status === "active" ? desk.color : "var(--text-secondary)",
                  border: `1px solid ${a.status === "active" ? desk.color + "66" : "var(--border-subtle)"}`,
                  fontWeight: a.status === "active" ? 600 : 400,
                }}>
                  {formatAgentName(a.id)}
                </span>
              ))}
            </div>

            {currentTasks.length > 0 && (
              <div style={{
                padding: "8px 10px", borderRadius: 5, background: "rgba(255,255,255,0.02)",
                border: "1px solid var(--border-subtle)", fontSize: 11, color: "var(--text-secondary)",
                fontFamily: "var(--font-mono, monospace)",
              }}>
                {currentTasks.slice(0, 2).join(" · ")}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function PipelineFooter() {
  return (
    <div style={{
      marginTop: 16, padding: "12px 16px", borderRadius: 6,
      border: "1px solid var(--border-subtle)", background: "rgba(255,255,255,0.01)",
      fontSize: 11, color: "var(--text-tertiary)", lineHeight: 1.6,
    }}>
      <strong style={{ color: "var(--text-secondary)" }}>Pipeline:</strong>{" "}
      Marcus · Vera · Rex → [XRP Analyst] → Polymarket Scout →{" "}
      <strong style={{ color: "var(--accent-primary)" }}>Nova (Synthesizer)</strong>{" "}
      → stream:trade_desk:inbox →{" "}
      <strong style={{ color: "#22c55e" }}>Diana · Atlas</strong>{" "}
      → stream:trade_outcomes →{" "}
      <strong style={{ color: "#f59e0b" }}>Sage · Scout</strong>
    </div>
  );
}
