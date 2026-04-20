"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import { PageShell, SectionHeader } from "@/components/PageShell";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Portfolio { cash: number; positions_value: number; total: number; daily_pnl: number; trade_count: number }
interface Position { symbol: string; side: string; quantity: number; avg_price: number; current_price?: number; unrealized_pnl?: number }
interface Order { order_id: string; symbol: string; side: string; quantity: number; filled_price: number; status: string; created_at: string; agent_id: string; strategy: string }
interface Pending { id: string; symbol: string; side: string; agent_id: string; confidence: number; thesis: string }
interface KillStatus { active: boolean; reason: string; activated_at: string }

function fmt(n: number | undefined, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

export default function ExecutionPage() {
  const [portfolio, setPortfolio] = useState<Portfolio>({ cash: 10000, positions_value: 0, total: 10000, daily_pnl: 0, trade_count: 0 });
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const [killStatus, setKillStatus] = useState<KillStatus>({ active: false, reason: "", activated_at: "" });
  const [killInput, setKillInput] = useState("");
  const [showKillConfirm, setShowKillConfirm] = useState(false);
  const [toasts, setToasts] = useState<{ id: number; msg: string; color: string }[]>([]);
  const toastId = useRef(0);

  function toast(msg: string, color = "var(--accent-profit)") {
    const id = ++toastId.current;
    setToasts(p => [...p, { id, msg, color }]);
    setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), 4000);
  }

  const fetchAll = useCallback(async () => {
    try {
      const [port, pos, ord, ks] = await Promise.all([
        fetch(`${API}/api/orders/portfolio`).then(r => r.json()),
        fetch(`${API}/api/execution/positions`).then(r => r.json()),
        fetch(`${API}/api/orders`).then(r => r.json()),
        fetch(`${API}/api/orders/kill/status`).then(r => r.json()),
      ]);
      setPortfolio(port);
      setPositions(Array.isArray(pos) ? pos : pos?.positions ?? []);
      setOrders(Array.isArray(ord) ? ord : ord?.orders ?? []);
      setKillStatus(ks);
    } catch { /* swallow */ }
  }, []);

  useEffect(() => { fetchAll(); const iv = setInterval(fetchAll, 3000); return () => clearInterval(iv); }, [fetchAll]);

  async function activateKill() {
    if (killInput !== "KILL") return;
    const r = await fetch(`${API}/api/orders/kill`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "Manual activation from UI" }),
    });
    if (r.ok) { toast("Kill switch activated — all positions flattened", "var(--accent-loss)"); setShowKillConfirm(false); setKillInput(""); fetchAll(); }
  }
  async function resetKill() {
    await fetch(`${API}/api/orders/kill/reset`, { method: "POST" });
    toast("Kill switch reset — trading resumed");
    fetchAll();
  }
  async function approve(id: string) {
    const r = await fetch(`${API}/api/orders/approve/${id}`, { method: "POST" });
    if (r.ok) { toast("Signal approved and executed"); setPending(p => p.filter(x => x.id !== id)); }
  }
  async function reject(id: string) {
    await fetch(`${API}/api/orders/reject/${id}`, { method: "POST" });
    toast("Signal rejected", "var(--text-tertiary)");
    setPending(p => p.filter(x => x.id !== id));
  }

  const winRate = 0;

  return (
    <PageShell
      crumbs={["The Firm", "Intelligence", "Execution"]}
      status={<>
        <div className="st"><span className={`d ${killStatus.active ? "warn" : "ok"}`} />
          {killStatus.active ? "KILL SWITCH ACTIVE" : "Order flow live"}
        </div>
        <div className="st">{portfolio.trade_count} trades · {positions.length} open</div>
      </>}
    >
      {/* Toasts */}
      <style>{`@keyframes slideIn{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}`}</style>
      <div style={{ position: "fixed", top: 20, right: 20, zIndex: 999, display: "flex", flexDirection: "column", gap: 8 }}>
        {toasts.map(t => (
          <div key={t.id} style={{ background: "var(--bg-surface-2)", border: `1px solid ${t.color}`, borderRadius: "var(--radius-sm)", padding: "10px 16px", fontSize: 13, color: t.color, animation: "slideIn 0.3s ease", minWidth: 240 }}>{t.msg}</div>
        ))}
      </div>

      {/* Kill switch banner */}
      {killStatus.active && (
        <div className="mode-row" style={{ borderColor: "var(--accent-loss)", background: "rgba(248,113,113,.08)" }}>
          <span className="flag" style={{ color: "var(--accent-loss)" }}>KILL SWITCH ACTIVE</span>
          <div className="msg"><b>{killStatus.reason || "Manual activation"}</b> — all orders suspended</div>
          <div className="tools">
            <button className="btn-ghost" onClick={resetKill}>Reset kill switch</button>
          </div>
        </div>
      )}

      {/* Top figure row */}
      <div className="briefing">
        <div className="left">
          <div className="eyebrow"><span className="num">01</span><span>·</span><span>Execution monitor</span>
            <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>Live paper · sim venue</span>
          </div>
          <p className="headline">
            Live order flow from Atlas. Kill switch cuts all open positions in &lt; 60s. Operator approvals queue here
            when autonomy is <b>COMMANDER</b>.
          </p>
          <div className="figure-stack">
            <span className="lbl">Portfolio</span>
            <span className="big">
              ${fmt(Math.floor(portfolio.total), 0)}
              <span className="cents">.{String(Math.floor((portfolio.total % 1) * 100)).padStart(2, "0")}</span>
            </span>
            <span className="delta">
              <span className={`v ${portfolio.daily_pnl >= 0 ? "up" : "dn"}`}>
                {portfolio.daily_pnl >= 0 ? "+" : "−"}${fmt(Math.abs(portfolio.daily_pnl))}
              </span>
              <span>today</span>
            </span>
          </div>
        </div>
        <div className="right">
          <div className="cell"><div className="k"><span>Cash</span><span className="n">02</span></div><div className="v">${fmt(portfolio.cash, 0)}</div><div className="sub"><span>Available</span></div></div>
          <div className="cell"><div className="k"><span>Positions value</span><span className="n">03</span></div><div className="v">${fmt(portfolio.positions_value, 0)}</div><div className="sub"><span>{positions.length} open</span></div></div>
          <div className="cell"><div className="k"><span>Trades today</span><span className="n">04</span></div><div className="v">{portfolio.trade_count}</div><div className="sub"><span>Since 00:00 UTC</span></div></div>
          <div className="cell"><div className="k"><span>Kill state</span><span className="n">05</span></div>
            <div className={`v ${killStatus.active ? "dn" : "up"}`}>{killStatus.active ? "ACTIVE" : "READY"}</div>
            <div className="sub">
              {!killStatus.active && !showKillConfirm && (
                <button className="btn-ghost" onClick={() => setShowKillConfirm(true)} style={{ color: "var(--accent-loss)", borderColor: "var(--accent-loss)" }}>Arm kill switch</button>
              )}
              {!killStatus.active && showKillConfirm && (
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input value={killInput} onChange={e => setKillInput(e.target.value)} placeholder="Type KILL"
                    style={{ background: "var(--bg-surface-2)", border: "1px solid var(--accent-loss)", borderRadius: 4, color: "var(--text-primary)", padding: "4px 8px", fontSize: 11, width: 90 }} />
                  <button className="btn-ghost" onClick={activateKill} style={{ color: "var(--accent-loss)", borderColor: "var(--accent-loss)" }}>Confirm</button>
                  <button className="btn-ghost" onClick={() => { setShowKillConfirm(false); setKillInput(""); }}>×</button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Pending approvals */}
      {pending.length > 0 && (
        <section>
          <SectionHeader n="02" label="Approvals" title={`${pending.length} pending`} sub="COMMANDER mode — approve or reject each signal" />
          <div className="card card-pad">
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {pending.map(s => {
                const isLong = s.side === "BUY" || s.side === "LONG";
                return (
                  <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", background: "rgba(0,0,0,.28)", border: "1px solid var(--line-hair)", borderRadius: 7 }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, minWidth: 90 }}>{s.symbol}</span>
                    <span className={`side ${isLong ? "long" : "short"}`} style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}>
                      <span style={{ padding: "2px 7px", borderRadius: 3, background: isLong ? "var(--accent-profit-dim)" : "var(--accent-loss-dim)", color: isLong ? "var(--accent-profit)" : "var(--accent-loss)", fontWeight: 600, letterSpacing: ".14em" }}>{s.side}</span>
                    </span>
                    <span style={{ fontSize: 12, color: "var(--text-secondary)", flex: 1 }}>{s.thesis?.slice(0, 80)}</span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-tertiary)", minWidth: 40 }}>{(s.confidence * 100).toFixed(0)}%</span>
                    <button className="btn-ghost" style={{ color: "var(--accent-profit)", borderColor: "var(--accent-profit)" }} onClick={() => approve(s.id)}>Approve</button>
                    <button className="btn-ghost" onClick={() => reject(s.id)}>Reject</button>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* Open positions */}
      <section>
        <SectionHeader n={pending.length > 0 ? "03" : "02"} label="Book" title="Open positions" sub={`${positions.length} position${positions.length !== 1 ? "s" : ""}`} />
        <div className="card positions-card">
          <table className="positions">
            <thead>
              <tr>
                <th style={{ width: 28 }}>#</th>
                <th>Symbol</th>
                <th>Side</th>
                <th className="r">Qty</th>
                <th className="r">Entry</th>
                <th className="r">Mark</th>
                <th className="r">Unreal P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign: "center", padding: "28px 14px", color: "var(--text-tertiary)" }}>No open positions</td></tr>
              )}
              {positions.map((p, i) => {
                const isLong = p.side === "LONG" || p.side === "BUY";
                const upnl = p.unrealized_pnl ?? 0;
                return (
                  <tr key={p.symbol + i}>
                    <td style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 10.5 }}>{String(i + 1).padStart(2, "0")}</td>
                    <td className="sym">{p.symbol}</td>
                    <td className={`side ${isLong ? "long" : "short"}`}><span>{p.side}</span></td>
                    <td className="r mono">{fmt(p.quantity, 4)}</td>
                    <td className="r mono">${fmt(p.avg_price, 4)}</td>
                    <td className="r mono strong">${fmt(p.current_price, 4)}</td>
                    <td className={`r pnl ${upnl >= 0 ? "up" : "dn"}`}>{upnl >= 0 ? "+" : "−"}${fmt(Math.abs(upnl))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Order history */}
      <section>
        <SectionHeader n={pending.length > 0 ? "04" : "03"} label="History" title="Order flow" sub={`Last ${Math.min(20, orders.length)} of ${orders.length}`} />
        <div className="card stream-card">
          <div className="stream-body">
            {orders.length === 0 && (
              <div style={{ padding: "20px 24px", color: "var(--text-tertiary)", fontSize: 13 }}>No orders yet</div>
            )}
            {orders.slice(-20).reverse().map(o => {
              const isLong = o.side === "BUY" || o.side === "LONG";
              return (
                <div key={o.order_id} className="stream-row">
                  <span className="t">{new Date(o.created_at).toISOString().slice(11, 19)}</span>
                  <span className={`tag ${isLong ? "tag-trd" : "tag-rsk"}`}>{o.side}</span>
                  <span className="msg">
                    <b>{o.symbol}</b> · qty {fmt(o.quantity, 4)} @ ${fmt(o.filled_price, 4)} · agent {o.agent_id} · {o.status}
                  </span>
                  <span className="id">{o.order_id.slice(0, 8)}</span>
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </PageShell>
  );
}
