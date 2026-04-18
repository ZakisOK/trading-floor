"use client";
import { useState, useEffect, useCallback, useMemo } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Signal {
  id: string;
  agent: string;
  symbol: string;
  direction: "LONG" | "SHORT" | "NEUTRAL";
  confidence: number;
  thesis: string;
  ts: string;
}

function directionColor(d: string) {
  if (d === "LONG") return "var(--accent-profit)";
  if (d === "SHORT") return "var(--accent-loss)";
  return "var(--text-tertiary)";
}

function timeAgo(iso: string): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h`;
  return `${Math.floor(ms / 86_400_000)}d`;
}

function formatAgent(id: string) {
  if (!id) return "?";
  if (id === "xrp_analyst") return "XRP Analyst";
  if (id === "polymarket_scout") return "Polymarket";
  return id.charAt(0).toUpperCase() + id.slice(1);
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [agentFilter, setAgentFilter] = useState<string>("all");
  const [directionFilter, setDirectionFilter] = useState<string>("all");

  const fetchSignals = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/signals/recent?limit=100`);
      if (r.ok) setSignals(await r.json());
    } catch (e) {
      console.error("signals fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSignals();
    const t = setInterval(fetchSignals, 5000);
    return () => clearInterval(t);
  }, [fetchSignals]);

  const agents = useMemo(() => Array.from(new Set(signals.map((s) => s.agent))), [signals]);
  const filtered = useMemo(() => {
    return signals.filter((s) =>
      (agentFilter === "all" || s.agent === agentFilter) &&
      (directionFilter === "all" || s.direction === directionFilter),
    );
  }, [signals, agentFilter, directionFilter]);

  return (
    <div style={{ padding: "28px 32px", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", letterSpacing: "-0.02em", margin: "0 0 6px 0" }}>
          Signals
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-tertiary)", margin: 0 }}>
          Every signal emitted by every agent, newest first. Use this to audit individual agent reasoning — what Marcus saw that Vera missed, which symbol Rex has been bearish on, etc. Refreshes every 5s.
        </p>
      </div>

      <div style={{ display: "flex", gap: 14, marginBottom: 16, alignItems: "center" }}>
        <div>
          <label style={{ fontSize: 10, color: "var(--text-tertiary)", marginRight: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>Agent</label>
          <select value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)} style={{
            background: "var(--bg-surface-2)", border: "1px solid var(--border-default)",
            borderRadius: 4, color: "var(--text-primary)", padding: "5px 8px", fontSize: 12,
          }}>
            <option value="all">All</option>
            {agents.map((a) => <option key={a} value={a}>{formatAgent(a)}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 10, color: "var(--text-tertiary)", marginRight: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>Direction</label>
          <select value={directionFilter} onChange={(e) => setDirectionFilter(e.target.value)} style={{
            background: "var(--bg-surface-2)", border: "1px solid var(--border-default)",
            borderRadius: 4, color: "var(--text-primary)", padding: "5px 8px", fontSize: 12,
          }}>
            <option value="all">All</option>
            <option value="LONG">LONG</option>
            <option value="SHORT">SHORT</option>
            <option value="NEUTRAL">NEUTRAL</option>
          </select>
        </div>
        <div style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-tertiary)" }}>
          {filtered.length} / {signals.length} signals
        </div>
      </div>

      <div className="glass-panel" style={{ padding: "0", overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 32, textAlign: "center", color: "var(--text-tertiary)" }}>Loading…</div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", color: "var(--text-tertiary)" }}>No signals match your filter.</div>
        ) : (
          <div>
            <div style={{
              display: "grid",
              gridTemplateColumns: "60px 100px 100px 80px 80px 1fr",
              gap: 10, padding: "10px 16px", fontSize: 10,
              color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em",
              borderBottom: "1px solid var(--border-subtle)",
            }}>
              <span>Ago</span>
              <span>Agent</span>
              <span>Symbol</span>
              <span>Direction</span>
              <span>Conf.</span>
              <span>Thesis</span>
            </div>
            {filtered.map((s) => (
              <div key={s.id} style={{
                display: "grid",
                gridTemplateColumns: "60px 100px 100px 80px 80px 1fr",
                gap: 10, padding: "12px 16px", fontSize: 12,
                borderBottom: "1px solid var(--border-subtle)",
                alignItems: "baseline",
              }}>
                <span style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>{timeAgo(s.ts)}</span>
                <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{formatAgent(s.agent)}</span>
                <span style={{ color: "var(--text-secondary)" }}>{s.symbol}</span>
                <span style={{ fontWeight: 700, color: directionColor(s.direction) }}>{s.direction}</span>
                <span style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono, monospace)" }}>{(s.confidence * 100).toFixed(0)}%</span>
                <span style={{ color: "var(--text-secondary)", lineHeight: 1.45 }}>
                  {s.thesis.length > 220 ? s.thesis.slice(0, 220) + "…" : s.thesis}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
