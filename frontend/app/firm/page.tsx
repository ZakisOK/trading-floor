"use client";
import { useEffect, useState, useCallback } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface DeskStatus {
  name: string;
  status: "active" | "idle" | "error";
  lastAction: string;
  agents: string[];
  activeCount: number;
}

interface AgentRow {
  id: string;
  name: string;
  role: string;
  desk: string;
  winRate: number | null;
  totalSignals: number;
  calibrationEce: number | null;
  calibrationStatus: string;
  currentWeight: number;
  lastSignal: string;
}

interface DailyReport {
  date: string;
  total_trades: number;
  win_rate: number;
  total_pnl_pct: number;
  sharpe: number | null;
  best_agent: string;
  worst_agent: string;
}

interface ConvictionPacket {
  packet_id: string;
  symbol: string;
  direction: string;
  final_confidence: number;
  consensus_strength: string;
  expires_at: string;
  regime: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const DESK_CONFIG = [
  {
    key: "research",
    label: "Alpha Research",
    subtitle: "Desk 1",
    icon: "🔬",
    agents: ["Marcus", "Vera", "Rex", "XRP Analyst", "Polymarket Scout", "Nova"],
    color: "var(--accent-primary)",
    description: "Generates signals, debates conviction, synthesizes via Nova",
  },
  {
    key: "execution",
    label: "Trade Execution",
    subtitle: "Desk 2",
    icon: "⚡",
    agents: ["Diana", "Atlas", "Trade Desk"],
    color: "#22c55e",
    description: "Receives conviction packets, sizes positions, executes and monitors",
  },
  {
    key: "oversight",
    label: "Portfolio Oversight",
    subtitle: "Desk 3",
    icon: "🏛",
    agents: ["Portfolio Chief"],
    color: "#f59e0b",
    description: "Correlation checks, regime detection, mistake patterns, daily reports",
  },
];

const AGENT_CATALOG: Omit<AgentRow, "winRate" | "totalSignals" | "calibrationEce" | "calibrationStatus" | "currentWeight" | "lastSignal">[] = [
  { id: "marcus",           name: "Marcus",           role: "Fundamentals Analyst",   desk: "Alpha Research" },
  { id: "vera",             name: "Vera",             role: "Technical Analyst",       desk: "Alpha Research" },
  { id: "rex",              name: "Rex",              role: "Sentiment Analyst",       desk: "Alpha Research" },
  { id: "xrp_analyst",     name: "XRP Analyst",      role: "Specialist",             desk: "Alpha Research" },
  { id: "polymarket_scout", name: "Polymarket Scout", role: "Prediction Markets",     desk: "Alpha Research" },
  { id: "nova",             name: "Nova",             role: "Synthesizer",            desk: "Alpha Research" },
  { id: "diana",            name: "Diana",            role: "Risk Manager",           desk: "Trade Execution" },
  { id: "atlas",            name: "Atlas",            role: "Executor",               desk: "Trade Execution" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function strengthColor(s: string) {
  if (s === "strong") return "#22c55e";
  if (s === "moderate") return "#f59e0b";
  return "#ef4444";
}

function pctFormat(v: number | null, decimals = 1) {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(decimals)}%`;
}

function confidenceBar(v: number) {
  const color = v >= 0.7 ? "#22c55e" : v >= 0.5 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{
        flex: 1, height: 4, background: "var(--border-subtle)", borderRadius: 2, overflow: "hidden",
      }}>
        <div style={{ width: `${v * 100}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 11, color: "var(--text-secondary)", minWidth: 32 }}>
        {(v * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function calibrationBadge(status: string, ece: number | null) {
  const colors: Record<string, string> = {
    well_calibrated: "#22c55e",
    moderate_drift: "#f59e0b",
    poorly_calibrated: "#ef4444",
    insufficient_data: "var(--text-tertiary)",
    no_data: "var(--text-tertiary)",
  };
  const labels: Record<string, string> = {
    well_calibrated: "Calibrated",
    moderate_drift: "Drifting",
    poorly_calibrated: "Miscal.",
    insufficient_data: "Learning",
    no_data: "No data",
  };
  const color = colors[status] || "var(--text-tertiary)";
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 3,
      border: `1px solid ${color}`, color, textTransform: "uppercase", letterSpacing: "0.04em",
    }}>
      {labels[status] || status} {ece !== null ? `(${(ece * 100).toFixed(1)})` : ""}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function DeskCard({ config, status }: { config: typeof DESK_CONFIG[0]; status?: DeskStatus }) {
  const online = status?.status === "active";
  return (
    <div style={{
      background: "var(--bg-panel)", border: "1px solid var(--border-subtle)",
      borderRadius: 8, padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16,
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <span style={{ fontSize: 28, lineHeight: 1 }}>{config.icon}</span>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
            <span style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
              {config.label}
            </span>
            <span style={{
              fontSize: 10, fontWeight: 600, padding: "1px 6px", borderRadius: 3,
              background: `${config.color}22`, color: config.color, letterSpacing: "0.05em",
            }}>
              {config.subtitle}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>{config.description}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <div style={{
            width: 7, height: 7, borderRadius: "50%",
            background: online ? "#22c55e" : "var(--text-tertiary)",
            boxShadow: online ? "0 0 6px #22c55e" : "none",
          }} />
          <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
            {online ? "Active" : "Idle"}
          </span>
        </div>
      </div>

      {/* Agent list */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {config.agents.map((a) => (
          <span key={a} style={{
            fontSize: 11, padding: "3px 8px", borderRadius: 12,
            background: "rgba(255,255,255,0.05)", color: "var(--text-secondary)",
            border: "1px solid var(--border-subtle)",
          }}>
            {a}
          </span>
        ))}
      </div>

      {/* Last action */}
      <div style={{
        padding: "10px 12px", borderRadius: 6, background: "rgba(255,255,255,0.02)",
        border: "1px solid var(--border-subtle)", fontSize: 12, color: "var(--text-secondary)",
        fontFamily: "monospace", minHeight: 38,
      }}>
        {status?.lastAction || "Awaiting activity…"}
      </div>
    </div>
  );
}

function ConvictionCard({ packet }: { packet: ConvictionPacket }) {
  const expiry = new Date(packet.expires_at);
  const msLeft = expiry.getTime() - Date.now();
  const minLeft = Math.max(0, Math.floor(msLeft / 60000));

  return (
    <div style={{
      background: "var(--bg-panel)", border: `1px solid ${strengthColor(packet.consensus_strength)}44`,
      borderRadius: 6, padding: "12px 16px", display: "flex", flexDirection: "column", gap: 8,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>
            {packet.symbol}
          </span>
          <span style={{
            fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 3,
            background: packet.direction === "LONG" ? "#22c55e22" : "#ef444422",
            color: packet.direction === "LONG" ? "#22c55e" : "#ef4444",
          }}>
            {packet.direction}
          </span>
          <span style={{
            fontSize: 10, fontWeight: 600, padding: "1px 5px", borderRadius: 3,
            border: `1px solid ${strengthColor(packet.consensus_strength)}`,
            color: strengthColor(packet.consensus_strength), textTransform: "uppercase",
          }}>
            {packet.consensus_strength}
          </span>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
          {packet.regime} · expires {minLeft}m
        </div>
      </div>
      {confidenceBar(packet.final_confidence)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function FirmPage() {
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [packets, setPackets] = useState<ConvictionPacket[]>([]);
  const [report, setReport] = useState<DailyReport | null>(null);
  const [regime, setRegime] = useState<string>("—");
  const [deskStatuses] = useState<Record<string, DeskStatus>>({});
  const [loading, setLoading] = useState(true);

  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  const fetchData = useCallback(async () => {
    try {
      // Agent stats
      const agentRows: AgentRow[] = AGENT_CATALOG.map((a) => ({
        ...a,
        winRate: null,
        totalSignals: 0,
        calibrationEce: null,
        calibrationStatus: "no_data",
        currentWeight: 0.5,
        lastSignal: "—",
      }));

      // Try to fetch live stats for each agent
      await Promise.allSettled(
        agentRows.map(async (row, idx) => {
          try {
            const r = await fetch(`${API}/api/agents/${row.id}/stats`, { signal: AbortSignal.timeout(3000) });
            if (r.ok) {
              const data = await r.json();
              agentRows[idx] = {
                ...agentRows[idx],
                winRate: data.win_rate ?? null,
                totalSignals: data.total_signals ?? 0,
                calibrationEce: data.calibration_ece ?? null,
                calibrationStatus: data.calibration_status ?? "no_data",
                currentWeight: data.current_weight ?? 0.5,
                lastSignal: data.last_signal ?? "—",
              };
            }
          } catch {
            // Stats endpoint not yet live — keep defaults
          }
        })
      );

      setAgents(agentRows);

      // Daily report
      try {
        const r = await fetch(`${API}/api/performance/daily/latest`, { signal: AbortSignal.timeout(3000) });
        if (r.ok) setReport(await r.json());
      } catch { /* offline */ }

      // Regime
      try {
        const r = await fetch(`${API}/api/market/regime`, { signal: AbortSignal.timeout(3000) });
        if (r.ok) {
          const d = await r.json();
          setRegime(d.regime || "—");
        }
      } catch { /* offline */ }

      // Active conviction packets
      try {
        const r = await fetch(`${API}/api/trade_desk/pending`, { signal: AbortSignal.timeout(3000) });
        if (r.ok) setPackets(await r.json());
      } catch { /* offline */ }

    } catch (e) {
      console.error("FirmPage fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, [API]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 10000);
    return () => clearInterval(timer);
  }, [fetchData]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div style={{ padding: "28px 32px", maxWidth: 1400, margin: "0 auto" }}>

      {/* Page header */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
          <span style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
            The Firm
          </span>
          <span style={{
            fontSize: 11, padding: "2px 8px", borderRadius: 3, fontWeight: 600,
            background: "rgba(94,106,210,0.15)", color: "var(--accent-primary)",
            letterSpacing: "0.05em", textTransform: "uppercase",
          }}>
            Bloomberg Mode
          </span>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{
              width: 7, height: 7, borderRadius: "50%", background: "#22c55e",
              boxShadow: "0 0 6px #22c55e",
            }} />
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              Market Regime: <strong style={{ color: "var(--text-primary)" }}>{regime}</strong>
            </span>
          </div>
        </div>
        <p style={{ fontSize: 13, color: "var(--text-tertiary)", margin: 0 }}>
          Three-desk hedge fund architecture — Alpha Research · Trade Execution · Portfolio Oversight
        </p>
      </div>

      {/* Daily KPI strip */}
      {report && (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: 28,
        }}>
          {[
            { label: "Win Rate", value: pctFormat(report.win_rate) },
            { label: "Total P&L", value: pctFormat(report.total_pnl_pct) },
            { label: "Trades Today", value: String(report.total_trades) },
            { label: "Sharpe", value: report.sharpe !== null ? String(report.sharpe) : "—" },
            { label: "Best Agent", value: report.best_agent },
          ].map(({ label, value }) => (
            <div key={label} style={{
              background: "var(--bg-panel)", border: "1px solid var(--border-subtle)",
              borderRadius: 6, padding: "14px 16px",
            }}>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {label}
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>
                {value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Three desk columns */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 28 }}>
        {DESK_CONFIG.map((config) => (
          <DeskCard key={config.key} config={config} status={deskStatuses[config.key]} />
        ))}
      </div>

      {/* Active conviction packets from Nova */}
      {packets.length > 0 && (
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Live Conviction Packets — awaiting Desk 2
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {packets.map((p) => <ConvictionCard key={p.packet_id} packet={p} />)}
          </div>
        </div>
      )}

      {/* Agent Performance Table */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Agent Performance — Rolling 50 Signals
        </div>

        <div style={{
          background: "var(--bg-panel)", border: "1px solid var(--border-subtle)", borderRadius: 8, overflow: "hidden",
        }}>
          {/* Table header */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "180px 160px 140px 120px 160px 80px 1fr",
            padding: "10px 20px",
            borderBottom: "1px solid var(--border-subtle)",
            background: "rgba(255,255,255,0.02)",
          }}>
            {["Agent", "Desk", "Role", "Win Rate", "Calibration", "Weight", "Last Signal"].map((h) => (
              <span key={h} style={{ fontSize: 10, fontWeight: 600, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {h}
              </span>
            ))}
          </div>

          {loading ? (
            <div style={{ padding: "24px 20px", color: "var(--text-tertiary)", fontSize: 13 }}>
              Loading agent stats…
            </div>
          ) : (
            agents.map((agent, i) => (
              <div key={agent.id} style={{
                display: "grid",
                gridTemplateColumns: "180px 160px 140px 120px 160px 80px 1fr",
                padding: "12px 20px",
                borderBottom: i < agents.length - 1 ? "1px solid var(--border-subtle)" : "none",
                alignItems: "center",
                transition: "background 0.1s",
              }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.025)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                {/* Agent */}
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{agent.name}</div>
                  <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{agent.totalSignals} signals</div>
                </div>

                {/* Desk */}
                <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>{agent.desk}</div>

                {/* Role */}
                <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{agent.role}</div>

                {/* Win Rate */}
                <div style={{ fontSize: 13, fontWeight: 600, color: agent.winRate !== null ? (agent.winRate >= 0.5 ? "#22c55e" : "#ef4444") : "var(--text-tertiary)" }}>
                  {agent.winRate !== null ? pctFormat(agent.winRate) : "—"}
                </div>

                {/* Calibration */}
                <div>
                  {calibrationBadge(agent.calibrationStatus, agent.calibrationEce)}
                </div>

                {/* Weight */}
                <div style={{ width: 60 }}>
                  {confidenceBar(agent.currentWeight)}
                </div>

                {/* Last Signal */}
                <div style={{ fontSize: 11, color: "var(--text-tertiary)", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {agent.lastSignal}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Architecture note */}
      <div style={{
        marginTop: 28, padding: "14px 18px", borderRadius: 6,
        border: "1px solid var(--border-subtle)", background: "rgba(255,255,255,0.01)",
        fontSize: 12, color: "var(--text-tertiary)", lineHeight: 1.6,
      }}>
        <strong style={{ color: "var(--text-secondary)" }}>Pipeline:</strong>{" "}
        Marcus · Vera · Rex → [XRP Analyst] → Polymarket Scout →{" "}
        <strong style={{ color: "var(--accent-primary)" }}>Nova (Synthesizer)</strong>{" "}
        → stream:trade_desk:inbox →{" "}
        <strong style={{ color: "#22c55e" }}>Diana · Atlas</strong>{" "}
        → stream:trade_outcomes →{" "}
        <strong style={{ color: "#f59e0b" }}>AgentMemory · Portfolio Chief</strong>
      </div>
    </div>
  );
}
