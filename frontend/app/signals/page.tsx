"use client";
import { useState, useEffect, useCallback, useMemo } from "react";
import { PageShell, SectionHeader } from "@/components/PageShell";

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

function timeAgo(iso: string): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (isNaN(ms)) return "—";
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
  const [loaded, setLoaded] = useState(false);
  const [agentFilter, setAgentFilter] = useState<string>("all");
  const [directionFilter, setDirectionFilter] = useState<"all" | "LONG" | "SHORT" | "NEUTRAL">("all");

  const fetchSignals = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/signals/recent?limit=100`);
      if (r.ok) setSignals(await r.json());
    } catch { /* swallow */ }
    finally { setLoaded(true); }
  }, []);

  useEffect(() => { fetchSignals(); const t = setInterval(fetchSignals, 5000); return () => clearInterval(t); }, [fetchSignals]);

  const agents = useMemo(() => Array.from(new Set(signals.map(s => s.agent))).filter(Boolean).sort(), [signals]);
  const filtered = useMemo(() =>
    signals.filter(s =>
      (agentFilter === "all" || s.agent === agentFilter) &&
      (directionFilter === "all" || s.direction === directionFilter),
    ),
    [signals, agentFilter, directionFilter]
  );

  const longCount = signals.filter(s => s.direction === "LONG").length;
  const shortCount = signals.filter(s => s.direction === "SHORT").length;
  const neutralCount = signals.filter(s => s.direction === "NEUTRAL").length;
  const avgConf = signals.length > 0 ? signals.reduce((a, s) => a + (s.confidence ?? 0), 0) / signals.length : 0;

  return (
    <PageShell
      crumbs={["The Firm", "Signals"]}
      status={<>
        <div className="st"><span className="d ok" /> {signals.length} signals · {agents.length} agents</div>
      </>}
    >
      {/* Briefing */}
      <div className="briefing">
        <div className="left">
          <div className="eyebrow"><span className="num">01</span><span>·</span><span>Signal stream</span>
            <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>Refresh every 5s</span>
          </div>
          <p className="headline">
            Every signal every agent emits, newest first. Use this to audit reasoning — what Marcus saw that Vera missed,
            which symbol Rex has been bearish on, etc.
          </p>
          <div className="figure-stack">
            <span className="lbl">Conviction</span>
            <span className="big">{Math.round(avgConf * 100)}<span className="cents">%</span></span>
            <span className="delta">
              <span className="v up">{longCount} LONG</span>
              <span className="pip" />
              <span className="v dn">{shortCount} SHORT</span>
              <span className="pip" />
              <span>{neutralCount} neutral</span>
            </span>
          </div>
        </div>
        <div className="right">
          <div className="cell"><div className="k"><span>Total signals</span><span className="n">02</span></div><div className="v">{signals.length}</div><div className="sub"><span>Last 100 emissions</span></div></div>
          <div className="cell"><div className="k"><span>LONG</span><span className="n">03</span></div><div className="v up">{longCount}</div><div className="sub"><span className="bar-mini"><span className="fill" style={{ width: `${signals.length > 0 ? (longCount / signals.length) * 100 : 0}%`, background: "var(--accent-profit)" }} /></span></div></div>
          <div className="cell"><div className="k"><span>SHORT</span><span className="n">04</span></div><div className="v dn">{shortCount}</div><div className="sub"><span className="bar-mini"><span className="fill" style={{ width: `${signals.length > 0 ? (shortCount / signals.length) * 100 : 0}%`, background: "var(--accent-loss)" }} /></span></div></div>
          <div className="cell"><div className="k"><span>Agents reporting</span><span className="n">05</span></div><div className="v">{agents.length}</div><div className="sub"><span>Unique emitters</span></div></div>
        </div>
      </div>

      {/* Filter + feed */}
      <section>
        <SectionHeader
          n="02"
          label="Stream"
          title="Every signal, newest first"
          sub={`${filtered.length} / ${signals.length} match filters`}
          tools={
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <div className="seg">
                {(["all", "LONG", "SHORT", "NEUTRAL"] as const).map(d => (
                  <button key={d} className={directionFilter === d ? "on" : ""} onClick={() => setDirectionFilter(d)}>{d}</button>
                ))}
              </div>
              <select
                value={agentFilter}
                onChange={e => setAgentFilter(e.target.value)}
                style={{
                  background: "rgba(0,0,0,.35)", border: "1px solid var(--line-fine)",
                  borderRadius: 6, color: "var(--text-primary)", padding: "5px 10px",
                  fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: ".14em",
                  textTransform: "uppercase",
                }}
              >
                <option value="all">All agents</option>
                {agents.map(a => <option key={a} value={a}>{formatAgent(a)}</option>)}
              </select>
            </div>
          }
        />

        <div className="card sig-card">
          <div className="sig-list">
            {!loaded && (
              <div style={{ padding: "24px", color: "var(--text-tertiary)", fontSize: 13 }} className="loader-pulse">
                <span className="pip" />LOADING SIGNALS…
              </div>
            )}
            {loaded && filtered.length === 0 && (
              <div style={{ padding: "24px", color: "var(--text-tertiary)", fontSize: 13 }}>No signals match your filter.</div>
            )}
            {filtered.map((s, i) => {
              const dir = (s.direction || "NEUTRAL").toUpperCase();
              const cls = dir === "LONG" ? "long" : dir === "SHORT" ? "short" : "neutral";
              return (
                <div key={s.id || i} className={`signal ${cls}`}>
                  <span className="num">{String(i + 1).padStart(3, "0")}</span>
                  <div className="body">
                    <div className="line">
                      <span className="sym">{s.symbol}</span>
                      <span className="dirw">{dir}</span>
                      <span className="from">via <b>{formatAgent(s.agent)}</b></span>
                    </div>
                    {s.thesis && <div className="thesis">{s.thesis.length > 220 ? s.thesis.slice(0, 220) + "…" : s.thesis}</div>}
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
      </section>
    </PageShell>
  );
}
