"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS_URL = (API.replace(/^http/, "ws")) + "/ws/stream";

// ─── Types ───────────────────────────────────────────────────────────────────
interface Portfolio {
  cash: number;
  positions_value: number;
  total: number;
  daily_pnl: number;
  trade_count?: number;
  win_rate?: number;
}
interface Position {
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  stop_loss?: number;
}
interface Signal {
  agent?: string;
  direction: string;
  confidence: number;
  thesis: string;
  symbol?: string;
  asset_class?: string;
  signal_type?: string;
  ts?: string;
}
interface CopySignal {
  symbol: string;
  direction: string;
  confidence: number;
  sources: string[];
  binance_positions?: number;
  whale_moves?: number;
  cot_signal?: string;
}
interface AgentPerf {
  id: string;
  name: string;
  role: string;
  color: string;
  elo: number;
  status: string;
}
interface StreamEvent {
  ts: string;
  msg: string;
  level: string;
  stream?: string;
  data?: Record<string, unknown>;
}
interface SparkPrice {
  symbol: string;
  name: string;
  price: number;
  change_pct: number;
  history: number[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function fmt(n: number | undefined | null, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function fmtDollar(n: number | undefined | null) {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "+";
  if (abs >= 1_000_000) return `${sign}$${fmt(abs / 1_000_000, 2)}M`;
  if (abs >= 1_000) return `${sign}$${fmt(abs / 1_000, 1)}k`;
  return `${sign}$${fmt(abs)}`;
}
function pnlColor(n: number) {
  if (n > 0) return "var(--accent-profit)";
  if (n < 0) return "var(--accent-loss)";
  return "var(--text-secondary)";
}
function directionColor(d: string) {
  if (d === "LONG" || d === "BULLISH") return "var(--accent-profit)";
  if (d === "SHORT" || d === "BEARISH") return "var(--accent-loss)";
  return "var(--text-tertiary)";
}
function levelColor(level: string) {
  if (level === "error") return "var(--accent-loss)";
  if (level === "warning") return "#f59e0b";
  if (level === "info") return "var(--accent-info)";
  return "var(--text-tertiary)";
}
function streamColor(stream: string = "") {
  if (stream.includes("signal")) return "#60a5fa";
  if (stream.includes("trade")) return "var(--accent-profit)";
  if (stream.includes("alert") || stream.includes("risk")) return "#f59e0b";
  if (stream.includes("kill")) return "var(--accent-loss)";
  return "var(--text-tertiary)";
}
function confidenceBar(conf: number) {
  const pct = Math.round(conf * 100);
  const color = conf >= 0.75 ? "var(--accent-profit)" : conf >= 0.55 ? "#f59e0b" : "var(--accent-loss)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 60, height: 5, background: "var(--border-subtle)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 11, color }}>{pct}%</span>
    </div>
  );
}

// ─── Sparkline ────────────────────────────────────────────────────────────────
function Sparkline({ data, positive }: { data: number[]; positive: boolean }) {
  if (data.length < 2) return <div style={{ height: 32 }} />;
  const W = 80, H = 32;
  const min = Math.min(...data), max = Math.max(...data), range = max - min || 1;
  const pts = data.map((v, i) =>
    `${(i / (data.length - 1)) * W},${H - ((v - min) / range) * H}`
  ).join(" ");
  const color = positive ? "var(--accent-profit)" : "var(--accent-loss)";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: W, height: H }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────
function KPICard({
  label, value, sub, color, badge,
}: {
  label: string; value: string; sub?: string; color?: string; badge?: string;
}) {
  return (
    <div className="glass-panel" style={{
      padding: "18px 22px", flex: 1, minWidth: 140, display: "flex",
      flexDirection: "column", gap: 6,
    }}>
      <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, color: color || "var(--text-primary)", fontFamily: "var(--font-mono, monospace)" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>{sub}</div>}
      {badge && (
        <div style={{
          display: "inline-block", padding: "2px 8px", borderRadius: 4,
          fontSize: 11, fontWeight: 600,
          background: badge === "RISK-OFF" ? "rgba(239,68,68,0.15)" :
            badge === "TRENDING" ? "rgba(34,197,94,0.15)" : "rgba(148,163,184,0.15)",
          color: badge === "RISK-OFF" ? "var(--accent-loss)" :
            badge === "TRENDING" ? "var(--accent-profit)" : "var(--text-secondary)",
        }}>
          {badge}
        </div>
      )}
    </div>
  );
}

// ─── Asset class tabs ─────────────────────────────────────────────────────────
const ASSET_TABS = ["Crypto", "Commodities", "Equities"];
const SIDEBAR_PRICES: Record<string, { symbol: string; name: string; ticker: string }[]> = {
  Crypto: [
    { symbol: "XRP/USDT", name: "XRP", ticker: "XRP" },
    { symbol: "BTC/USDT", name: "Bitcoin", ticker: "BTC" },
    { symbol: "ETH/USDT", name: "Ethereum", ticker: "ETH" },
    { symbol: "SOL/USDT", name: "Solana", ticker: "SOL" },
  ],
  Commodities: [
    { symbol: "GC=F", name: "Gold", ticker: "XAU" },
    { symbol: "CL=F", name: "WTI Crude", ticker: "OIL" },
    { symbol: "NG=F", name: "Nat Gas", ticker: "NG" },
    { symbol: "SI=F", name: "Silver", ticker: "XAG" },
  ],
  Equities: [
    { symbol: "SPY", name: "S&P 500", ticker: "SPX" },
    { symbol: "QQQ", name: "Nasdaq 100", ticker: "NDX" },
    { symbol: "VIX", name: "VIX", ticker: "VIX" },
  ],
};

// ─── Main page ────────────────────────────────────────────────────────────────
export default function MissionControlPage() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [copySignals, setCopySignals] = useState<CopySignal[]>([]);
  const [agents, setAgents] = useState<AgentPerf[]>([]);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [regime, setRegime] = useState<string>("UNKNOWN");
  const [activeAgentCycle, setActiveAgentCycle] = useState<string>("Idle");
  const [activeSymbol, setActiveSymbol] = useState<string>("");
  const [assetTab, setAssetTab] = useState("Crypto");
  const [sparkPrices, setSparkPrices] = useState<SparkPrice[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const eventsRef = useRef<StreamEvent[]>([]);

  const fetchAll = useCallback(async () => {
    try {
      const [portRes, posRes, agRes] = await Promise.allSettled([
        fetch(`${API}/api/execution/portfolio`).then(r => r.json()),
        fetch(`${API}/api/execution/positions`).then(r => r.json()),
        fetch(`${API}/api/agents`).then(r => r.json()),
      ]);

      if (portRes.status === "fulfilled") setPortfolio(portRes.value);
      if (posRes.status === "fulfilled") {
        setPositions(Array.isArray(posRes.value) ? posRes.value : posRes.value?.positions ?? []);
      }
      if (agRes.status === "fulfilled") {
        setAgents(Array.isArray(agRes.value) ? agRes.value : agRes.value?.agents ?? []);
      }
    } catch {
      // API not available — degrade gracefully
    }

    try {
      const sigRes = await fetch(`${API}/api/signals/recent?limit=10`).then(r => r.json());
      const rawSignals = Array.isArray(sigRes) ? sigRes : sigRes?.signals ?? [];
      setSignals(rawSignals.slice(0, 6));
      // Filter copy trade signals
      const copy = rawSignals.filter((s: Signal) => s.signal_type === "copy_trade").slice(0, 3);
      setCopySignals(copy);
    } catch { /* noop */ }

    try {
      const regRes = await fetch(`${API}/api/market/regime`).then(r => r.json());
      setRegime(regRes?.regime ?? "UNKNOWN");
    } catch { /* noop */ }
  }, []);

  // WebSocket for live events
  useEffect(() => {
    let retryTimeout: ReturnType<typeof setTimeout>;
    const connect = () => {
      try {
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;

        ws.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data);
            const event: StreamEvent = {
              ts: data.ts ?? new Date().toISOString(),
              msg: data.msg ?? data.message ?? JSON.stringify(data).slice(0, 80),
              level: data.level ?? "info",
              stream: data.stream ?? data.type ?? "",
              data: data,
            };

            // Update active agent cycle
            if (data.type === "agent_start") {
              setActiveAgentCycle(data.agent_name ?? "Running");
              setActiveSymbol(data.symbol ?? "");
            }
            if (data.type === "agent_done" || data.type === "cycle_complete") {
              setActiveAgentCycle("Idle");
              setActiveSymbol("");
            }
            if (data.type === "signal") {
              setSignals(prev => [data as Signal, ...prev].slice(0, 10));
            }

            eventsRef.current = [event, ...eventsRef.current].slice(0, 20);
            setEvents([...eventsRef.current]);
          } catch { /* malformed WS message */ }
        };

        ws.onclose = () => {
          retryTimeout = setTimeout(connect, 5000);
        };
        ws.onerror = () => ws.close();
      } catch { /* WS not available */ }
    };
    connect();
    return () => {
      clearTimeout(retryTimeout);
      wsRef.current?.close();
    };
  }, []);

  // 5-second polling fallback + initial load
  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  // Mock sparkline data for sidebar (replace with real price history endpoint)
  useEffect(() => {
    const generate = (base: number, vol: number) =>
      Array.from({ length: 20 }, (_, i) => base + (Math.random() - 0.5) * vol * (i / 20 + 0.5));

    const mocks: Record<string, { base: number; vol: number; change: number }> = {
      "XRP/USDT": { base: 0.62, vol: 0.04, change: 2.3 },
      "BTC/USDT": { base: 67400, vol: 1200, change: -0.8 },
      "ETH/USDT": { base: 3480, vol: 150, change: 1.1 },
      "SOL/USDT": { base: 182, vol: 8, change: 3.2 },
      "GC=F": { base: 2340, vol: 25, change: 0.6 },
      "CL=F": { base: 79.4, vol: 1.5, change: -1.2 },
      "NG=F": { base: 2.18, vol: 0.15, change: 4.1 },
      "SI=F": { base: 28.6, vol: 0.8, change: 1.9 },
      "SPY": { base: 528, vol: 6, change: 0.4 },
      "QQQ": { base: 447, vol: 8, change: 0.7 },
      "VIX": { base: 16.4, vol: 1.2, change: -5.2 },
    };

    const all = Object.values(SIDEBAR_PRICES).flat().map(({ symbol, name, ticker }) => {
      const m = mocks[symbol] ?? { base: 100, vol: 2, change: 0 };
      return {
        symbol,
        name,
        price: m.base,
        change_pct: m.change,
        history: generate(m.base, m.vol),
      };
    });
    setSparkPrices(all);
  }, []);

  const currentTabPrices = sparkPrices.filter(p =>
    SIDEBAR_PRICES[assetTab]?.some(s => s.symbol === p.symbol)
  );

  const winRate = portfolio?.win_rate ?? 0;
  const totalValue = portfolio ? portfolio.cash + portfolio.positions_value : 0;

  return (
    <div style={{ display: "flex", flex: 1, gap: 0, height: "100%" }}>
      {/* ── Main content ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "28px 24px", display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Row 1: KPI cards */}
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <KPICard
            label="Portfolio Value"
            value={`$${fmt(totalValue, 0)}`}
            sub={`Cash: $${fmt(portfolio?.cash, 0)}`}
          />
          <KPICard
            label="Daily P&L"
            value={fmtDollar(portfolio?.daily_pnl)}
            color={pnlColor(portfolio?.daily_pnl ?? 0)}
            sub={`${positions.length} open position${positions.length !== 1 ? "s" : ""}`}
          />
          <KPICard
            label="Open Positions"
            value={String(positions.length)}
            sub={`${portfolio?.trade_count ?? 0} trades today`}
          />
          <KPICard
            label="Win Rate"
            value={winRate ? `${fmt(winRate * 100, 1)}%` : "—"}
            color={winRate > 0.55 ? "var(--accent-profit)" : "var(--text-primary)"}
            sub="Today's closed trades"
          />
          <KPICard
            label="Market Regime"
            value={regime}
            badge={
              regime === "RISK_OFF" ? "RISK-OFF" :
              regime === "TRENDING" ? "TRENDING" : undefined
            }
          />
        </div>

        {/* Row 2: Live feeds */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>

          {/* Active agent cycle */}
          <div className="glass-panel" style={{ padding: "18px 20px" }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 12 }}>
              Agent Cycle
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <div style={{
                width: 8, height: 8, borderRadius: "50%",
                background: activeAgentCycle === "Idle" ? "var(--text-tertiary)" : "var(--accent-profit)",
                boxShadow: activeAgentCycle !== "Idle" ? "0 0 6px var(--accent-profit)" : "none",
                animation: activeAgentCycle !== "Idle" ? "pulse 1.5s infinite" : "none",
              }} />
              <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>
                {activeAgentCycle}
              </span>
            </div>
            {activeSymbol && (
              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                Symbol: <span style={{ fontFamily: "var(--font-mono, monospace)", color: "var(--text-primary)" }}>{activeSymbol}</span>
              </div>
            )}
            <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 4 }}>
              {["marcus", "copy_trade_scout", "vera", "rex", "nova"].map(ag => (
                <div key={ag} style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                  <span style={{ color: "var(--text-tertiary)", textTransform: "capitalize" }}>
                    {ag.replace("_", " ")}
                  </span>
                  <span style={{ color: "var(--text-secondary)" }}>
                    {agents.find(a => a.id === ag)?.status ?? "—"}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Latest Nova conviction packets */}
          <div className="glass-panel" style={{ padding: "18px 20px" }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 12 }}>
              Nova Conviction Packets
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {signals.filter(s => s.signal_type !== "copy_trade").slice(0, 3).length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>No signals yet</div>
              ) : (
                signals.filter(s => s.signal_type !== "copy_trade").slice(0, 3).map((sig, i) => (
                  <div key={i} style={{
                    borderLeft: `3px solid ${directionColor(sig.direction)}`,
                    paddingLeft: 10, paddingTop: 4, paddingBottom: 4,
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: directionColor(sig.direction) }}>
                        {sig.direction}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>
                        {sig.symbol ?? "—"}
                      </span>
                    </div>
                    {confidenceBar(sig.confidence)}
                    <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4, lineHeight: 1.4 }}>
                      {sig.thesis?.slice(0, 90)}{sig.thesis?.length > 90 ? "…" : ""}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Copy trade signals */}
          <div className="glass-panel" style={{ padding: "18px 20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Copy Trade Signals
              </div>
              <Link href="/copy-trade" style={{ fontSize: 11, color: "var(--accent-info)", textDecoration: "none" }}>
                View all →
              </Link>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {copySignals.length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>No copy signals active</div>
              ) : (
                copySignals.map((cs, i) => (
                  <div key={i} style={{
                    padding: "8px 10px", borderRadius: 6,
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid var(--border-subtle)",
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                      <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 12, fontWeight: 700 }}>
                        {cs.symbol}
                      </span>
                      <span style={{ fontSize: 12, fontWeight: 700, color: directionColor(cs.direction) }}>
                        {cs.direction}
                      </span>
                    </div>
                    {confidenceBar(cs.confidence)}
                    <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 4 }}>
                      {cs.binance_positions != null && `${cs.binance_positions} Binance traders`}
                      {cs.whale_moves != null && cs.whale_moves > 0 && ` · ${cs.whale_moves} whale moves`}
                      {cs.cot_signal && cs.cot_signal !== "N/A" && ` · COT: ${cs.cot_signal}`}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Row 3: Positions + Agent performance */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 14 }}>

          {/* Open positions table */}
          <div className="glass-panel" style={{ padding: "18px 20px" }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 14 }}>
              Open Positions
            </div>
            {positions.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--text-tertiary)", padding: "12px 0" }}>No open positions</div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: "var(--text-tertiary)" }}>
                    {["Symbol", "Side", "Size", "Entry", "Current", "P&L", "Stop Dist"].map(h => (
                      <th key={h} style={{ textAlign: "left", paddingBottom: 8, fontWeight: 500, borderBottom: "1px solid var(--border-subtle)" }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {positions.map((pos, i) => {
                    const stopDist = pos.stop_loss
                      ? Math.abs((pos.current_price - pos.stop_loss) / pos.current_price * 100)
                      : null;
                    const stopPct = stopDist ? Math.min(100, stopDist / 10 * 100) : 0;

                    return (
                      <tr key={i} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                        <td style={{ padding: "10px 0", fontFamily: "var(--font-mono, monospace)", fontWeight: 700 }}>
                          {pos.symbol}
                        </td>
                        <td>
                          <span style={{
                            color: pos.side === "LONG" ? "var(--accent-profit)" : "var(--accent-loss)",
                            fontWeight: 600,
                          }}>
                            {pos.side}
                          </span>
                        </td>
                        <td style={{ color: "var(--text-secondary)" }}>{fmt(pos.size, 4)}</td>
                        <td style={{ fontFamily: "var(--font-mono, monospace)" }}>${fmt(pos.entry_price)}</td>
                        <td style={{ fontFamily: "var(--font-mono, monospace)" }}>${fmt(pos.current_price)}</td>
                        <td style={{ color: pnlColor(pos.unrealized_pnl), fontWeight: 600 }}>
                          {fmtDollar(pos.unrealized_pnl)}
                        </td>
                        <td>
                          {stopDist != null ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              <div style={{ width: 48, height: 4, background: "var(--border-subtle)", borderRadius: 2, overflow: "hidden" }}>
                                <div style={{
                                  width: `${stopPct}%`, height: "100%", borderRadius: 2,
                                  background: stopDist < 2 ? "var(--accent-loss)" : stopDist < 5 ? "#f59e0b" : "var(--accent-profit)",
                                }} />
                              </div>
                              <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{fmt(stopDist, 1)}%</span>
                            </div>
                          ) : (
                            <span style={{ color: "var(--text-tertiary)" }}>—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* Agent performance mini-table */}
          <div className="glass-panel" style={{ padding: "18px 20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Agent Performance
              </div>
              <Link href="/agents" style={{ fontSize: 11, color: "var(--accent-info)", textDecoration: "none" }}>
                Details →
              </Link>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {agents.length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>Loading agents…</div>
              ) : (
                agents.slice(0, 8).map(ag => (
                  <div key={ag.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{
                        width: 6, height: 6, borderRadius: "50%",
                        background: ag.status === "active" ? "var(--accent-profit)" : "var(--border-subtle)",
                      }} />
                      <span style={{ fontSize: 12, color: "var(--text-primary)" }}>{ag.name}</span>
                    </div>
                    <span style={{
                      fontSize: 12, fontFamily: "var(--font-mono, monospace)",
                      color: ag.elo >= 1200 ? "var(--accent-profit)" : "var(--text-secondary)",
                    }}>
                      {ag.elo ? Math.round(ag.elo) : "—"}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Row 4: Redis stream activity log */}
        <div className="glass-panel" style={{ padding: "18px 20px" }}>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 12 }}>
            Live Activity Stream
          </div>
          <div style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 11, display: "flex", flexDirection: "column", gap: 3, maxHeight: 200, overflowY: "auto" }}>
            {events.length === 0 ? (
              <div style={{ color: "var(--text-tertiary)" }}>Connecting to stream…</div>
            ) : (
              events.map((ev, i) => (
                <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                  <span style={{ color: "var(--text-tertiary)", flexShrink: 0, fontSize: 10 }}>
                    {new Date(ev.ts).toLocaleTimeString()}
                  </span>
                  {ev.stream && (
                    <span style={{
                      color: streamColor(ev.stream), flexShrink: 0, fontSize: 10,
                      padding: "1px 5px", borderRadius: 3, background: "rgba(255,255,255,0.05)",
                    }}>
                      {ev.stream.replace("stream:", "")}
                    </span>
                  )}
                  <span style={{ color: levelColor(ev.level), lineHeight: 1.4 }}>{ev.msg}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* ── Right sidebar ── */}
      <div style={{
        width: 220, minHeight: "100%", background: "var(--bg-base)",
        borderLeft: "1px solid var(--border-subtle)", padding: "20px 14px",
        display: "flex", flexDirection: "column", gap: 16, overflowY: "auto",
        flexShrink: 0,
      }}>
        {/* Asset class tabs */}
        <div style={{ display: "flex", gap: 4 }}>
          {ASSET_TABS.map(tab => (
            <button
              key={tab}
              onClick={() => setAssetTab(tab)}
              style={{
                flex: 1, padding: "5px 0", fontSize: 10, fontWeight: 600,
                border: "1px solid var(--border-subtle)", borderRadius: 4, cursor: "pointer",
                background: assetTab === tab ? "rgba(99,102,241,0.15)" : "transparent",
                color: assetTab === tab ? "var(--accent-info)" : "var(--text-tertiary)",
                textTransform: "uppercase", letterSpacing: "0.06em",
              }}
            >
              {tab.slice(0, 5)}
            </button>
          ))}
        </div>

        {/* Mini price charts */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {currentTabPrices.map(sp => (
            <div key={sp.symbol} style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "8px 10px", borderRadius: 6, background: "rgba(255,255,255,0.03)",
              border: "1px solid var(--border-subtle)",
            }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)" }}>{sp.name}</span>
                <span style={{ fontSize: 10, color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>
                  ${sp.price >= 1000 ? fmt(sp.price, 0) : fmt(sp.price, 2)}
                </span>
                <span style={{
                  fontSize: 10, fontWeight: 600,
                  color: sp.change_pct >= 0 ? "var(--accent-profit)" : "var(--accent-loss)",
                }}>
                  {sp.change_pct >= 0 ? "+" : ""}{fmt(sp.change_pct, 2)}%
                </span>
              </div>
              <Sparkline data={sp.history} positive={sp.change_pct >= 0} />
            </div>
          ))}
        </div>

        {/* Top Polymarket signal */}
        <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 14 }}>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>
            Polymarket Top Signal
          </div>
          <Link href="/polymarket" style={{ textDecoration: "none" }}>
            <div style={{
              padding: "10px 12px", borderRadius: 6, cursor: "pointer",
              background: "rgba(99,102,241,0.08)", border: "1px solid rgba(99,102,241,0.2)",
            }}>
              <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 6 }}>
                Fed rate cut by June?
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 18, fontWeight: 700, color: "var(--accent-info)", fontFamily: "var(--font-mono, monospace)" }}>
                  62%
                </span>
                <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
                  $2.4M vol
                </span>
              </div>
            </div>
          </Link>
        </div>
      </div>
    </div>
  );
}
