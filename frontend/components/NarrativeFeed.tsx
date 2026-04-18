"use client";
import { useState, useEffect, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface NarrativeEvent {
  ts: string | null;
  kind: "cycle" | "trade" | "pnl" | "pending";
  severity: "info" | "muted" | "win" | "loss" | "trade" | "warn";
  text: string;
  duration_s?: number;
}

interface Payload {
  summary: {
    cycles_completed: number;
    cycles_approved: number;
    cycles_rejected: number;
    wins: number;
    losses: number;
    pending: number;
  };
  events: NarrativeEvent[];
  ts: string;
}

const SEV_COLOR: Record<NarrativeEvent["severity"], string> = {
  info: "var(--text-secondary)",
  muted: "var(--text-tertiary)",
  win: "var(--accent-profit)",
  loss: "var(--accent-loss)",
  trade: "var(--accent-info)",
  warn: "#f59e0b",
};

const SEV_DOT: Record<NarrativeEvent["severity"], string> = {
  info: "#94a3b8",
  muted: "#475569",
  win: "#22c55e",
  loss: "#ef4444",
  trade: "#6366f1",
  warn: "#f59e0b",
};

function timeAgo(iso: string | null): string {
  if (!iso) return "just now";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h`;
  return `${Math.floor(ms / 86_400_000)}d`;
}

export function NarrativeFeed() {
  const [data, setData] = useState<Payload | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [pulseKey, setPulseKey] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/narrative`);
      if (!r.ok) return;
      const d = await r.json();
      setData(d);
      setLastUpdate(new Date());
      setPulseKey((p) => p + 1);
    } catch {}
  }, []);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 4_000);
    return () => clearInterval(iv);
  }, [refresh]);

  return (
    <div className="glass-panel" style={{ padding: "18px 20px", display: "flex", flexDirection: "column" }}>
      <style>{`@keyframes livepulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }`}</style>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Firm Narrative
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, color: "var(--text-tertiary)" }}>
          <span key={pulseKey} style={{
            display: "inline-block", width: 6, height: 6, borderRadius: "50%",
            background: "#22c55e", boxShadow: "0 0 6px #22c55e",
            animation: "livepulse 1.5s infinite",
          }} />
          LIVE · updated {lastUpdate ? `${Math.floor((Date.now() - lastUpdate.getTime()) / 1000)}s ago` : "—"}
        </div>
      </div>
      <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 12, lineHeight: 1.35 }}>
        Plain-English log of what the firm&apos;s been doing. Every event is a real cycle, trade, or decision from Redis streams.
      </div>

      {/* Summary stats */}
      {data && (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 14,
          padding: "10px 12px", background: "rgba(255,255,255,0.02)", borderRadius: 6,
          border: "1px solid var(--border-subtle)",
        }}>
          <div>
            <div style={{ fontSize: 9, color: "var(--text-tertiary)", textTransform: "uppercase" }}>Cycles</div>
            <div style={{ fontSize: 14, fontWeight: 700 }}>{data.summary.cycles_completed}</div>
          </div>
          <div>
            <div style={{ fontSize: 9, color: "var(--text-tertiary)", textTransform: "uppercase" }}>Approved</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--accent-profit)" }}>{data.summary.cycles_approved}</div>
          </div>
          <div>
            <div style={{ fontSize: 9, color: "var(--text-tertiary)", textTransform: "uppercase" }}>W / L</div>
            <div style={{ fontSize: 14, fontWeight: 700 }}>
              <span style={{ color: "var(--accent-profit)" }}>{data.summary.wins}</span>
              <span style={{ color: "var(--text-tertiary)" }}> / </span>
              <span style={{ color: "var(--accent-loss)" }}>{data.summary.losses}</span>
            </div>
          </div>
          <div>
            <div style={{ fontSize: 9, color: "var(--text-tertiary)", textTransform: "uppercase" }}>Pending</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: data.summary.pending > 0 ? "#f59e0b" : "var(--text-primary)" }}>
              {data.summary.pending}
            </div>
          </div>
        </div>
      )}

      {/* Events */}
      <div style={{ flex: 1, overflowY: "auto", maxHeight: 400, display: "flex", flexDirection: "column", gap: 6 }}>
        {!data ? (
          <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>Loading…</div>
        ) : data.events.length === 0 ? (
          <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
            Nothing yet — the firm will start posting here as cycles fire and trades execute.
          </div>
        ) : (
          data.events.map((e, i) => (
            <div key={i} style={{
              display: "grid", gridTemplateColumns: "10px 1fr 40px", gap: 8,
              alignItems: "baseline", padding: "5px 0",
              borderBottom: i < data.events.length - 1 ? "1px solid var(--border-subtle)" : "none",
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: "50%",
                background: SEV_DOT[e.severity], alignSelf: "center",
              }} />
              <span style={{ fontSize: 11, color: SEV_COLOR[e.severity], lineHeight: 1.45 }}>
                {e.text}
              </span>
              <span style={{ fontSize: 10, color: "var(--text-tertiary)", textAlign: "right", fontFamily: "var(--font-mono, monospace)" }}>
                {timeAgo(e.ts)}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
