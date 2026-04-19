"use client";
import { useState, useEffect, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface PendingSignal {
  signal_id: string;
  symbol: string;
  side: string;
  direction: string;
  price: number;
  confidence: number;
  agent_id: string;
  contributing_agents: string[];
  reasoning: string;
  created_at: string;
}

interface Mode { system?: { autonomy_mode?: string; execution_venue?: string } }

type VenuePillProps = { venue: string; alpacaOk: boolean | null };

function VenuePill({ venue, alpacaOk }: VenuePillProps) {
  const label =
    venue === "live" ? "LIVE" :
    venue === "alpaca_paper" ? "ALPACA PAPER" :
    "SIM";
  const bg =
    venue === "live" ? "rgba(239,68,68,0.15)" :
    venue === "alpaca_paper" ? "rgba(99,102,241,0.15)" :
    "rgba(255,255,255,0.06)";
  const color =
    venue === "live" ? "#ef4444" :
    venue === "alpaca_paper" ? "#818cf8" :
    "var(--text-tertiary)";
  const dot = alpacaOk === false ? "#ef4444" : alpacaOk ? "#22c55e" : color;
  return (
    <span title={alpacaOk === false ? "Alpaca credentials missing or account inactive" : `Venue: ${venue}`}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        fontSize: 10, fontWeight: 700, padding: "3px 10px", borderRadius: 3,
        background: bg, color, textTransform: "uppercase", letterSpacing: "0.05em",
      }}>
      {venue !== "sim" && (
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: dot }} />
      )}
      {label}
    </span>
  );
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  return `${Math.floor(ms / 3_600_000)}h ago`;
}

export function ApprovalBanner() {
  const [pending, setPending] = useState<PendingSignal[]>([]);
  const [mode, setMode] = useState<string>("COMMANDER");
  const [venue, setVenue] = useState<string>("sim");
  const [alpacaOk, setAlpacaOk] = useState<boolean | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [p, m, v] = await Promise.allSettled([
        fetch(`${API}/api/orders/pending`).then((r) => r.json()),
        fetch(`${API}/api/settings`).then((r) => r.json()),
        fetch(`${API}/api/execution/venue`).then((r) => r.json()),
      ]);
      if (p.status === "fulfilled") setPending(Array.isArray(p.value) ? p.value : []);
      if (m.status === "fulfilled") {
        const sys = (m.value as Mode).system;
        setMode(sys?.autonomy_mode ?? "COMMANDER");
        if (sys?.execution_venue) setVenue(sys.execution_venue);
      }
      if (v.status === "fulfilled" && v.value) {
        const data = v.value as { venue?: string; alpaca_account_ok?: boolean; alpaca_available?: boolean };
        if (data.venue) setVenue(data.venue);
        setAlpacaOk(data.venue === "sim" ? null : Boolean(data.alpaca_account_ok));
      }
    } catch {}
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3_000);
    return () => clearInterval(t);
  }, [refresh]);

  async function decide(signal_id: string, action: "approve" | "reject") {
    await fetch(`${API}/api/orders/${action}/${signal_id}`, { method: "POST" });
    refresh();
  }

  async function changeMode(next: string) {
    await fetch(`${API}/api/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system: { autonomy_mode: next } }),
    });
    refresh();
  }

  if (mode !== "COMMANDER" && pending.length === 0) {
    return (
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "8px 16px", borderRadius: 6, marginBottom: 16,
        background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.3)",
        fontSize: 12, color: "var(--text-secondary)",
      }}>
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <VenuePill venue={venue} alpacaOk={alpacaOk} />
          <span><strong style={{ color: "#22c55e" }}>{mode}</strong> mode — auto-executing approved signals</span>
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          {["COMMANDER", "TRUSTED", "YOLO"].map((m) => (
            <button key={m} onClick={() => changeMode(m)} style={{
              padding: "4px 10px", fontSize: 10, fontWeight: 600, borderRadius: 3,
              background: m === mode ? "var(--accent-primary)" : "transparent",
              color: m === mode ? "#fff" : "var(--text-secondary)",
              border: `1px solid ${m === mode ? "var(--accent-primary)" : "var(--border-default)"}`,
              cursor: "pointer",
            }}>
              {m}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{
      marginBottom: 18, padding: "12px 16px", borderRadius: 6,
      background: pending.length > 0 ? "rgba(245,158,11,0.1)" : "rgba(94,106,210,0.08)",
      border: `1px solid ${pending.length > 0 ? "rgba(245,158,11,0.4)" : "rgba(94,106,210,0.3)"}`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: pending.length > 0 ? 12 : 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <VenuePill venue={venue} alpacaOk={alpacaOk} />
          <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 3, background: "#f59e0b22", color: "#f59e0b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {mode}
          </span>
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
            {pending.length === 0
              ? "No trades pending. Agents will queue them here when conviction hits Diana's threshold."
              : `${pending.length} trade${pending.length === 1 ? "" : "s"} awaiting your approval`}
          </span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {["COMMANDER", "TRUSTED", "YOLO"].map((m) => (
            <button key={m} onClick={() => changeMode(m)} style={{
              padding: "4px 10px", fontSize: 10, fontWeight: 600, borderRadius: 3,
              background: m === mode ? "var(--accent-primary)" : "transparent",
              color: m === mode ? "#fff" : "var(--text-secondary)",
              border: `1px solid ${m === mode ? "var(--accent-primary)" : "var(--border-default)"}`,
              cursor: "pointer",
            }}>
              {m}
            </button>
          ))}
        </div>
      </div>

      {pending.map((p) => (
        <div key={p.signal_id} style={{
          display: "grid", gridTemplateColumns: "80px 80px 100px 1fr auto", gap: 12,
          alignItems: "center", padding: "10px 0", borderTop: "1px solid var(--border-subtle)",
        }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: p.direction === "LONG" ? "var(--accent-profit)" : "var(--accent-loss)" }}>
            {p.side} {p.direction}
          </span>
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>{p.symbol}</span>
          <span style={{ fontSize: 12, color: "var(--text-secondary)", fontFamily: "var(--font-mono, monospace)" }}>
            ${p.price.toFixed(p.price < 10 ? 4 : 2)} · {(p.confidence * 100).toFixed(0)}%
          </span>
          <span style={{ fontSize: 11, color: "var(--text-tertiary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {p.contributing_agents.join(", ")} · {timeAgo(p.created_at)}
          </span>
          <div style={{ display: "flex", gap: 6 }}>
            <button onClick={() => decide(p.signal_id, "approve")} style={{
              padding: "5px 12px", fontSize: 11, fontWeight: 600, borderRadius: 3,
              background: "var(--accent-profit)", color: "#fff", border: "none", cursor: "pointer",
            }}>
              Approve
            </button>
            <button onClick={() => decide(p.signal_id, "reject")} style={{
              padding: "5px 12px", fontSize: 11, fontWeight: 600, borderRadius: 3,
              background: "transparent", color: "var(--accent-loss)",
              border: "1px solid var(--accent-loss)", cursor: "pointer",
            }}>
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
