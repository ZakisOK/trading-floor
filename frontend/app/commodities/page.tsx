"use client";
import { useState, useEffect, useCallback, useMemo } from "react";

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
    <div style={{ padding: "28px 32px", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", letterSpacing: "-0.02em", margin: "0 0 6px 0" }}>
          Commodities
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-tertiary)", margin: 0 }}>
          COMEX/NYMEX/CBOT futures quotes via Yahoo Finance (free, real-time-ish, 15-min delayed on some feeds). Metals, energy, grains. Paper-only — the broker refuses to route commodity orders to any live venue.
        </p>
      </div>

      {loading ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--text-tertiary)" }}>Loading quotes…</div>
      ) : (
        Object.entries(byCategory).map(([cat, items]) => (
          <div key={cat} style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 10 }}>
              {cat}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
              {items.map((c) => {
                const q = quotes[c.symbol];
                const sig = latestSignal(c.symbol);
                const changeColor = !q ? "var(--text-tertiary)" : q.change >= 0 ? "var(--accent-profit)" : "var(--accent-loss)";
                return (
                  <div key={c.symbol} className="glass-panel" style={{ padding: "14px 16px" }}>
                    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 8 }}>
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>{c.name}</div>
                        <div style={{ fontSize: 10, color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>{c.symbol}</div>
                      </div>
                      {q ? (
                        <div style={{ textAlign: "right" }}>
                          <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono, monospace)", color: "var(--text-primary)" }}>
                            ${q.last.toFixed(2)}
                          </div>
                          <div style={{ fontSize: 11, fontWeight: 600, color: changeColor, fontFamily: "var(--font-mono, monospace)" }}>
                            {q.change >= 0 ? "+" : ""}${q.change.toFixed(2)} ({(q.change_pct * 100).toFixed(2)}%)
                          </div>
                        </div>
                      ) : (
                        <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>No quote</span>
                      )}
                    </div>
                    {sig && (
                      <div style={{ paddingTop: 8, borderTop: "1px solid var(--border-subtle)" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: directionColor(sig.direction) }}>{sig.direction}</span>
                          <span style={{ fontSize: 10, color: "var(--text-secondary)" }}>{(sig.confidence * 100).toFixed(0)}% · {sig.agent}</span>
                        </div>
                        <div style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.4 }}>
                          {sig.thesis.length > 160 ? sig.thesis.slice(0, 160) + "…" : sig.thesis}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
