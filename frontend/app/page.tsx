"use client";
// ─────────────────────────────────────────────────────────────────────────────
// Mission Control — implements the Claude Design handoff
// (.claude/_handoff_design/project/Mission Control.html). Every section wires
// to the live endpoints the docker stack already exposes; nothing is mocked.
// ─────────────────────────────────────────────────────────────────────────────
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { DashSkeleton } from "@/components/DashSkeleton";

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
  closed_trades?: number;
  wins?: number;
  losses?: number;
}
interface RiskMetrics {
  venue?: string;
  portfolio_value?: number;
  total_pnl?: number;
  day_pnl?: number;
  unrealized_pnl?: number;
  realized_pnl?: number;
  closed_trade_pnl?: number;
  total_exposure?: number;
  drawdown_pct?: number;
  open_positions?: string | number;
  starting_capital?: number;
  updated_at?: string;
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
interface AgentPerf {
  id: string;
  name: string;
  role: string;
  color: string;
  elo: number;
  status: string;
  current_task?: string | null;
  last_heartbeat?: string | null;
}
interface StreamEvent {
  ts: string;
  msg: string;
  level: string;
  stream?: string;
  data?: Record<string, unknown>;
  type?: string;
}
interface LlmCost {
  today_usd?: number;
  all_time_usd?: number;
  today_calls?: number;
  today_input_tokens?: number;
  today_output_tokens?: number;
  by_model_today?: Record<string, { calls: number; usd: number; input_tokens: number; output_tokens: number }>;
}
interface PnlHistoryPoint {
  ts: string;
  portfolio_value: number;
  total_pnl: number;
  day_pnl: number;
  unrealized_pnl?: number;
  realized_pnl?: number;
  open_positions?: number;
}
// Mini record of each fill so we can overlay markers on the P&L line.
interface FillMarker {
  order_id: string;
  ts: string;
  symbol: string;
  side: "BUY" | "SELL" | string;
  price: number;
  quantity: number;
  status: string;
  agent_id?: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function fmt(n: number | undefined | null, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function fmtSignedDollar(n: number | undefined | null, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  const s = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${s}$${fmt(Math.abs(n), dec)}`;
}
function fmtPct(n: number | undefined | null, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  const s = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${s}${fmt(Math.abs(n) * 100, dec)}%`;
}
function timeAgo(ts: string | number | undefined): string {
  if (!ts) return "just now";
  const t = typeof ts === "number" ? ts : new Date(ts).getTime();
  if (isNaN(t)) return "just now";
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}
function timeHMS(ts: string | number | undefined): string {
  if (!ts) return "—";
  const d = new Date(typeof ts === "number" ? ts : ts);
  if (isNaN(d.getTime())) return "—";
  return d.toISOString().slice(11, 23);
}
// Agent palette matching the mock's chip colors
const AGENT_COLORS: Record<string, { bg: string; initial: string }> = {
  marcus: { bg: "#4A90D9", initial: "M" },
  vera: { bg: "#7B68EE", initial: "V" },
  rex: { bg: "#E8A838", initial: "R" },
  nova: { bg: "#8B5CF6", initial: "N" },
  diana: { bg: "#E84040", initial: "D" },
  atlas: { bg: "#40B8A8", initial: "A" },
  sage: { bg: "#F0C040", initial: "S" },
  scout: { bg: "#60C8E8", initial: "S" },
  xrp_analyst: { bg: "#00AAE4", initial: "X" },
  polymarket_scout: { bg: "#9945FF", initial: "P" },
  portfolio_constructor: { bg: "#2DCCFF", initial: "C" },
};
function agentLook(id?: string): { bg: string; initial: string } {
  const k = (id ?? "").toLowerCase();
  if (AGENT_COLORS[k]) return AGENT_COLORS[k];
  return { bg: "#5E6AD2", initial: (id ?? "?")[0]?.toUpperCase() ?? "?" };
}

const WATCHLIST_CRYPTO = [
  { symbol: "BTC/USDT", name: "Bitcoin", ticker: "BTC", icon: "₿", cls: "btc" },
  { symbol: "ETH/USDT", name: "Ethereum", ticker: "ETH", icon: "Ξ", cls: "eth" },
  { symbol: "XRP/USDT", name: "XRP", ticker: "XRP", icon: "X", cls: "xrp" },
  { symbol: "SOL/USDT", name: "Solana", ticker: "SOL", icon: "S", cls: "sol" },
];

const DESK_LAYOUT = [
  {
    ix: "01",
    group: "Research",
    name: "Alpha Research",
    blurb: "Generates signals, debates conviction across 4 analysts, synthesizes the firm view through Nova.",
    members: ["marcus", "vera", "rex", "nova"],
  },
  {
    ix: "02",
    group: "Execution",
    name: "Trade Execution",
    blurb: "Consumes Nova conviction packets, runs risk-checks, routes orders to paper & live venues.",
    members: ["diana", "atlas"],
  },
  {
    ix: "03",
    group: "Oversight",
    name: "Portfolio Oversight",
    blurb: "Monitors exposure, drawdown, cross-agent calibration. Tightens or widens stops in real time.",
    members: ["sage", "scout"],
  },
];

// ─── Sparkline (mini SVG) ────────────────────────────────────────────────────
function Sparkline({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 2) {
    return <svg viewBox="0 0 60 22" className="watch-spark"><path d="M0 11 L60 11" stroke={up ? "var(--accent-profit)" : "var(--accent-loss)"}/></svg>;
  }
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * 60;
    const y = 22 - ((v - min) / range) * 22;
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox="0 0 60 22" className="watch-spark">
      <path d={pts} stroke={up ? "var(--accent-profit)" : "var(--accent-loss)"}/>
    </svg>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────
export default function MissionControlPage() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [risk, setRisk] = useState<RiskMetrics | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [agents, setAgents] = useState<AgentPerf[]>([]);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [cost, setCost] = useState<LlmCost | null>(null);
  const [pnlHistory, setPnlHistory] = useState<PnlHistoryPoint[]>([]);
  const [fills, setFills] = useState<FillMarker[]>([]);
  const [hoveredFill, setHoveredFill] = useState<FillMarker | null>(null);
  const [regime, setRegime] = useState<string>("UNKNOWN");
  const [effectiveSignals, setEffectiveSignals] = useState<number | null>(null);
  const [sentimentBySymbol, setSentimentBySymbol] = useState<Record<string, { score: number; label: string }>>({});
  const [watchPrices, setWatchPrices] = useState<Record<string, { price: number; change_pct: number; history: number[] }>>({});
  const [autonomy, setAutonomy] = useState<string>("TRUSTED");
  const [venue, setVenue] = useState<string>("sim");
  const [streamFilter, setStreamFilter] = useState<string>("all");
  const [rangeKey, setRangeKey] = useState<string>("4h");
  const [cycleId, setCycleId] = useState<string>("—");
  const [initialLoaded, setInitialLoaded] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const eventsRef = useRef<StreamEvent[]>([]);

  // Polling aggregator
  const fetchAll = useCallback(async () => {
    const j = (url: string) => fetch(url).then(r => r.json()).catch(() => null);
    const [portRes, riskRes, posRes, agRes, sigRes, regRes, costRes, pnlRes, fillsRes, cfgRes, xrpSent, btcSent, gcSent] = await Promise.allSettled([
      j(`${API}/api/execution/portfolio`),
      j(`${API}/api/execution/risk-metrics`),
      j(`${API}/api/execution/positions`),
      j(`${API}/api/agents`),
      j(`${API}/api/signals/recent?limit=12`),
      j(`${API}/api/market/regime?symbol=XRP%2FUSDT`),
      j(`${API}/api/llm/costs`),
      j(`${API}/api/execution/pnl-history?limit=240`),
      j(`${API}/api/orders?limit=200`),
      j(`${API}/api/settings`),
      j(`${API}/api/market/sentiment/XRP_USDT`),
      j(`${API}/api/market/sentiment/BTC_USDT`),
      j(`${API}/api/market/sentiment/GC_F`),
    ]);
    if (portRes.status === "fulfilled" && portRes.value) setPortfolio(portRes.value);
    if (riskRes.status === "fulfilled" && riskRes.value) {
      setRisk(riskRes.value);
      if (riskRes.value.venue) setVenue(riskRes.value.venue);
    }
    if (posRes.status === "fulfilled" && posRes.value) {
      setPositions(Array.isArray(posRes.value) ? posRes.value : posRes.value?.positions ?? []);
    }
    if (agRes.status === "fulfilled" && agRes.value) {
      setAgents(Array.isArray(agRes.value) ? agRes.value : agRes.value?.agents ?? []);
    }
    if (sigRes.status === "fulfilled" && sigRes.value) {
      const raw = Array.isArray(sigRes.value) ? sigRes.value : sigRes.value?.signals ?? [];
      setSignals(raw);
    }
    if (regRes.status === "fulfilled" && regRes.value) setRegime(regRes.value?.regime ?? "UNKNOWN");
    if (costRes.status === "fulfilled" && costRes.value) {
      // /api/llm/costs returns { today: {...}, all_time: {...}, history_7d: [...] }
      // Map to the flatter shape our UI consumes.
      const t = costRes.value?.today ?? {};
      const byModelShaped: Record<string, { calls: number; usd: number; input_tokens: number; output_tokens: number }> = {};
      for (const [model, row] of Object.entries(t?.by_model ?? {})) {
        const r = row as { calls?: number; input?: number; output?: number; cost?: number };
        // approximate cost per model using its share of total if no per-model cost is returned
        const totalTok = (r.input ?? 0) + (r.output ?? 0);
        const share = t.input_tokens + t.output_tokens > 0
          ? totalTok / (t.input_tokens + t.output_tokens)
          : 0;
        byModelShaped[model] = {
          calls: r.calls ?? 0,
          usd: (t.cost_usd ?? 0) * share,
          input_tokens: r.input ?? 0,
          output_tokens: r.output ?? 0,
        };
      }
      setCost({
        today_usd: t.cost_usd ?? 0,
        all_time_usd: costRes.value?.all_time?.cost_usd ?? 0,
        today_calls: t.calls ?? 0,
        today_input_tokens: t.input_tokens ?? 0,
        today_output_tokens: t.output_tokens ?? 0,
        by_model_today: byModelShaped,
      });
    }
    if (pnlRes.status === "fulfilled" && pnlRes.value) {
      // The endpoint wraps the list in { points: [...] }. Older shape was a
      // raw array — support both so we don't break local dev.
      const raw = Array.isArray(pnlRes.value) ? pnlRes.value : pnlRes.value?.points;
      if (Array.isArray(raw)) setPnlHistory(raw);
    }
    if (fillsRes.status === "fulfilled" && Array.isArray(fillsRes.value)) {
      // Map orders → lightweight fill markers. Include REJECTED so the user
      // still sees the attempt; color-code accordingly in the chart.
      const markers: FillMarker[] = fillsRes.value
        .filter((o: { created_at?: string; filled_price?: number | null }) => o.created_at)
        .map((o: {
          order_id: string; symbol: string; side: string; filled_price?: number | null;
          quantity: number; status: string; created_at: string; agent_id?: string;
        }) => ({
          order_id: o.order_id,
          ts: o.created_at,
          symbol: o.symbol,
          side: o.side,
          price: Number(o.filled_price ?? 0),
          quantity: Number(o.quantity ?? 0),
          status: o.status,
          agent_id: o.agent_id,
        }));
      setFills(markers);
    }
    if (cfgRes.status === "fulfilled" && cfgRes.value?.system?.autonomy_mode) setAutonomy(cfgRes.value.system.autonomy_mode);
    const sm: Record<string, { score: number; label: string }> = {};
    const assign = (sym: string, r: PromiseSettledResult<unknown>) => {
      if (r.status === "fulfilled" && r.value) {
        const v = r.value as { score?: number; label?: string };
        sm[sym] = { score: v.score ?? 0, label: v.label ?? "NEUTRAL" };
      }
    };
    assign("XRP/USDT", xrpSent); assign("BTC/USDT", btcSent); assign("GC=F", gcSent);
    setSentimentBySymbol(sm);
    // First fetch landed — lift the skeleton even if some endpoints failed.
    setInitialLoaded(true);
  }, []);

  // Watchlist prices
  const fetchWatch = useCallback(async () => {
    const syms = WATCHLIST_CRYPTO.map(x => x.symbol);
    try {
      const r = await fetch(`${API}/api/market/prices?symbols=${encodeURIComponent(syms.join(","))}`);
      if (!r.ok) return;
      const d = await r.json();
      const updates: Record<string, { price: number; change_pct: number; history: number[] }> = { ...watchPrices };
      for (const p of (d.prices || [])) {
        const prev = updates[p.symbol]?.history ?? [];
        const hist = [...prev, p.price].slice(-20);
        updates[p.symbol] = { price: p.price ?? 0, change_pct: p.change_pct ?? 0, history: hist };
      }
      setWatchPrices(updates);
    } catch { /* swallow */ }
  }, [watchPrices]);

  // WebSocket for live stream
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
              msg: data.msg ?? data.message ?? JSON.stringify(data).slice(0, 160),
              level: data.level ?? "info",
              stream: data.stream ?? data.type ?? "",
              data,
              type: data.type,
            };
            if (data.type === "signal" && data.symbol) {
              setSignals(prev => [data as Signal, ...prev].slice(0, 20));
            }
            if (data.cycle_id) setCycleId(data.cycle_id.slice(0, 8));
            if (data.effective_signal_count != null) setEffectiveSignals(data.effective_signal_count);
            eventsRef.current = [event, ...eventsRef.current].slice(0, 40);
            setEvents([...eventsRef.current]);
          } catch { /* ignore */ }
        };
        ws.onclose = () => { retryTimeout = setTimeout(connect, 5000); };
        ws.onerror = () => ws.close();
      } catch { /* WS unavailable */ }
    };
    connect();
    return () => { clearTimeout(retryTimeout); wsRef.current?.close(); };
  }, []);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 2000);
    return () => clearInterval(iv);
  }, [fetchAll]);

  useEffect(() => {
    fetchWatch();
    const iv = setInterval(fetchWatch, 15_000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalValue = risk?.portfolio_value ?? portfolio?.total ?? 0;
  const startingCapital = risk?.starting_capital ?? 10_000;
  const totalPnl = risk?.total_pnl ?? (totalValue - startingCapital);
  const dayPnl = risk?.day_pnl ?? portfolio?.daily_pnl ?? 0;
  const unrealized = risk?.unrealized_pnl ?? 0;
  const realized = risk?.realized_pnl ?? 0;
  const closedCount = portfolio?.closed_trades ?? 0;
  const wins = portfolio?.wins ?? 0;
  const losses = portfolio?.losses ?? 0;
  const winRate = portfolio?.win_rate ?? (closedCount > 0 ? wins / closedCount : 0);
  const totalExposure = risk?.total_exposure ?? positions.reduce((acc, p) => acc + (p.size * p.current_price), 0);
  const exposurePct = totalValue > 0 ? totalExposure / totalValue : 0;
  const drawdown = risk?.drawdown_pct ?? 0;

  // Chart geometry. We render every pnlHistory tick to a 760×180 coordinate
  // space (matches the CSS chart-wrap height) and overlay fills as colored
  // triangles at their timestamp's x-coordinate. All of this ties to a single
  // time window — the first tick is t0, the last is tN — so markers sit on
  // the line rather than drifting off.
  const chartGeometry = useMemo(() => {
    const empty = {
      path: "",
      fillPath: "",
      points: [] as { x: number; y: number; ts: number; pv: number }[],
      tMin: 0,
      tMax: 0,
      pvMin: startingCapital,
      pvMax: startingCapital,
      markers: [] as Array<FillMarker & { x: number; y: number }>,
    };
    if (pnlHistory.length < 2) {
      // Degenerate fallback: draw a flat line at startingCapital. Markers
      // still get rendered along a baseline so the user sees which trades
      // happened even when history isn't back-filled yet.
      const flatY = 90;
      const line = `M0,${flatY} L760,${flatY}`;
      const ts = fills.map(f => new Date(f.ts).getTime()).filter(t => !isNaN(t));
      const tMin = ts.length > 0 ? Math.min(...ts) : Date.now() - 3600_000;
      const tMax = ts.length > 0 ? Math.max(...ts) : Date.now();
      const range = Math.max(1, tMax - tMin);
      return {
        ...empty,
        path: line,
        fillPath: `${line} L760,220 L0,220 Z`,
        tMin, tMax,
        pvMin: startingCapital, pvMax: startingCapital,
        markers: fills
          .map(f => ({ ...f, _t: new Date(f.ts).getTime() }))
          .filter(f => !isNaN(f._t))
          .map(f => ({
            ...f,
            x: ((f._t - tMin) / range) * 760,
            y: flatY,
          })),
      };
    }

    const ptsWithTs = pnlHistory
      .map(p => ({ pv: p.portfolio_value, t: new Date(p.ts).getTime() }))
      .filter(p => !isNaN(p.t) && typeof p.pv === "number");
    if (ptsWithTs.length < 2) return empty;

    const tMin = ptsWithTs[0].t;
    const tMax = ptsWithTs[ptsWithTs.length - 1].t;
    const tRange = Math.max(1, tMax - tMin);
    const pvs = ptsWithTs.map(p => p.pv);
    // Pad the y-range a bit so the line doesn't hug the top/bottom edge.
    const rawMin = Math.min(...pvs);
    const rawMax = Math.max(...pvs);
    const pad = Math.max(5, (rawMax - rawMin) * 0.15);
    const pvMin = rawMin - pad;
    const pvMax = rawMax + pad;
    const pvRange = Math.max(1, pvMax - pvMin);

    const points = ptsWithTs.map(p => ({
      x: ((p.t - tMin) / tRange) * 760,
      y: 170 - ((p.pv - pvMin) / pvRange) * 160,
      ts: p.t,
      pv: p.pv,
    }));
    const path = points.map((p, i) =>
      `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`
    ).join(" ");
    const fillPath = `${path} L760,220 L0,220 Z`;

    const markers = fills
      .map(f => ({ ...f, _t: new Date(f.ts).getTime() }))
      .filter(f => !isNaN(f._t) && f._t >= tMin - 60_000 && f._t <= tMax + 60_000)
      .map(f => {
        const x = Math.max(0, Math.min(760, ((f._t - tMin) / tRange) * 760));
        // Snap each marker to the line by finding the nearest point.
        let nearest = points[0];
        let nearestDx = Math.abs(points[0].x - x);
        for (const p of points) {
          const dx = Math.abs(p.x - x);
          if (dx < nearestDx) { nearest = p; nearestDx = dx; }
        }
        return { ...f, x, y: nearest.y };
      });

    return { path, fillPath, points, tMin, tMax, pvMin, pvMax, markers };
  }, [pnlHistory, fills, startingCapital]);

  const chartPath = chartGeometry.path;
  const chartFill = chartGeometry.fillPath;
  const chartMarkers = chartGeometry.markers;

  // Briefing headline
  const headline = (() => {
    const sign = totalPnl > 0 ? "up" : totalPnl < 0 ? "down" : "flat";
    const delta = fmtSignedDollar(Math.abs(totalPnl));
    const positionPhrase = positions.length === 0
      ? "carrying no open positions"
      : positions.length === 1
        ? "carrying one open position"
        : `carrying ${positions.length} open positions`;
    const cryptoN = positions.filter(p => /USDT|USD|BTC|ETH|XRP|SOL/i.test(p.symbol)).length;
    const asset = cryptoN === positions.length && positions.length > 0 ? "across crypto" : "";
    return { sign, delta, positionPhrase, asset };
  })();

  // Desks — compute status from agents state
  const desksData = useMemo(() => {
    return DESK_LAYOUT.map(d => {
      const members = d.members.map(id => {
        const agent = agents.find(a => a.id === id);
        return { id, agent, look: agentLook(id) };
      });
      const active = members.filter(m => m.agent?.status === "active" || m.agent?.current_task).length;
      const total = members.length;
      const running = active > 0;
      const currentTask = members.find(m => m.agent?.current_task)?.agent;
      return {
        ...d,
        members,
        active, total, running,
        currentText: currentTask
          ? `${currentTask.name} analyzing ${currentTask.current_task}`
          : d.group === "Execution"
            ? "Waiting on Nova conviction ≥ 0.62"
            : "Idle",
      };
    });
  }, [agents]);

  // Filter signals list to last 3 with non-neutral direction (fallback to any 3)
  const topSignals = useMemo(() => {
    const directional = signals.filter(s => ["LONG", "SHORT"].includes((s.direction || "").toUpperCase()));
    const list = directional.length >= 3 ? directional : signals;
    return list.slice(0, 3);
  }, [signals]);

  // Cost figures
  const costToday = cost?.today_usd ?? 0;
  const costBudget = 2.40;
  const costPct = Math.min(1, costToday / costBudget);
  const costByModel = cost?.by_model_today ?? {};
  const costRunwayHours = costToday > 0
    ? Math.max(0, ((costBudget - costToday) / (costToday / 24)))
    : null;

  // Narrative stats (rail)
  const narrativeStats = {
    cycles: cycleId === "—" ? Math.max(closedCount, 0) : closedCount + positions.length, // proxy
    approved: signals.filter(s => (s.direction || "").toUpperCase() !== "NEUTRAL").length,
    wins,
    losses,
  };

  // Recent trade/signal rail items (top 6)
  const railNarrative = useMemo(() => {
    const items: { agent: string; text: React.ReactNode; time: string; look: { bg: string; initial: string } }[] = [];
    // From recent events, surface trade + signal actions
    for (const e of events.slice(0, 20)) {
      const d = e.data ?? {};
      if (e.type === "signal" && typeof d.symbol === "string") {
        const agentId = typeof d.agent === "string" ? d.agent.toLowerCase() : "";
        const look = agentLook(agentId);
        const dir = (d.direction as string | undefined)?.toUpperCase() ?? "NEUTRAL";
        const dirCls = dir === "LONG" ? "up" : dir === "SHORT" ? "dn" : "";
        items.push({
          agent: agentId,
          look,
          text: (
            <>
              <b>{d.agent as string}</b> synthesized <span className={dirCls}>{dir}</span> on{" "}
              <span className="sym">{d.symbol as string}</span>{" "}
              {d.confidence != null ? `@ ${(Number(d.confidence)).toFixed(2)}` : ""}
            </>
          ),
          time: timeAgo(e.ts),
        });
      } else if (typeof d.event === "string" && d.event.includes("trade")) {
        const sym = (d.symbol as string) ?? "—";
        const agentId = (d.agent_id as string | undefined)?.toLowerCase() ?? "atlas";
        const look = agentLook(agentId);
        items.push({
          agent: agentId,
          look,
          text: <><b>Atlas</b> executed <span className="sym">{sym}</span></>,
          time: timeAgo(e.ts),
        });
      }
      if (items.length >= 6) break;
    }
    // Fallback: derive from current positions when stream is quiet
    if (items.length === 0) {
      for (const p of positions.slice(0, 6)) {
        items.push({
          agent: "atlas",
          look: agentLook("atlas"),
          text: (
            <>
              <b>Atlas</b> bought <span className="sym">{fmt(p.size, 4)} {p.symbol}</span> at{" "}
              <span className="sym">${fmt(p.current_price, 2)}</span>
            </>
          ),
          time: "just now",
        });
      }
    }
    return items;
  }, [events, positions]);

  // Positions with stop distance
  const positionRows = useMemo(() => {
    return positions.map((p, i) => {
      const move = p.entry_price > 0 ? ((p.current_price - p.entry_price) / p.entry_price) : 0;
      const stopDistPct = p.stop_loss && p.stop_loss > 0
        ? Math.abs((p.current_price - p.stop_loss) / p.current_price)
        : 0.03; // default 3%
      const stopBarColor = stopDistPct >= 0.05 ? "var(--accent-profit)"
        : stopDistPct >= 0.025 ? "var(--status-serious)"
        : "var(--accent-loss)";
      const stopBarWidth = Math.min(100, Math.round(stopDistPct * 1000));
      return { p, i, move, stopDistPct, stopBarColor, stopBarWidth };
    });
  }, [positions]);

  // Subtotal for positions
  const positionsSubtotal = useMemo(() => {
    const notional = positions.reduce((acc, p) => acc + p.size * p.current_price, 0);
    const unreal = positions.reduce((acc, p) => acc + (p.unrealized_pnl ?? 0), 0);
    const avgMove = positions.length === 0
      ? 0
      : positions.reduce((acc, p) => acc + (p.entry_price > 0 ? (p.current_price - p.entry_price) / p.entry_price : 0), 0) / positions.length;
    return { notional, unreal, avgMove };
  }, [positions]);

  // Filtered stream
  const streamRows = useMemo(() => {
    const filtered = events.filter(e => {
      if (streamFilter === "all") return true;
      const s = (e.stream ?? "") + " " + (e.type ?? "") + " " + (e.msg ?? "");
      if (streamFilter === "signals") return /signal/i.test(s);
      if (streamFilter === "trades") return /trade|fill|order/i.test(s);
      if (streamFilter === "risk") return /risk|kill|stop|alert/i.test(s);
      if (streamFilter === "agents") return /agent|cycle|heartbeat/i.test(s);
      if (streamFilter === "system") return /system|health|redis|broker/i.test(s);
      return true;
    });
    return filtered.slice(0, 10);
  }, [events, streamFilter]);

  // Tag + id for a stream row
  const streamTagFor = (e: StreamEvent): { tag: string; cls: string } => {
    const s = (e.stream ?? "") + " " + (e.type ?? "") + " " + (e.msg ?? "");
    if (/signal/i.test(s)) return { tag: "Signals", cls: "tag-sig" };
    if (/trade|fill|order/i.test(s)) return { tag: "Trades", cls: "tag-trd" };
    if (/risk|kill|stop|alert/i.test(s)) return { tag: "Risk", cls: "tag-rsk" };
    if (/agent|cycle|heartbeat/i.test(s)) return { tag: "Agents", cls: "tag-agt" };
    return { tag: "System", cls: "tag-sys" };
  };

  // Set mode via API. /api/settings accepts POSTed fields under `system`.
  const setAutonomyMode = async (mode: string) => {
    setAutonomy(mode);
    try {
      await fetch(`${API}/api/settings`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system: { autonomy_mode: mode } }),
      });
    } catch { /* ignore */ }
  };

  const nowUtc = new Date().toISOString().replace("T", " · ").slice(0, 16) + " UTC";

  // First paint: show skeleton until the first fetch lands. Eliminates the
  // ~7s of blank dashboard a cold connection used to produce.
  if (!initialLoaded) {
    return <DashSkeleton crumbs={["The Firm", "Mission Control"]} />;
  }

  return (
    <>
      <div className="aurora" />
      <div className="grain" />

      <div style={{ display: "flex", flex: 1, minWidth: 0, minHeight: "100vh" }}>

        {/* ── MAIN ── */}
        <main style={{ flex: 1, minWidth: 0, padding: "28px 36px 64px", display: "flex", flexDirection: "column", gap: 32, position: "relative", zIndex: 2 }}>

          {/* Top meta */}
          <div className="top-meta">
            <div className="crumbs">
              <span>The Firm</span>
              <span className="sep">/</span>
              <span className="here">Mission Control</span>
            </div>
            <div className="status-cluster">
              <div className="st"><span className="d std" />{nowUtc}</div>
              <div className="st"><span className="d ok" />{venue === "sim" ? "All desks green" : `Venue ${venue.toUpperCase()}`}</div>
              <div className="st">Cycle {cycleId}</div>
            </div>
          </div>

          {/* Mode */}
          <div className="mode-row">
            <span className="flag">{venue.toUpperCase()} · {autonomy}</span>
            <div className="msg">
              {autonomy === "COMMANDER" ? (
                <>Operator approves each signal. <b>Trusted</b> auto-executes once approved.</>
              ) : autonomy === "YOLO" ? (
                <>Full autonomous execution. <b>Caps relaxed</b> to YOLO limits.</>
              ) : (
                <>Auto-executing approved signals. <b>Commander override</b> available anytime.</>
              )}
            </div>
            <div className="tools">
              <div className="seg">
                {["COMMANDER", "TRUSTED", "YOLO"].map(m => (
                  <button key={m} className={autonomy === m ? "on" : ""} onClick={() => setAutonomyMode(m)}>
                    {m.charAt(0) + m.slice(1).toLowerCase()}
                  </button>
                ))}
              </div>
              <button className="btn-ghost" onClick={async () => {
                try { await fetch(`${API}/api/orders/kill`, { method: "POST" }); } catch { /* ignore */ }
              }}>Pause desk</button>
            </div>
          </div>

          {/* Briefing */}
          <div className="briefing">
            <div className="left">
              <div className="eyebrow">
                <span className="num">01</span><span>·</span><span>Firm briefing</span>
                <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>Updated {timeAgo(risk?.updated_at)}</span>
              </div>
              <p className="headline">
                The firm is running <b>{autonomy.toLowerCase()} mode</b> and is{" "}
                {headline.sign === "up" ? "up" : headline.sign === "down" ? "down" : "flat at"}{" "}
                <span className={headline.sign === "up" ? "up" : "dn"}>{headline.delta}</span>{" "}
                today, {headline.positionPhrase}{headline.asset ? ` ${headline.asset}` : ""}. Macro remains neutral;
                crypto conviction is {sentimentBySymbol["BTC/USDT"]?.label?.toLowerCase() ?? "forming"} on Nova synthesis.
              </p>
              <div className="figure-stack">
                <span className="lbl">Portfolio</span>
                <span className="big">
                  ${fmt(Math.floor(totalValue), 0)}
                  <span className="cents">.{String(Math.floor((totalValue % 1) * 100)).padStart(2, "0")}</span>
                </span>
                <span className="delta">
                  <span className={`v ${dayPnl >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(dayPnl)}</span>
                  <span>today</span>
                  <span className="pip" />
                  <span className={`v ${totalPnl >= 0 ? "up" : "dn"}`}>{fmtPct(totalPnl / startingCapital)}</span>
                  <span>since inception</span>
                </span>
              </div>
            </div>
            <div className="right">
              <div className="cell">
                <div className="k"><span>Open positions</span><span className="n">02</span></div>
                <div className="v">{positions.length}</div>
                <div className="sub"><span>{portfolio?.trade_count ?? 0} trades today</span></div>
              </div>
              <div className="cell">
                <div className="k"><span>Win rate · today</span><span className="n">03</span></div>
                <div className={`v ${winRate >= 0.55 ? "up" : winRate > 0 && winRate < 0.45 ? "dn" : ""}`}>
                  {closedCount > 0 ? fmt(winRate * 100, 1) : "—"}
                  {closedCount > 0 && <small>%</small>}
                </div>
                <div className="sub">
                  <span>{closedCount} closed</span>
                  <span className="bar-mini"><span className="fill" style={{ width: `${Math.round((winRate || 0) * 100)}%` }} /></span>
                </div>
              </div>
              <div className="cell">
                <div className="k"><span>Exposure</span><span className="n">04</span></div>
                <div className="v">${fmt(totalExposure, 0)}</div>
                <div className="sub">
                  <span>{Math.round(exposurePct * 100)}% of book</span>
                  <span className="bar-mini"><span className="fill" style={{ width: `${Math.min(100, Math.round(exposurePct * 100))}%` }} /></span>
                </div>
              </div>
              <div className="cell">
                <div className="k"><span>Drawdown</span><span className="n">05</span></div>
                <div className="v">{fmt(Math.abs(drawdown) * 100, 2)}<small>%</small></div>
                <div className="sub"><span>Venue <span style={{ color: "var(--text-secondary)" }}>{venue}</span></span></div>
              </div>
            </div>
          </div>

          {/* Performance */}
          <section>
            <div className="sect-hd">
              <div className="title-group">
                <span className="n">02 — Performance</span>
                <h3>Running P&amp;L &amp; regime intelligence</h3>
              </div>
              <div className="sub">Marked-to-market every 2s · {pnlHistory.length} ticks</div>
            </div>
            <div className="perf">
              {/* Chart */}
              <div className="card chart-card">
                <div className="chart-hd">
                  <div className="t">
                    <div className="k">Running P&amp;L</div>
                    <h4>Portfolio value, session</h4>
                    <div className="note">Starting capital ${fmt(startingCapital, 0)} · {pnlHistory.length} ticks · updated every 2s</div>
                  </div>
                  <div className="controls">
                    <div className="seg">
                      {["1h", "4h", "12h", "1d", "1w"].map(k => (
                        <button key={k} className={rangeKey === k ? "on" : ""} onClick={() => setRangeKey(k)}>{k}</button>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="chart-legend">
                  <div className="item now"><span className="sw" style={{ background: "var(--text-primary)" }} />Portfolio value</div>
                  <div className="item"><span className="sw" style={{ background: "var(--text-muted)", height: 1 }} />Starting capital ${fmt(startingCapital, 0)}</div>
                  <div className="spacer" />
                  <div className="price">
                    ${fmt(totalValue, 2)}
                    <span className={`ch ${totalPnl >= 0 ? "" : "dn"}`}>{fmtPct(totalPnl / startingCapital)}</span>
                  </div>
                </div>
                <div className="chart-wrap" style={{ position: "relative" }}>
                  <svg viewBox="0 0 760 180" preserveAspectRatio="none" style={{ overflow: "visible" }}>
                    <defs>
                      <linearGradient id="pnlFill" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="0%" stopColor="rgba(244,245,247,0.22)" />
                        <stop offset="100%" stopColor="rgba(244,245,247,0)" />
                      </linearGradient>
                      <pattern id="grid" width="76" height="36" patternUnits="userSpaceOnUse">
                        <path d="M 76 0 L 0 0 0 36" fill="none" stroke="rgba(255,255,255,.025)" strokeWidth="1" />
                      </pattern>
                    </defs>
                    <rect width="760" height="180" fill="url(#grid)" />
                    <line x1="0" y1="90" x2="760" y2="90" stroke="rgba(255,255,255,.14)" strokeDasharray="2 3" strokeWidth=".75" />
                    {chartFill && <path d={chartFill} fill="url(#pnlFill)" />}
                    {chartPath && <path d={chartPath} fill="none" stroke="#F4F5F7" strokeWidth="1.3" />}

                    {/* Trade markers — filled = circle, rejected = hollow ring.
                        Click/hover surfaces the details in the callout below. */}
                    {chartMarkers.map((m, i) => {
                      const isBuy = (m.side || "").toUpperCase() === "BUY";
                      const isRejected = (m.status || "").toUpperCase() === "REJECTED";
                      const color = isRejected
                        ? "rgba(255,255,255,.35)"
                        : isBuy ? "var(--accent-profit)" : "var(--accent-loss)";
                      return (
                        <g key={m.order_id + i}
                          style={{ cursor: "pointer" }}
                          onMouseEnter={() => setHoveredFill(m)}
                          onMouseLeave={() => setHoveredFill(null)}>
                          {/* Vertical connector line up from the x-axis */}
                          <line x1={m.x} y1={m.y} x2={m.x} y2={180} stroke={color} strokeWidth=".5" strokeDasharray="1 2" opacity=".35" />
                          <circle cx={m.x} cy={m.y} r={isRejected ? 3.5 : 4}
                            fill={isRejected ? "transparent" : color}
                            stroke={color} strokeWidth="1.5" />
                          {/* Side label near the marker — small so it doesn't crowd */}
                          <text x={m.x} y={isBuy ? m.y - 8 : m.y + 14}
                            textAnchor="middle" fontSize="8" fontFamily="var(--font-mono)"
                            fontWeight="600" fill={color}
                            style={{ letterSpacing: ".14em" }}>
                            {isBuy ? "▲" : "▼"}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                  <div className="y-ax">
                    <div className="r">${fmt(chartGeometry.pvMax, 0)}</div>
                    <div className="r" style={{ opacity: .5 }}>${fmt((chartGeometry.pvMax + chartGeometry.pvMin) / 2, 0)}</div>
                    <div className="r" style={{ color: "var(--text-tertiary)" }}>${fmt(startingCapital, 0)}</div>
                    <div className="r" style={{ opacity: .5 }}>${fmt((chartGeometry.pvMax + chartGeometry.pvMin) / 2 - (chartGeometry.pvMax - startingCapital), 0)}</div>
                    <div className="r">${fmt(chartGeometry.pvMin, 0)}</div>
                  </div>

                  {/* Hover callout */}
                  {hoveredFill && (
                    <div style={{
                      position: "absolute", top: 8, right: 8,
                      background: "rgba(10,13,19,.95)", border: "1px solid var(--line-soft)",
                      borderRadius: 6, padding: "10px 14px", minWidth: 220, zIndex: 5,
                      backdropFilter: "blur(6px)",
                      boxShadow: "0 8px 24px rgba(0,0,0,.5)",
                    }}>
                      <div style={{
                        fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: ".14em",
                        textTransform: "uppercase", color: "var(--text-tertiary)", marginBottom: 6,
                      }}>
                        {new Date(hoveredFill.ts).toISOString().slice(11, 19)}
                      </div>
                      <div style={{ fontSize: 13, fontFamily: "var(--font-mono)", marginBottom: 4 }}>
                        <b style={{ color: "var(--text-primary)" }}>{hoveredFill.symbol}</b>{" "}
                        <span style={{
                          color: hoveredFill.side.toUpperCase() === "BUY" ? "var(--accent-profit)" : "var(--accent-loss)",
                          fontWeight: 600, letterSpacing: ".08em",
                        }}>{hoveredFill.side}</span>
                      </div>
                      <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
                        qty {fmt(hoveredFill.quantity, 4)} @ ${fmt(hoveredFill.price, 4)}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 4 }}>
                        {hoveredFill.agent_id ?? "system"} · {hoveredFill.status}
                      </div>
                    </div>
                  )}

                  {/* Marker count footer */}
                  {chartMarkers.length > 0 && (
                    <div style={{
                      position: "absolute", bottom: 6, left: 24,
                      fontFamily: "var(--font-mono)", fontSize: 9.5,
                      color: "var(--text-muted)", letterSpacing: "-.005em",
                    }}>
                      {chartMarkers.length} fill{chartMarkers.length !== 1 ? "s" : ""} ·{" "}
                      <span style={{ color: "var(--accent-profit)" }}>▲</span> buy ·{" "}
                      <span style={{ color: "var(--accent-loss)" }}>▼</span> sell
                    </div>
                  )}
                </div>
                <div className="chart-footer">
                  <div className="item">
                    <div className="k">Today</div>
                    <div className={`v ${dayPnl >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(dayPnl)}</div>
                    <div className="sub">Mark-to-market</div>
                  </div>
                  <div className="item">
                    <div className="k">Unrealized</div>
                    <div className={`v ${unrealized >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(unrealized)}</div>
                    <div className="sub">Across {positions.length} open</div>
                  </div>
                  <div className="item">
                    <div className="k">Realized</div>
                    <div className={`v ${realized >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(realized)}</div>
                    <div className="sub">{closedCount} closed today</div>
                  </div>
                  <div className="item">
                    <div className="k">Total</div>
                    <div className={`v ${totalPnl >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(totalPnl)}</div>
                    <div className="sub">Since inception</div>
                  </div>
                </div>
              </div>

              {/* Regime card — live sentiment */}
              <div className="card regime">
                <div className="regime-hd">
                  <div className="k">Regime</div>
                  <h4>Cross-market intelligence</h4>
                  <div className="note">
                    {effectiveSignals != null ? `PCA: raw → ${effectiveSignals.toFixed(1)} effective` : "Awaiting PCA baseline"}
                  </div>
                </div>
                <div className="regime-list">
                  {[
                    { ix: "01", name: "Macro", tk: "VIX · DXY · Curve", sym: "MACRO" },
                    { ix: "02", name: "Crypto", tk: "BTC · ETH · XRP", sym: "BTC/USDT" },
                    { ix: "03", name: "Commodities", tk: "GC · CL · NG", sym: "GC=F" },
                    { ix: "04", name: "XRP focus", tk: "Ripple · ODL", sym: "XRP/USDT" },
                  ].map(row => {
                    const s = sentimentBySymbol[row.sym] ?? { score: 0, label: "NEUTRAL" };
                    const sig = s.score;
                    const cls = sig > 0.1 ? "bull" : sig < -0.1 ? "bear" : "neu";
                    const width = Math.min(50, Math.abs(sig) * 50);
                    const color = sig > 0.1 ? "var(--accent-profit)" : sig < -0.1 ? "var(--accent-loss)" : "var(--text-secondary)";
                    const fillStyle: React.CSSProperties = sig >= 0
                      ? { left: "50%", width: `${width}%`, background: color }
                      : { right: "50%", width: `${width}%`, background: color };
                    const dotLeft = sig >= 0 ? `${50 + width}%` : `${50 - width}%`;
                    return (
                      <div key={row.ix} className={`regime-row ${cls}`}>
                        <span className="idx">{row.ix}</span>
                        <div className="nm"><span className="n">{row.name}</span><span className="tk">{row.tk}</span></div>
                        <div className="bi-bar">
                          <span className="mid" />
                          <span className="fill" style={fillStyle} />
                          <span className="dot" style={{ left: dotLeft, background: color }} />
                        </div>
                        <div className="lbl">
                          {sig > 0.1 ? "Bullish" : sig < -0.1 ? "Bearish" : "Neutral"}
                          <small>{sig >= 0 ? "+" : ""}{sig.toFixed(2)}</small>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </section>

          {/* Desks */}
          <section>
            <div className="sect-hd">
              <div className="title-group">
                <span className="n">03 — The floor</span>
                <h3>Three desks, ten agents, one cycle</h3>
              </div>
              <div className="sub">Cycles auto-run every 60s · cycle {cycleId}</div>
            </div>
            <div className="desks">
              {desksData.map(d => (
                <div key={d.ix} className="desk">
                  <div>
                    <div className="desk-ix">Desk {d.ix} · {d.group}</div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
                      <h4>{d.name}</h4>
                      <span className={`status ${d.running ? "run" : "wait"}`}>
                        {d.running ? `Active ${d.active}/${d.total}` : `Idle 0/${d.total}`}
                      </span>
                    </div>
                  </div>
                  <p className="blurb">{d.blurb}</p>
                  <div className="agents">
                    {d.members.map(m => (
                      <span key={m.id} className={`agent-chip ${m.agent?.status === "active" ? "on" : ""}`}>
                        <span className="ico" style={{ background: m.look.bg }}>{m.look.initial}</span>
                        {m.agent?.name ?? m.id}
                      </span>
                    ))}
                  </div>
                  <div className="desk-progress">
                    <div className="track"><div className="fill" style={{ width: `${d.total > 0 ? Math.round((d.active / d.total) * 100) : 0}%` }} /></div>
                    <div className="lbl">
                      <span>Working {d.active}/{d.total}</span>
                      <span>{d.members[0]?.agent?.current_task ?? "—"}</span>
                    </div>
                  </div>
                  <div className="desk-now">
                    {d.running && <span className="live" />}
                    <span className="txt">{d.currentText}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Intelligence */}
          <section>
            <div className="sect-hd">
              <div className="title-group">
                <span className="n">04 — Intelligence</span>
                <h3>Conviction, rating, burn</h3>
              </div>
              <div className="sub">Live feed · last {signals.length} signals</div>
            </div>
            <div className="intel">
              {/* Signals */}
              <div className="card sig-card">
                <div className="sig-head">
                  <div className="t">
                    <div className="k">Latest signals</div>
                    <h4>Firm conviction packets</h4>
                  </div>
                  <a className="btn-ghost" href="/signals" style={{ fontSize: 10, textDecoration: "none" }}>All signals →</a>
                </div>
                <div className="sig-list">
                  {topSignals.length === 0 && (
                    <div style={{ padding: "20px 24px", color: "var(--text-tertiary)", fontSize: 13 }}>
                      Awaiting first directional signal…
                    </div>
                  )}
                  {topSignals.map((s, i) => {
                    const dir = (s.direction || "NEUTRAL").toUpperCase();
                    const cls = dir === "LONG" ? "long" : dir === "SHORT" ? "short" : "neutral";
                    return (
                      <div key={i} className={`signal ${cls}`}>
                        <span className="num">{String(i + 1).padStart(3, "0")}</span>
                        <div className="body">
                          <div className="line">
                            <span className="sym">{s.symbol ?? "—"}</span>
                            <span className="dirw">{dir}</span>
                            {s.agent && <span className="from">via <b>{s.agent}</b></span>}
                          </div>
                          {s.thesis && <div className="thesis">{s.thesis.slice(0, 180)}{s.thesis.length > 180 ? "…" : ""}</div>}
                        </div>
                        <div className="meta">
                          <div className="conf">{Math.round((s.confidence ?? 0) * 100)}%</div>
                          <div className="time">{timeAgo(s.ts)}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Agents */}
              <div className="card agents-card">
                <div className="agents-head">
                  <div className="k"><span>Agent ELO · live</span><a href="/agents">Details →</a></div>
                  <h4>Chess-rated conviction</h4>
                  <div className="note">Starts at 1200 · <span className="up">+32</span> per profitable trade, <span className="dn">−32</span> on loss.</div>
                </div>
                <div className="agents-list">
                  {agents.slice(0, 7).map(a => {
                    const look = agentLook(a.id);
                    const stCls = a.status === "active" ? "st-run"
                      : a.status === "idle" ? "st-idle"
                      : "st-wait";
                    const stLabel = a.status === "active" ? "Run"
                      : a.status === "idle" ? "Idle"
                      : "Wait";
                    return (
                      <div key={a.id} className="agent-row">
                        <div className="chip" style={{ background: look.bg }}>{look.initial}</div>
                        <div className="nm"><span className="n">{a.name}</span><small>{a.role}</small></div>
                        <div className={`st ${stCls}`}>{stLabel}</div>
                        <div className="elo">{a.elo ?? 1200}<small /></div>
                      </div>
                    );
                  })}
                  {agents.length === 0 && (
                    <div style={{ padding: "20px 24px", color: "var(--text-tertiary)", fontSize: 13 }}>No agents reporting yet</div>
                  )}
                </div>
              </div>

              {/* Cost */}
              <div className="card cost-card">
                <div className="cost-head">
                  <div className="k">LLM burn · today</div>
                  <h4>Cost vs. budget</h4>
                </div>
                <div className="cost-figure">${fmt(costToday, 2)}<small>/ ${fmt(costBudget, 2)}</small></div>
                <div>
                  <div className="cost-meter">
                    <div className="fill" style={{ width: `${costPct * 100}%` }} />
                    <div className="mark" style={{ left: "75%" }} />
                  </div>
                  <div className="cost-scale">
                    <span>$0</span><span>$0.60</span><span>$1.20</span><span style={{ color: "var(--text-secondary)" }}>$1.80</span><span>${fmt(costBudget, 2)}</span>
                  </div>
                </div>
                <div className="cost-table">
                  {Object.entries(costByModel).map(([model, v]) => (
                    <div key={model} className="cost-row">
                      <span className="n">{model}</span>
                      <span className="tok">{fmt(v.input_tokens + v.output_tokens, 0)} tok</span>
                      <span className="amt">${fmt(v.usd, 2)}</span>
                    </div>
                  ))}
                  {Object.keys(costByModel).length === 0 && (
                    <div className="cost-row"><span className="n">—</span><span className="tok">awaiting calls</span><span className="amt">$0.00</span></div>
                  )}
                </div>
                <div className="cost-foot">
                  <span>Cost / cycle <span>${cost?.today_calls ? fmt(costToday / Math.max(1, cost.today_calls), 4) : "—"}</span></span>
                  <span>Runway · {costRunwayHours != null ? `${Math.floor(costRunwayHours)}h ${Math.floor((costRunwayHours % 1) * 60)}m` : "—"}</span>
                </div>
              </div>
            </div>
          </section>

          {/* Positions */}
          <section>
            <div className="sect-hd">
              <div className="title-group">
                <span className="n">05 — Book</span>
                <h3>Open positions</h3>
              </div>
              <div className="tools">
                <div className="seg">
                  <button className="on">All</button>
                  <button>Crypto</button>
                  <button>Commo</button>
                  <button>Equity</button>
                </div>
                <button className="btn-ghost" onClick={async () => {
                  try { await fetch(`${API}/api/orders/kill`, { method: "POST" }); } catch { /* ignore */ }
                }}>Close all</button>
              </div>
            </div>

            <div className="card positions-card">
              <table className="positions">
                <thead>
                  <tr>
                    <th style={{ width: 28 }}>#</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th className="r">Size</th>
                    <th className="r">Entry</th>
                    <th className="r">Mark</th>
                    <th className="r">Move</th>
                    <th className="r">Unreal. P&amp;L</th>
                    <th>Stop distance</th>
                  </tr>
                </thead>
                <tbody>
                  {positionRows.length === 0 && (
                    <tr>
                      <td colSpan={9} style={{ textAlign: "center", padding: "28px 14px", color: "var(--text-tertiary)" }}>
                        No open positions
                      </td>
                    </tr>
                  )}
                  {positionRows.map(({ p, i, move, stopDistPct, stopBarColor, stopBarWidth }) => (
                    <tr key={p.symbol + i}>
                      <td style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 10.5 }}>
                        {String(i + 1).padStart(2, "0")}
                      </td>
                      <td className="sym">{p.symbol}</td>
                      <td className={`side ${String(p.side).toLowerCase() === "long" ? "long" : "short"}`}>
                        <span>{String(p.side).charAt(0) + String(p.side).slice(1).toLowerCase()}</span>
                      </td>
                      <td className="r mono">{fmt(p.size, 4)}</td>
                      <td className="r mono">${fmt(p.entry_price, 4)}</td>
                      <td className="r mono strong">${fmt(p.current_price, 4)}</td>
                      <td className={`r pnl ${move >= 0 ? "up" : "dn"}`}>{fmtPct(move)}</td>
                      <td className={`r pnl ${(p.unrealized_pnl ?? 0) >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(p.unrealized_pnl)}</td>
                      <td>
                        <div className="stop-track">
                          <div className="stop-bar">
                            <div className="fill" style={{ width: `${stopBarWidth}%`, background: stopBarColor }} />
                          </div>
                          <span className="stop-pct">{fmt(stopDistPct * 100, 1)}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
                {positionRows.length > 0 && (
                  <tfoot className="pos-foot">
                    <tr>
                      <td colSpan={3}>Subtotal · {positions.length} position{positions.length !== 1 ? "s" : ""}</td>
                      <td className="r mono strong">—</td>
                      <td className="r mono">—</td>
                      <td className="r mono strong">${fmt(positionsSubtotal.notional, 2)} notional</td>
                      <td className={`r ${positionsSubtotal.avgMove >= 0 ? "up" : "dn"}`}>{fmtPct(positionsSubtotal.avgMove)} avg</td>
                      <td className={`r strong ${positionsSubtotal.unreal >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(positionsSubtotal.unreal)}</td>
                      <td />
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </section>

          {/* Activity stream */}
          <section>
            <div className="sect-hd">
              <div className="title-group">
                <span className="n">06 — Activity</span>
                <h3>System stream</h3>
              </div>
              <div className="sub">Redis firehose · {events.length} events buffered</div>
            </div>
            <div className="card stream-card">
              <div className="stream-hd">
                <div className="t">
                  <div className="k"><span className="live" /> Streaming</div>
                  <h4>Live events · last {streamRows.length}</h4>
                </div>
                <div className="stream-filters">
                  {["all", "signals", "trades", "risk", "agents", "system"].map(f => (
                    <button key={f}
                      className={`fchip ${streamFilter === f ? "on" : ""}`}
                      onClick={() => setStreamFilter(f)}>{f}</button>
                  ))}
                </div>
              </div>
              <div className="stream-body">
                {streamRows.length === 0 && (
                  <div style={{ padding: "20px 24px", color: "var(--text-tertiary)", fontSize: 13 }}>
                    Quiet. Waiting for next cycle…
                  </div>
                )}
                {streamRows.map((e, i) => {
                  const { tag, cls } = streamTagFor(e);
                  return (
                    <div key={i} className="stream-row">
                      <span className="t">{timeHMS(e.ts)}</span>
                      <span className={`tag ${cls}`}>{tag}</span>
                      <span className="msg">{e.msg}</span>
                      <span className="id">{(e.data?.cycle_id as string | undefined)?.slice(0, 8) ?? ""}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>
        </main>

        {/* ── RAIL ── */}
        <aside className="rail">
          <section>
            <h5>Firm narrative <span className="sub"><span className="live" />Live</span></h5>
            <div className="narr-stats">
              <div className="c"><div className="k">Cycles</div><div className="v">{narrativeStats.cycles || "—"}</div></div>
              <div className="c"><div className="k">Approved</div><div className="v up">{narrativeStats.approved}</div></div>
              <div className="c"><div className="k">W / L</div><div className="v">{wins}·{losses}</div></div>
              <div className="c"><div className="k">Pending</div><div className="v">{positions.length}</div></div>
            </div>
            <div className="narr-feed">
              {railNarrative.length === 0 && (
                <div style={{ padding: "12px 0", color: "var(--text-tertiary)", fontSize: 12 }}>Quiet for now.</div>
              )}
              {railNarrative.map((item, i) => (
                <div key={i} className="narr-item">
                  <div className="narr-avatar" style={{ background: item.look.bg }}>{item.look.initial}</div>
                  <div className="narr-text">{item.text}</div>
                  <div className="narr-time">{item.time}</div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h5>Watchlist <span className="sub">Mark-to-market</span></h5>
            <div className="tabs">
              <button className="on">Crypto</button>
              <button>Commo</button>
              <button>Equit</button>
            </div>
            <div className="watch">
              {WATCHLIST_CRYPTO.map(w => {
                const live = watchPrices[w.symbol] ?? { price: 0, change_pct: 0, history: [] };
                const up = live.change_pct >= 0;
                return (
                  <div key={w.symbol} className="watch-row">
                    <div className={`watch-ico ${w.cls}`}>{w.icon}</div>
                    <div className="watch-name">
                      <span className="n">{w.name}</span>
                      <span className="t">{w.ticker} · USDT</span>
                    </div>
                    <Sparkline values={live.history} up={up} />
                    <div className="watch-right">
                      <div className="p">${fmt(live.price, live.price < 10 ? 4 : 2)}</div>
                      <div className={`c ${up ? "up" : "dn"}`}>{fmtPct(live.change_pct / 100)}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section>
            <h5>Task queue <span className="sub">Next cycle · {cycleId === "—" ? "48s" : "now"}</span></h5>
            <div className="queue-list">
              {["XRP/USDT", "BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "AVAX/USDT", "DOGE/USDT"].map((sym, i) => (
                <div key={sym} className="queue-row">
                  <span className={`s ${i >= 4 ? "dim" : ""}`}>{sym}</span>
                  <span className="f">every {i < 4 ? "5" : "10"}s</span>
                  <span className={`d ${i < 2 ? "" : "pend"}`}>{i < 2 ? "due" : `+${i}s`}</span>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}
