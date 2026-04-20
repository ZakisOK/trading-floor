"use client";
import { useState, useEffect, useCallback, useMemo } from "react";
import { PageShell, SectionHeader } from "@/components/PageShell";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const COMMODITIES = [
  { symbol: "GC=F", name: "Gold", category: "Metals" },
  { symbol: "SI=F", name: "Silver", category: "Metals" },
  { symbol: "HG=F", name: "Copper", category: "Metals" },
  { symbol: "CL=F", name: "Crude Oil (WTI)", category: "Energy" },
  { symbol: "NG=F", name: "Natural Gas", category: "Energy" },
  { symbol: "ZW=F", name: "Wheat", category: "Grains" },
  { symbol: "ZC=F", name: "Corn", category: "Grains" },
  { symbol: "ZS=F", name: "Soybean", category: "Grains" },
];

interface Quote {
  symbol: string;
  last: number;
  previous_close: number;
  change: number;
  change_pct: number;
  currency: string;
  ts: string;
}

interface Signal {
  id: string;
  agent: string;
  symbol: string;
  direction: string;
  confidence: number;
  thesis: string;
  ts: string;
}

function directionColor(d: string) {
  if (d === "LONG") return "var(--accent-profit)";
  if (d === "SHORT") return "var(--accent-loss)";
  return "var(--text-tertiary)";
}

export default function CommoditiesPage() {
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [quotesRes, sigRes] = await Promise.allSettled([
        fetch(`${API}/api/commodities/quotes`).then((r) => r.json()),
        fetch(`${API}/api/signals/recent?limit=100`).then((r) => r.json()),
      ]);
      if (quotesRes.status === "fulfilled") {
        const map: Record<string, Quote> = {};
        for (const q of quotesRes.value?.quotes ?? []) map[q.symbol] = q;
        setQuotes(map);
      }
      if (sigRes.status === "fulfilled") setSignals(Array.isArray(sigRes.value) ? sigRes.value : []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, 30_000); // futures don't move as fast
    return () => clearInterval(t);
  }, [fetchData]);

  const byCategory = useMemo(() => {
    const groups: Record<string, typeof COMMODITIES> = {};
    for (const c of COMMODITIES) {
      groups[c.category] = groups[c.category] || [];
      groups[c.category].push(c);
    }
    return groups;
  }, []);

  function latestSignal(symbol: string): Signal | null {
    return signals.find((s) => s.symbol === symbol) || null;
  }

  return (
    <PageShell
      crumbs={["The Firm", "Markets", "Commodities"]}
      status={<div className="st"><span className="d ok" /> Yahoo futures feed · paper-only</div>}
    >
      <div className="mode-row">
        <span className="flag">PAPER ONLY</span>
        <div className="msg">COMEX/NYMEX/CBOT futures quotes via Yahoo Finance. Metals, energy, grains. <b>Broker refuses to route commodity orders to any live venue.</b></div>
      </div>

      {loading && (
        <div className="loader-pulse" style={{ padding: "20px 0" }}>
          <span className="pip" /><span>LOADING QUOTES…</span>
        </div>
      )}
      {!loading && Object.entries(byCategory).map(([cat, items], idx) => (
        <section key={cat}>
          <SectionHeader n={`0${idx + 1}`} label={cat} title={`${cat} futures`} sub={`${items.length} symbol${items.length !== 1 ? "s" : ""}`} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
            {items.map((c) => {
                const q = quotes[c.symbol];
                const sig = latestSignal(c.symbol);
                const changeColor = !q ? "var(--text-tertiary)" : q.change >= 0 ? "var(--accent-profit)" : "var(--accent-loss)";
                return (
                  <div key={c.symbol} className="card card-pad">
                    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 8 }}>
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text-primary)", letterSpacing: "-.01em" }}>{c.name}</div>
                        <div style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "var(--font-mono)", letterSpacing: ".08em", textTransform: "uppercase" }}>{c.symbol}</div>
                      </div>
                      {q ? (
                        <div style={{ textAlign: "right" }}>
                          <div style={{ fontSize: 18, fontFamily: "var(--font-mono)", color: "var(--text-primary)", letterSpacing: "-.024em" }}>
                            ${q.last.toFixed(2)}
                          </div>
                          <div style={{ fontSize: 11, color: changeColor, fontFamily: "var(--font-mono)", letterSpacing: "-.01em" }}>
                            {q.change >= 0 ? "+" : ""}${q.change.toFixed(2)} · {(q.change_pct * 100).toFixed(2)}%
                          </div>
                        </div>
                      ) : (
                        <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>No quote</span>
                      )}
                    </div>
                    {sig && (
                      <div style={{ paddingTop: 8, borderTop: "1px solid var(--line-hair)", marginTop: 6 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                          <span className={`dirw ${sig.direction === "LONG" ? "" : ""}`} style={{
                            fontFamily: "var(--font-mono)", fontSize: 9.5, letterSpacing: ".16em", fontWeight: 600,
                            padding: "2px 6px", borderRadius: 3,
                            background: sig.direction === "LONG" ? "var(--accent-profit-dim)" : sig.direction === "SHORT" ? "var(--accent-loss-dim)" : "rgba(148,163,184,.12)",
                            color: directionColor(sig.direction),
                          }}>{sig.direction}</span>
                          <span style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{(sig.confidence * 100).toFixed(0)}% · {sig.agent}</span>
                        </div>
                        <div style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.45 }}>
                          {sig.thesis.length > 160 ? sig.thesis.slice(0, 160) + "…" : sig.thesis}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        </section>
      ))}
    </PageShell>
  );
}
