"use client";
import { useState } from "react";
import { LiveView } from "@/components/floor/LiveView";
import { AgentGrid } from "@/components/floor/AgentGrid";
import { SymbolConsensus } from "@/components/floor/SymbolConsensus";
import { PageShell } from "@/components/PageShell";

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
    <PageShell
      crumbs={["The Firm", "Intelligence", "Trading Floor"]}
      status={<div className="st"><span className="d ok" /> {current.sub}</div>}
    >
      <div className="mode-row">
        <span className="flag">THE FLOOR</span>
        <div className="msg">Visual and statistical views of what the agents are doing right now.</div>
        <div className="tools">
          <div className="seg">
            {TABS.map((t) => (
              <button key={t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {tab === "live" && <LiveView />}
      {tab === "agents" && <AgentGrid />}
      {tab === "symbols" && <SymbolConsensus />}
    </PageShell>
  );
}
