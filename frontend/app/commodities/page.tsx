"use client";
import { useState, useEffect, useCallback, useMemo } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const COMMODITY_SYMBOLS = [
  { symbol: "GC=F", name: "Gold Futures", category: "Metals" },
  { symbol: "SI=F", name: "Silver Futures", category: "Metals" },
  { symbol: "HG=F", name: "Copper Futures", category: "Metals" },
  { symbol: "CL=F", name: "Crude Oil Futures", category: "Energy" },
  { symbol: "NG=F", name: "Natural Gas Futures", category: "Energy" },
  { symbol: "ZW=F", name: "Wheat Futures", category: "Grains" },
  { symbol: "ZC=F", name: "Corn Futures", category: "Grains" },
  { symbol: "ZS=F", name: "Soybean Futures", category: "Grains" },
];

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

export default function CommoditiesPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchSignals = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/signals/recent?limit=100`);
      if (r.ok) setSignals(await r.json());
    } catch (e) {
      console.error("commodities fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSignals();
    const t = setInterval(fetchSignals, 5000);
    return () => clearInterval(t);
  }, [fetchSignals]);

  const byCategory = useMemo(() => {
    const groups: Record<string, typeof COMMODITY_SYMBOLS> = {};
    for (const c of COMMODITY_SYMBOLS) {
      groups[c.category] = groups[c.category] || [];
      groups[c.category].push(c);
    }
    return groups;
  }, []);

  function signalsFor(symbol: string) {
    return signals.filter((s) => s.symbol === symbol).slice(0, 3);
  }

  return (
    <div style={{ padding: "28px 32px", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", letterSpacing: "-0.02em", margin: "0 0 6px 0" }}>
          Commodities
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-tertiary)", margin: 0 }}>
          Futures tracked by the floor: metals, energy, grains. Commodities always stay in paper mode — the broker enforces it. Live prices are not yet wired in (Coinbase doesn't cover futures); this page shows the latest agent signals per symbol.
        </p>
      </div>

      {loading && signals.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--text-tertiary)" }}>Loading…</div>
      ) : (
        Object.entries(byCategory).map(([cat, items]) => (
          <div key={cat} style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 10 }}>
              {cat}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
              {items.map((c) => {
                const sigs = signalsFor(c.symbol);
                const latest = sigs[0];
                return (
                  <div key={c.symbol} className="glass-panel" style={{ padding: "14px 16px" }}>
                    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 6 }}>
                      <span style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>{c.name}</span>
                      <span style={{ fontSize: 11, color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>{c.symbol}</span>
                    </div>
                    {latest ? (
                      <>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: directionColor(latest.direction) }}>{latest.direction}</span>
                          <span style={{ fontSize: 10, color: "var(--text-secondary)" }}>{(latest.confidence * 100).toFixed(0)}% · {latest.agent}</span>
                        </div>
                        <div style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.45 }}>
                          {latest.thesis.length > 180 ? latest.thesis.slice(0, 180) + "…" : latest.thesis}
                        </div>
                      </>
                    ) : (
                      <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>No recent signal. Agents cycle every 5 min.</div>
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
