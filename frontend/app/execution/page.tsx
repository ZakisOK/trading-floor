"use client";
import { useState, useEffect, useCallback, useRef } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Portfolio { cash: number; positions_value: number; total: number; daily_pnl: number; trade_count: number }
interface Position { symbol: string; side: string; quantity: number; avg_price: number; current_price?: number; unrealized_pnl?: number }
interface Order { order_id: string; symbol: string; side: string; quantity: number; filled_price: number; status: string; created_at: string; agent_id: string; strategy: string }
interface Pending { id: string; symbol: string; side: string; agent_id: string; confidence: number; thesis: string }
interface KillStatus { active: boolean; reason: string; activated_at: string }

function PnlBadge({ val }: { val: number }) {
  const color = val >= 0 ? "var(--accent-profit)" : "var(--accent-loss)";
  return <span style={{ color, fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>{val >= 0 ? "+" : ""}${val.toFixed(2)}</span>;
}

function SideBadge({ side }: { side: string }) {
  const bg = side === "BUY" || side === "LONG" ? "rgba(88,214,141,0.15)" : "rgba(248,81,73,0.15)";
  const color = side === "BUY" || side === "LONG" ? "var(--accent-profit)" : "var(--accent-loss)";
  return <span style={{ background: bg, color, padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 700 }}>{side}</span>;
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
        fetch(`${API}/api/orders/positions`).then(r => r.json()),
        fetch(`${API}/api/orders`).then(r => r.json()),
        fetch(`${API}/api/orders/kill/status`).then(r => r.json()),
      ]);
      setPortfolio(port); setPositions(pos); setOrders(ord); setKillStatus(ks);
    } catch {}
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

  const mono = { fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" as const };
  const card = { background: "var(--bg-surface-1)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: "16px 20px" };

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-void)", color: "var(--text-primary)", padding: "32px", fontFamily: "var(--font-sans)" }}>
      <style>{`@keyframes slideIn{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}`}</style>

      {/* Toast notifications */}
      <div style={{ position: "fixed", top: 20, right: 20, zIndex: 999, display: "flex", flexDirection: "column", gap: 8 }}>
        {toasts.map(t => (
          <div key={t.id} style={{ background: "var(--bg-surface-2)", border: `1px solid ${t.color}`, borderRadius: "var(--radius-sm)", padding: "10px 16px", fontSize: 13, color: t.color, animation: "slideIn 0.3s ease", minWidth: 240 }}>{t.msg}</div>
        ))}
      </div>

      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 4 }}>Execution Monitor</h1>
            <p style={{ color: "var(--text-secondary)" }}>Live paper trading — order flow and positions</p>
          </div>
          {/* Kill switch */}
          {killStatus.active ? (
            <button onClick={resetKill} style={{ background: "rgba(88,214,141,0.15)", border: "2px solid var(--accent-profit)", borderRadius: "var(--radius-sm)", color: "var(--accent-profit)", padding: "10px 24px", fontWeight: 700, fontSize: 14, cursor: "pointer" }}>
              Reset Kill Switch
            </button>
          ) : (
            <div>
              {!showKillConfirm ? (
                <button onClick={() => setShowKillConfirm(true)} style={{ background: "rgba(248,81,73,0.15)", border: "2px solid var(--accent-loss)", borderRadius: "var(--radius-sm)", color: "var(--accent-loss)", padding: "10px 24px", fontWeight: 700, fontSize: 14, cursor: "pointer" }}>
                  KILL SWITCH
                </button>
              ) : (
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input value={killInput} onChange={e => setKillInput(e.target.value)} placeholder="Type KILL to confirm"
                    style={{ background: "var(--bg-surface-2)", border: "2px solid var(--accent-loss)", borderRadius: "var(--radius-sm)", color: "var(--text-primary)", padding: "8px 12px", fontSize: 13, width: 180 }} />
                  <button onClick={activateKill} disabled={killInput !== "KILL"} style={{ background: killInput === "KILL" ? "var(--accent-loss)" : "var(--bg-surface-3)", color: "#fff", border: "none", borderRadius: "var(--radius-sm)", padding: "8px 16px", cursor: killInput === "KILL" ? "pointer" : "not-allowed", fontWeight: 700, fontSize: 13 }}>Confirm</button>
                  <button onClick={() => { setShowKillConfirm(false); setKillInput(""); }} style={{ background: "none", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", padding: "8px 14px", cursor: "pointer", fontSize: 13 }}>Cancel</button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Kill switch banner */}
        {killStatus.active && (
          <div style={{ marginBottom: 20, padding: "14px 20px", background: "rgba(248,81,73,0.12)", border: "2px solid var(--accent-loss)", borderRadius: "var(--radius-md)", color: "var(--accent-loss)", fontWeight: 700 }}>
            KILL SWITCH ACTIVE — {killStatus.reason} — All orders suspended
          </div>
        )}

        {/* Portfolio summary */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, marginBottom: 20 }}>
          {[
            { l: "Total Value", v: `$${portfolio.total.toLocaleString("en", { minimumFractionDigits: 2 })}` },
            { l: "Cash", v: `$${portfolio.cash.toLocaleString("en", { minimumFractionDigits: 2 })}` },
            { l: "Positions", v: `$${portfolio.positions_value.toFixed(2)}` },
            { l: "Daily P&L", v: null, pnl: portfolio.daily_pnl },
            { l: "Trades Today", v: String(portfolio.trade_count) },
          ].map(m => (
            <div key={m.l} style={card}>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 6 }}>{m.l}</div>
              <div style={{ ...mono, fontSize: 18, fontWeight: 700 }}>
                {m.pnl !== undefined ? <PnlBadge val={m.pnl} /> : m.v}
              </div>
            </div>
          ))}
        </div>

        {/* Pending approvals */}
        {pending.length > 0 && (
          <div className="glass-panel" style={{ padding: 20, marginBottom: 20, borderColor: "rgba(94,106,210,0.3)" }}>
            <div style={{ fontSize: 11, color: "var(--accent-primary)", textTransform: "uppercase", marginBottom: 12 }}>Pending Approvals ({pending.length})</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {pending.map(s => (
                <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", background: "var(--bg-surface-2)", borderRadius: "var(--radius-sm)" }}>
                  <span style={{ ...mono, fontSize: 13, minWidth: 90 }}>{s.symbol}</span>
                  <SideBadge side={s.side} />
                  <span style={{ fontSize: 12, color: "var(--text-secondary)", flex: 1 }}>{s.thesis?.slice(0, 80)}</span>
                  <span style={{ ...mono, fontSize: 12, color: "var(--text-tertiary)", minWidth: 40 }}>{(s.confidence * 100).toFixed(0)}%</span>
                  <button onClick={() => approve(s.id)} style={{ background: "rgba(88,214,141,0.15)", border: "1px solid var(--accent-profit)", color: "var(--accent-profit)", borderRadius: "var(--radius-sm)", padding: "4px 12px", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>Approve</button>
                  <button onClick={() => reject(s.id)} style={{ background: "rgba(248,81,73,0.1)", border: "1px solid var(--accent-loss)", color: "var(--accent-loss)", borderRadius: "var(--radius-sm)", padding: "4px 12px", cursor: "pointer", fontSize: 12 }}>Reject</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Positions + Orders in two columns */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          <div className="glass-panel" style={{ padding: 20 }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 12 }}>Open Positions</div>
            {positions.length === 0 ? <div style={{ color: "var(--text-tertiary)", fontSize: 13, textAlign: "center", padding: 16 }}>No open positions</div> : (
              positions.map((p, i) => (
                <div key={i} style={{ padding: "8px 0", borderBottom: "1px solid var(--border-subtle)", display: "flex", justifyContent: "space-between" }}>
                  <span style={{ ...mono, fontSize: 13 }}>{p.symbol}</span>
                  <SideBadge side={p.side} />
                  <span style={{ ...mono, fontSize: 13, color: "var(--text-secondary)" }}>{p.quantity?.toFixed(4)}</span>
                  <span style={{ ...mono, fontSize: 13 }}>${p.avg_price?.toFixed(2)}</span>
                </div>
              ))
            )}
          </div>
          <div className="glass-panel" style={{ padding: 20 }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", marginBottom: 12 }}>Order History (last 20)</div>
            {orders.length === 0 ? <div style={{ color: "var(--text-tertiary)", fontSize: 13, textAlign: "center", padding: 16 }}>No orders yet</div> : (
              orders.slice(-20).reverse().map(o => (
                <div key={o.order_id} style={{ padding: "7px 0", borderBottom: "1px solid var(--border-subtle)", display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ ...mono, fontSize: 11, color: "var(--text-tertiary)", minWidth: 60 }}>{new Date(o.created_at).toLocaleTimeString()}</span>
                  <span style={{ ...mono, fontSize: 12, minWidth: 70 }}>{o.symbol}</span>
                  <SideBadge side={o.side} />
                  <span style={{ ...mono, fontSize: 12, color: "var(--text-secondary)" }}>${o.filled_price?.toFixed(2)}</span>
                  <span style={{ fontSize: 11, color: "var(--text-tertiary)", marginLeft: "auto" }}>{o.agent_id}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
