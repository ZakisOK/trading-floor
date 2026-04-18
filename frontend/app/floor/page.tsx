"use client";
import { useState } from "react";
import { LiveView } from "@/components/floor/LiveView";
import { AgentGrid } from "@/components/floor/AgentGrid";
import { SymbolConsensus } from "@/components/floor/SymbolConsensus";

type Tab = "live" | "agents" | "symbols";

const TABS: { key: Tab; label: string; sub: string }[] = [
  { key: "live", label: "Live Floor", sub: "Spatial view — agents, particles, bubbles" },
  { key: "agents", label: "Agent Grid", sub: "Performance cards — ELO, W/L, status" },
  { key: "symbols", label: "Symbol Consensus", sub: "What every symbol's getting voted" },
];

export default function FloorPage() {
  const [tab, setTab] = useState<Tab>("live");
  const current = TABS.find((t) => t.key === tab)!;

  return (
    <div style={{ padding: "28px 32px", maxWidth: 1400, margin: "0 auto", minHeight: "100vh" }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", letterSpacing: "-0.02em", margin: "0 0 6px 0" }}>
          Trading Floor
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-tertiary)", margin: 0 }}>
          {current.sub}
        </p>
      </div>

      <div style={{ display: "flex", gap: 2, marginBottom: 20, borderBottom: "1px solid var(--border-subtle)" }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              padding: "10px 18px",
              background: "transparent",
              border: "none",
              borderBottom: `2px solid ${tab === t.key ? "var(--accent-primary)" : "transparent"}`,
              color: tab === t.key ? "var(--text-primary)" : "var(--text-tertiary)",
              fontSize: 13,
              fontWeight: tab === t.key ? 600 : 400,
              cursor: "pointer",
              marginBottom: -1,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "live" && <LiveView />}
      {tab === "agents" && <AgentGrid />}
      {tab === "symbols" && <SymbolConsensus />}
    </div>
  );
}
