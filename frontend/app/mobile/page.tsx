"use client";
import { useState, useEffect, useCallback, useRef } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_MS = 5000;

// ── types ─────────────────────────────────────────────────────────────────

interface Agent {
  id: string;
  name: string;
  role: string;
  color: string;
  status: string;
  elo: number;
  current_task: string | null;
  last_heartbeat: string | null;
}

interface RiskMetrics {
  daily_pnl: number;
  portfolio_value: number;
  total_exposure: number;
  drawdown_pct: number;
  open_positions: string | number;
  updated_at: string | null;
}

interface LivePosition {
  symbol: string;
  side: string;
  quantity: number;
  avg_price: number;
  entry_time: string;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  stop_loss: number;
  take_profit: number;
  trailing_stop: number | null;
  distance_to_stop_pct: number;
  distance_to_target_pct: number;
}

interface KillStatus {
  active: boolean;
  reason: string;
  activated_at: string;
}

interface WsAlert {
  type: string;
  message: string;
  ts: string;
}

// ── styles ────────────────────────────────────────────────────────────────

const mono = { fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" as const };

const card: React.CSSProperties = {
  background: "var(--bg-surface-1)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--radius-md)",
  padding: "14px 16px",
};

const sectionTitle: React.CSSProperties = {
  fontSize: 11,
  color: "var(--text-tertiary)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  marginBottom: 10,
};

// ── components ────────────────────────────────────────────────────────────

function KillSwitch({ status, onActivate, onReset }: {
  status: KillStatus | null;
  onActivate: () => void;
  onReset: () => void;
}) {
  const [confirmKill, setConfirmKill] = useState(false);
  const isActive = status?.active ?? false;

  return (
    <div style={{
      ...card,
      borderColor: isActive ? "var(--accent-loss)" : "var(--border-default)",
      background: isActive ? "rgba(248,81,73,0.08)" : "var(--bg-surface-1)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: isActive ? "var(--accent-loss)" : "var(--text-primary)" }}>
            Kill Switch {isActive ? "ACTIVE" : "Ready"}
          </div>
          {isActive && status?.reason && (
            <div style={{ fontSize: 11, color: "var(--accent-loss)", marginTop: 2 }}>{status.reason}</div>
          )}
        </div>
        {isActive ? (
          <button onClick={onReset} style={{
            background: "var(--bg-surface-3)", color: "var(--text-primary)",
            border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)",
            padding: "8px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}>Reset</button>
        ) : confirmKill ? (
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => { onActivate(); setConfirmKill(false); }} style={{
              background: "var(--accent-loss)", color: "#fff", border: "none",
              borderRadius: "var(--radius-sm)", padding: "8px 16px", fontSize: 13,
              fontWeight: 700, cursor: "pointer",
            }}>CONFIRM KILL</button>
            <button onClick={() => setConfirmKill(false)} style={{
              background: "var(--bg-surface-3)", color: "var(--text-secondary)",
              border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)",
              padding: "8px 16px", fontSize: 13, cursor: "pointer",
            }}>Cancel</button>
          </div>
        ) : (
          <button onClick={() => setConfirmKill(true)} style={{
            background: "rgba(248,81,73,0.15)", color: "var(--accent-loss)",
            border: "1px solid rgba(248,81,73,0.3)", borderRadius: "var(--radius-sm)",
            padding: "8px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}>Kill All</button>
        )}
      </div>
    </div>
  );
}

function PnlCard({ risk }: { risk: RiskMetrics | null }) {
  if (!risk) return null;
  const pnl = Number(risk.daily_pnl);
  const pnlColor = pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)";
  const drawdown = Math.abs(Number(risk.drawdown_pct));
  const drawdownColor = drawdown > 0.04 ? "var(--accent-loss)" : drawdown > 0.02 ? "#f0a500" : "var(--accent-profit)";

  return (
    <div style={card}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 4 }}>Portfolio</div>
          <div style={{ ...mono, fontSize: 18, fontWeight: 700 }}>
            ${Number(risk.portfolio_value).toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 4 }}>Daily P&L</div>
          <div style={{ ...mono, fontSize: 18, fontWeight: 700, color: pnlColor }}>
            {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
          </div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 4 }}>Exposure</div>
          <div style={{ ...mono, fontSize: 14 }}>${Number(risk.total_exposure).toFixed(2)}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 4 }}>Drawdown</div>
          <div style={{ ...mono, fontSize: 14, color: drawdownColor }}>{(drawdown * 100).toFixed(2)}%</div>
        </div>
      </div>
    </div>
  );
}

function AgentGrid({ agents }: { agents: Agent[] }) {
  const statusDot = (s: string) => {
    const colors: Record<string, string> = {
      active: "var(--status-normal)", idle: "var(--status-off)",
      error: "var(--status-critical)", running: "var(--status-standby)",
    };
    return colors[s] ?? colors.idle;
  };

  return (
    <div>
      <div style={sectionTitle}>Agents</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {agents.map(a => (
          <div key={a.id} style={{
            ...card,
            padding: "10px 12px",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}>
            <div style={{
              width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
              background: statusDot(a.status),
              boxShadow: a.status === "active" ? `0 0 6px ${statusDot(a.status)}` : "none",
            }} />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: a.color, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {a.name}
              </div>
              <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
                ELO {a.elo.toFixed(0)}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PositionsList({ positions }: { positions: LivePosition[] }) {
  if (positions.length === 0) {
    return (
      <div>
        <div style={sectionTitle}>Positions</div>
        <div style={{ ...card, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13, padding: 24 }}>
          No open positions
        </div>
      </div>
    );
  }

  return (
    <div>
      <div style={sectionTitle}>Positions ({positions.length})</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {positions.map(p => {
          const isProfit = p.unrealized_pnl >= 0;
          const pnlColor = isProfit ? "var(--accent-profit)" : "var(--accent-loss)";
          return (
            <div key={p.symbol} style={{
              ...card,
              borderColor: isProfit ? "rgba(88,214,141,0.25)" : "rgba(248,81,73,0.25)",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <div>
                  <div style={{ ...mono, fontSize: 15, fontWeight: 700 }}>{p.symbol}</div>
                  <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
                    {p.side} {p.quantity.toFixed(6)}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ ...mono, fontSize: 15, fontWeight: 700, color: pnlColor }}>
                    {isProfit ? "+" : ""}${p.unrealized_pnl.toFixed(2)}
                  </div>
                  <div style={{ ...mono, fontSize: 11, color: pnlColor }}>
                    {isProfit ? "+" : ""}{(p.unrealized_pnl_pct * 100).toFixed(2)}%
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-tertiary)" }}>
                <span>Entry ${p.avg_price.toFixed(4)}</span>
                <span>Now ${p.current_price.toFixed(4)}</span>
              </div>
              <div style={{ height: 4, background: "var(--bg-surface-3)", borderRadius: 2, overflow: "hidden", marginTop: 6 }}>
                <div style={{
                  height: "100%",
                  width: `${Math.max(0, Math.min(1, p.distance_to_stop_pct)) * 100}%`,
                  background: pnlColor,
                  borderRadius: 2,
                  transition: "width 0.8s ease",
                }} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--text-tertiary)", marginTop: 3 }}>
                <span>SL ${p.stop_loss.toFixed(4)}</span>
                <span>TP ${p.take_profit.toFixed(4)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AlertsFeed({ alerts }: { alerts: WsAlert[] }) {
  if (alerts.length === 0) return null;

  return (
    <div>
      <div style={sectionTitle}>Recent Alerts</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {alerts.slice(0, 10).map((a, i) => (
          <div key={i} style={{
            ...card,
            padding: "8px 12px",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}>
            <div style={{
              width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
              background: a.type === "error" ? "var(--accent-loss)" : a.type === "trade" ? "var(--accent-profit)" : "var(--accent-primary)",
            }} />
            <div style={{ fontSize: 12, color: "var(--text-secondary)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {a.message}
            </div>
            <div style={{ ...mono, fontSize: 10, color: "var(--text-tertiary)", flexShrink: 0 }}>
              {new Date(a.ts).toLocaleTimeString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── main page ─────────────────────────────────────────────────────────────

export default function MobileDashboard() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [risk, setRisk] = useState<RiskMetrics | null>(null);
  const [positions, setPositions] = useState<LivePosition[]>([]);
  const [killStatus, setKillStatus] = useState<KillStatus | null>(null);
  const [alerts, setAlerts] = useState<WsAlert[]>([]);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [agentRes, riskRes, posRes, killRes] = await Promise.all([
        fetch(`${API}/api/agents`),
        fetch(`${API}/api/execution/risk-metrics`),
        fetch(`${API}/api/execution/positions`),
        fetch(`${API}/api/orders/kill/status`),
      ]);
      setAgents(await agentRes.json());
      setRisk(await riskRes.json());
      setPositions(await posRes.json());
      setKillStatus(await killRes.json());
      setLastUpdate(new Date());
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Connection failed");
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, POLL_MS);
    return () => clearInterval(iv);
  }, [fetchAll]);

  // WebSocket for real-time alerts
  useEffect(() => {
    const wsUrl = API.replace(/^http/, "ws") + "/ws";
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    function connect() {
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.stream === "stream:alerts" || data.stream === "stream:trades" || data.stream === "stream:pnl") {
            setAlerts(prev => [{
              type: data.stream === "stream:trades" ? "trade" : data.stream === "stream:alerts" ? "alert" : "pnl",
              message: data.payload?.message ?? data.payload?.symbol ?? JSON.stringify(data.payload).slice(0, 80),
              ts: data.payload?.ts ?? new Date().toISOString(),
            }, ...prev].slice(0, 50));
          }
        } catch {}
      };

      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3000);
      };
    }

    connect();
    return () => {
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  async function activateKill() {
    try {
      await fetch(`${API}/api/orders/kill`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Mobile kill switch", operator_id: "operator" }),
      });
      fetchAll();
    } catch {}
  }

  async function resetKill() {
    try {
      await fetch(`${API}/api/orders/kill/reset`, { method: "POST" });
      fetchAll();
    } catch {}
  }

  return (
    <div style={{
      minHeight: "100vh",
      background: "var(--bg-void)",
      color: "var(--text-primary)",
      padding: "16px",
      fontFamily: "var(--font-sans)",
      maxWidth: 480,
      margin: "0 auto",
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>The Trading Floor</h1>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2 }}>
            Mobile Command Center
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "4px 10px", borderRadius: "var(--radius-sm)",
            background: error ? "rgba(248,81,73,0.1)" : "rgba(88,214,141,0.1)",
            border: `1px solid ${error ? "rgba(248,81,73,0.3)" : "rgba(88,214,141,0.3)"}`,
          }}>
            <div style={{
              width: 6, height: 6, borderRadius: "50%",
              background: error ? "var(--accent-loss)" : "var(--accent-profit)",
            }} />
            <span style={{ fontSize: 11, color: error ? "var(--accent-loss)" : "var(--accent-profit)" }}>
              {error ? "Offline" : "Live"}
            </span>
          </div>
          {lastUpdate && (
            <div style={{ ...mono, fontSize: 10, color: "var(--text-tertiary)", marginTop: 4 }}>
              {lastUpdate.toLocaleTimeString()}
            </div>
          )}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          marginBottom: 12, padding: "10px 14px",
          background: "rgba(248,81,73,0.08)", border: "1px solid rgba(248,81,73,0.3)",
          borderRadius: "var(--radius-sm)", color: "var(--accent-loss)", fontSize: 12,
        }}>
          {error}
        </div>
      )}

      {/* Content stack */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <KillSwitch status={killStatus} onActivate={activateKill} onReset={resetKill} />
        <PnlCard risk={risk} />
        <PositionsList positions={positions} />
        <AgentGrid agents={agents} />
        <AlertsFeed alerts={alerts} />
      </div>

      {/* Bottom spacer for mobile safe area */}
      <div style={{ height: 32 }} />
    </div>
  );
}
