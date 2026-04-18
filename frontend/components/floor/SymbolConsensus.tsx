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

interface SymbolConsensus {
  symbol: string;
  total: number;
  long: number;
  short: number;
  neutral: number;
  avgConfidence: number;
  weightedDirection: "LONG" | "SHORT" | "NEUTRAL";
  weightedScore: number;
  agents: string[];
  topThesis: Signal | null;
  latestTs: string;
}

function directionColor(d: string) {
  if (d === "LONG") return "var(--accent-profit)";
  if (d === "SHORT") return "var(--accent-loss)";
  return "var(--text-tertiary)";
}

function timeAgo(iso: string): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

function formatAgent(id: string) {
  if (!id) return "?";
  if (id === "xrp_analyst") return "XRP Analyst";
  if (id === "polymarket_scout") return "Polymarket";
  if (id === "copy_trade_scout") return "Copy Scout";
  return id.charAt(0).toUpperCase() + id.slice(1);
}

function buildConsensus(signals: Signal[]): SymbolConsensus[] {
  const bySymbol = new Map<string, Signal[]>();
  for (const s of signals) {
    if (!bySymbol.has(s.symbol)) bySymbol.set(s.symbol, []);
    bySymbol.get(s.symbol)!.push(s);
  }

  const out: SymbolConsensus[] = [];
  for (const [symbol, arr] of bySymbol.entries()) {
    const long = arr.filter((s) => s.direction === "LONG").length;
    const short = arr.filter((s) => s.direction === "SHORT").length;
    const neutral = arr.filter((s) => s.direction === "NEUTRAL").length;

    const scoreSum = arr.reduce((acc, s) => {
      if (s.direction === "LONG") return acc + s.confidence;
      if (s.direction === "SHORT") return acc - s.confidence;
      return acc;
    }, 0);
    const weightedScore = arr.length ? scoreSum / arr.length : 0;
    const weightedDirection: SymbolConsensus["weightedDirection"] =
      weightedScore > 0.15 ? "LONG" : weightedScore < -0.15 ? "SHORT" : "NEUTRAL";

    const avgConfidence = arr.reduce((a, s) => a + s.confidence, 0) / arr.length;
    const directional = arr.filter((s) => s.direction === weightedDirection);
    const topThesis = (directional.length ? directional : arr).reduce(
      (a, b) => (a.confidence > b.confidence ? a : b),
    );

    out.push({
      symbol,
      total: arr.length,
      long,
      short,
      neutral,
      avgConfidence,
      weightedDirection,
      weightedScore,
      agents: Array.from(new Set(arr.map((s) => s.agent))),
      topThesis,
      latestTs: arr.reduce((a, b) => (a.ts > b.ts ? a : b)).ts,
    });
  }
  out.sort((a, b) => Math.abs(b.weightedScore) - Math.abs(a.weightedScore));
  return out;
}

function ConsensusBar({ long, short, neutral }: { long: number; short: number; neutral: number }) {
  const total = long + short + neutral || 1;
  return (
    <div style={{ display: "flex", height: 6, borderRadius: 3, overflow: "hidden", background: "var(--border-subtle)" }}>
      <div style={{ width: `${(long / total) * 100}%`, background: "var(--accent-profit)" }} />
      <div style={{ width: `${(neutral / total) * 100}%`, background: "var(--text-tertiary)" }} />
      <div style={{ width: `${(short / total) * 100}%`, background: "var(--accent-loss)" }} />
    </div>
  );
}

function SymbolCard({ c }: { c: SymbolConsensus }) {
  const color = directionColor(c.weightedDirection);
  return (
    <div className="glass-panel" style={{
      padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12,
      borderLeft: `3px solid ${color}`,
    }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>{c.symbol}</span>
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.05em",
            padding: "2px 7px", borderRadius: 3,
            background: `${color}22`, color, border: `1px solid ${color}66`,
          }}>
            {c.weightedDirection}
          </span>
          <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
            {(c.avgConfidence * 100).toFixed(0)}% avg conf
          </span>
        </div>
        <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{timeAgo(c.latestTs)}</span>
      </div>

      <ConsensusBar long={c.long} short={c.short} neutral={c.neutral} />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-tertiary)" }}>
        <span style={{ color: "var(--accent-profit)" }}>{c.long} long</span>
        <span>{c.neutral} neutral</span>
        <span style={{ color: "var(--accent-loss)" }}>{c.short} short</span>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {c.agents.map((a) => (
          <span key={a} style={{
            fontSize: 9, padding: "1px 6px", borderRadius: 10,
            background: "rgba(255,255,255,0.05)", color: "var(--text-secondary)",
            border: "1px solid var(--border-subtle)",
          }}>
            {formatAgent(a)}
          </span>
        ))}
      </div>

      {c.topThesis && (
        <div style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.45, paddingTop: 8, borderTop: "1px solid var(--border-subtle)" }}>
          <div style={{ fontSize: 9, color: "var(--text-tertiary)", marginBottom: 4, letterSpacing: "0.05em", textTransform: "uppercase" }}>
            Top thesis — {formatAgent(c.topThesis.agent)} · {(c.topThesis.confidence * 100).toFixed(0)}%
          </div>
          {c.topThesis.thesis.length > 200 ? c.topThesis.thesis.slice(0, 200) + "…" : c.topThesis.thesis}
        </div>
      )}
    </div>
  );
}

export function SymbolConsensus() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "crypto" | "commodity">("all");

  const fetchSignals = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/signals/recent?limit=100`);
      if (r.ok) setSignals(await r.json());
    } catch (e) {
      console.error("copy-trade fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSignals();
    const t = setInterval(fetchSignals, 5000);
    return () => clearInterval(t);
  }, [fetchSignals]);

  const filteredSignals = useMemo(() => {
    if (filter === "all") return signals;
    const isCommodity = (s: string) => s.includes("=F") || !!s.match(/^(GC|CL|SI|HG|NG|ZW|ZC|ZS)/);
    return signals.filter((s) =>
      filter === "commodity" ? isCommodity(s.symbol) : !isCommodity(s.symbol),
    );
  }, [signals, filter]);

  const consensus = useMemo(() => buildConsensus(filteredSignals), [filteredSignals]);
  const activeSymbols = consensus.length;
  const longLeaning = consensus.filter((c) => c.weightedDirection === "LONG").length;
  const shortLeaning = consensus.filter((c) => c.weightedDirection === "SHORT").length;
  const recent = useMemo(() => [...filteredSignals].sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 20), [filteredSignals]);

  return (
    <div>
      <p style={{ fontSize: 12, color: "var(--text-tertiary)", margin: "0 0 18px 0" }}>
        Live consensus across every symbol. Weighted by confidence — stronger conviction counts more than raw agent count.
      </p>

      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 6 }}>
          {(["all", "crypto", "commodity"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)} style={{
              padding: "6px 14px", borderRadius: 4, fontSize: 12, fontWeight: 600,
              border: `1px solid ${filter === f ? "var(--accent-primary)" : "var(--border-default)"}`,
              background: filter === f ? "rgba(94,106,210,0.15)" : "transparent",
              color: filter === f ? "var(--accent-primary)" : "var(--text-secondary)",
              cursor: "pointer",
            }}>
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 18, fontSize: 11, color: "var(--text-tertiary)" }}>
          <span>{activeSymbols} active</span>
          <span style={{ color: "var(--accent-profit)" }}>{longLeaning} long-leaning</span>
          <span style={{ color: "var(--accent-loss)" }}>{shortLeaning} short-leaning</span>
          <span>{signals.length} signals</span>
        </div>
      </div>

      {loading ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--text-tertiary)" }}>Loading signals…</div>
      ) : consensus.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--text-tertiary)" }}>
          No signals yet for this filter. Agents run every 2-5 min.
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14, marginBottom: 28 }}>
          {consensus.map((c) => <SymbolCard key={c.symbol} c={c} />)}
        </div>
      )}

      <div className="glass-panel" style={{ padding: "18px 20px" }}>
        <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 12 }}>
          Recent signals — chronological
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {recent.map((s) => (
            <div key={s.id} style={{
              display: "grid",
              gridTemplateColumns: "70px 100px 100px 70px 1fr",
              gap: 10, alignItems: "baseline", fontSize: 11, paddingBottom: 8,
              borderBottom: "1px solid var(--border-subtle)",
            }}>
              <span style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>{timeAgo(s.ts)}</span>
              <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{formatAgent(s.agent)}</span>
              <span style={{ color: "var(--text-secondary)" }}>{s.symbol}</span>
              <span style={{ fontWeight: 700, color: directionColor(s.direction) }}>{s.direction}</span>
              <span style={{ color: "var(--text-secondary)", lineHeight: 1.45 }}>
                {(s.confidence * 100).toFixed(0)}% · {s.thesis.length > 140 ? s.thesis.slice(0, 140) + "…" : s.thesis}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

