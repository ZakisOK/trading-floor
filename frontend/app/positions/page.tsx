"use client";
import { useState, useEffect, useCallback } from "react";
import { PageShell, SectionHeader } from "@/components/PageShell";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_MS = 5000;

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
interface RiskMetrics {
  daily_pnl: number;
  portfolio_value: number;
  total_exposure: number;
  drawdown_pct: number;
  open_positions: string | number;
  updated_at: string | null;
  day_pnl?: number;
  total_pnl?: number;
  unrealized_pnl?: number;
  realized_pnl?: number;
  starting_capital?: number;
}
interface TradeHistoryItem {
  symbol: string;
  side: string;
  status: "open" | "closed";
  entry_ts: string | null;
  exit_ts: string | null;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  pnl: number | null;
  pnl_pct: number | null;
  exit_reason: string | null;
  entry_agent: string | null;
}

function fmt(n: number | undefined | null, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function fmtSignedDollar(n: number | undefined | null) {
  if (n == null || isNaN(n)) return "—";
  const s = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${s}$${fmt(Math.abs(n))}`;
}
function fmtPct(n: number | undefined | null, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  const s = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${s}${fmt(Math.abs(n) * 100, dec)}%`;
}
function timeAgo(ts: string | null): string {
  if (!ts) return "—";
  const t = new Date(ts).getTime();
  if (isNaN(t)) return "—";
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function PositionsPage() {
  const [positions, setPositions] = useState<LivePosition[]>([]);
  const [history, setHistory] = useState<TradeHistoryItem[]>([]);
  const [risk, setRisk] = useState<RiskMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "crypto" | "commo" | "equity">("all");

  const fetchData = useCallback(async () => {
    try {
      const [posRes, riskRes, histRes] = await Promise.all([
        fetch(`${API}/api/execution/positions`),
        fetch(`${API}/api/execution/risk-metrics`),
        fetch(`${API}/api/orders/history`),
      ]);
      if (!posRes.ok) throw new Error(`Positions API ${posRes.status}`);
      const [pos, riskData, hist] = await Promise.all([posRes.json(), riskRes.json(), histRes.json()]);
      setPositions(pos);
      setRisk(riskData);
      setHistory(Array.isArray(hist) ? hist : []);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fetch failed");
    }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, POLL_MS);
    return () => clearInterval(iv);
  }, [fetchData]);

  const totalUnrealized = positions.reduce((a, p) => a + (p.unrealized_pnl ?? 0), 0);
  const totalNotional = positions.reduce((a, p) => a + p.quantity * p.current_price, 0);

  const classify = (sym: string) => {
    if (/USDT|USD|BTC|ETH|XRP|SOL/.test(sym) && /\/|\-/.test(sym)) return "crypto";
    if (/=F$/.test(sym)) return "commo";
    return "equity";
  };

  const visible = positions.filter(p => filter === "all" || classify(p.symbol) === filter);

  return (
    <PageShell
      crumbs={["The Firm", "Positions"]}
      status={<>
        <div className="st"><span className="d ok" /> {positions.length} open · {timeAgo(risk?.updated_at ?? null)}</div>
      </>}
    >
      {error && (
        <div className="mode-row" style={{ borderColor: "var(--accent-loss)", background: "rgba(248,113,113,.08)" }}>
          <span className="flag" style={{ color: "var(--accent-loss)" }}>Fetch error</span>
          <div className="msg">{error}</div>
        </div>
      )}

      {/* Briefing */}
      <div className="briefing">
        <div className="left">
          <div className="eyebrow"><span className="num">01</span><span>·</span><span>Live book</span>
            <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>Sweep every {POLL_MS / 1000}s</span>
          </div>
          <p className="headline">
            Position monitor fires exits within 5s of a stop or target hit. Stop-distance bars below show proximity
            to each position's effective stop (including trailing).
          </p>
          <div className="figure-stack">
            <span className="lbl">Portfolio</span>
            <span className="big">
              ${fmt(Math.floor(risk?.portfolio_value ?? 0), 0)}
              <span className="cents">.{String(Math.floor(((risk?.portfolio_value ?? 0) % 1) * 100)).padStart(2, "0")}</span>
            </span>
            <span className="delta">
              <span className={`v ${(risk?.day_pnl ?? 0) >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(risk?.day_pnl)}</span><span>today</span>
              <span className="pip" />
              <span className={`v ${(risk?.total_pnl ?? 0) >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(risk?.total_pnl)}</span><span>since inception</span>
            </span>
          </div>
        </div>
        <div className="right">
          <div className="cell"><div className="k"><span>Open positions</span><span className="n">02</span></div><div className="v">{positions.length}</div><div className="sub"><span>across assets</span></div></div>
          <div className="cell"><div className="k"><span>Notional</span><span className="n">03</span></div><div className="v">${fmt(totalNotional, 0)}</div><div className="sub"><span>{risk?.portfolio_value ? Math.round((totalNotional / risk.portfolio_value) * 100) : 0}% of book</span></div></div>
          <div className="cell"><div className="k"><span>Unrealized</span><span className="n">04</span></div><div className={`v ${totalUnrealized >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(totalUnrealized)}</div><div className="sub"><span>Mark-to-market</span></div></div>
          <div className="cell"><div className="k"><span>Realized</span><span className="n">05</span></div><div className={`v ${(risk?.realized_pnl ?? 0) >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(risk?.realized_pnl)}</div><div className="sub"><span>Closed trades</span></div></div>
        </div>
      </div>

      {/* Open positions */}
      <section>
        <SectionHeader
          n="02"
          label="Book"
          title="Open positions"
          tools={
            <div className="seg">
              {(["all", "crypto", "commo", "equity"] as const).map(f => (
                <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>{f}</button>
              ))}
            </div>
          }
        />
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
                <th className="r">Unreal P&amp;L</th>
                <th>Stop distance</th>
              </tr>
            </thead>
            <tbody>
              {visible.length === 0 && (
                <tr><td colSpan={9} style={{ textAlign: "center", padding: "28px 14px", color: "var(--text-tertiary)" }}>
                  {positions.length === 0 ? "No open positions" : `No ${filter} positions`}
                </td></tr>
              )}
              {visible.map((p, i) => {
                const isLong = p.side === "LONG";
                const stopDist = p.distance_to_stop_pct;
                const stopColor = stopDist >= 0.5 ? "var(--accent-profit)"
                  : stopDist >= 0.25 ? "var(--status-serious)"
                  : "var(--accent-loss)";
                return (
                  <tr key={p.symbol + i}>
                    <td style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 10.5 }}>{String(i + 1).padStart(2, "0")}</td>
                    <td className="sym">{p.symbol}</td>
                    <td className={`side ${isLong ? "long" : "short"}`}><span>{p.side}</span></td>
                    <td className="r mono">{fmt(p.quantity, 4)}</td>
                    <td className="r mono">${fmt(p.avg_price, 4)}</td>
                    <td className="r mono strong">${fmt(p.current_price, 4)}</td>
                    <td className={`r pnl ${p.unrealized_pnl_pct >= 0 ? "up" : "dn"}`}>{fmtPct(p.unrealized_pnl_pct)}</td>
                    <td className={`r pnl ${p.unrealized_pnl >= 0 ? "up" : "dn"}`}>{fmtSignedDollar(p.unrealized_pnl)}</td>
                    <td>
                      <div className="stop-track">
                        <div className="stop-bar">
                          <div className="fill" style={{ width: `${Math.min(100, stopDist * 100)}%`, background: stopColor }} />
                        </div>
                        <span className="stop-pct">{fmt(stopDist * 100, 0)}%</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            {visible.length > 0 && (
              <tfoot className="pos-foot">
                <tr>
                  <td colSpan={3}>Subtotal · {visible.length} position{visible.length !== 1 ? "s" : ""}</td>
                  <td className="r mono strong">—</td>
                  <td className="r mono">—</td>
                  <td className="r mono strong">${fmt(visible.reduce((a, p) => a + p.quantity * p.current_price, 0), 2)} notional</td>
                  <td className="r mono">—</td>
                  <td className={`r strong ${visible.reduce((a, p) => a + p.unrealized_pnl, 0) >= 0 ? "up" : "dn"}`}>
                    {fmtSignedDollar(visible.reduce((a, p) => a + p.unrealized_pnl, 0))}
                  </td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </section>

      {/* Trade history */}
      <section>
        <SectionHeader n="03" label="History" title="Recent trades" sub={`${history.length} trade${history.length !== 1 ? "s" : ""}`} />
        <div className="card stream-card">
          <div className="stream-body" style={{ maxHeight: 480 }}>
            {history.length === 0 && (
              <div style={{ padding: "20px 24px", color: "var(--text-tertiary)", fontSize: 13 }}>
                No trades yet. When Atlas fills an order it&apos;ll show here.
              </div>
            )}
            {history.slice(0, 50).map((t, i) => {
              const isOpen = t.status === "open";
              const pnl = t.pnl;
              const tagCls = isOpen ? "tag-agt" : pnl != null && pnl >= 0 ? "tag-trd" : "tag-rsk";
              const ts = t.entry_ts ? new Date(t.entry_ts).toISOString().slice(11, 19) : "—";
              return (
                <div key={i} className="stream-row">
                  <span className="t">{ts}</span>
                  <span className={`tag ${tagCls}`}>{isOpen ? "OPEN" : pnl != null && pnl >= 0 ? "WIN" : "LOSS"}</span>
                  <span className="msg">
                    <b>{t.symbol}</b> · {t.side} {fmt(t.quantity, 4)} · entry ${fmt(t.entry_price, 4)}
                    {t.exit_price != null && <> → exit ${fmt(t.exit_price, 4)}</>}
                    {pnl != null && <> · <span style={{ color: pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)" }}>{fmtSignedDollar(pnl)}</span></>}
                    {t.exit_reason && <> · {t.exit_reason}</>}
                    {t.entry_agent && <> · {t.entry_agent}</>}
                  </span>
                  <span className="id">{timeAgo(t.entry_ts)}</span>
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </PageShell>
  );
}
