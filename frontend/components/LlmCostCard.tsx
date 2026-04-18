"use client";
import { useState, useEffect } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface CostPayload {
  today: {
    cost_usd: number;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    by_model: Record<string, { calls?: number; input?: number; output?: number }>;
  };
  all_time: {
    cost_usd: number;
    calls: number;
    input_tokens: number;
    output_tokens: number;
  };
  history_7d: { date: string; cost: number; calls: number }[];
}

export function LlmCostCard() {
  const [data, setData] = useState<CostPayload | null>(null);

  useEffect(() => {
    const fetchCosts = async () => {
      try {
        const r = await fetch(`${API}/api/llm/costs`);
        if (r.ok) setData(await r.json());
      } catch {}
    };
    fetchCosts();
    const t = setInterval(fetchCosts, 30_000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="glass-panel" style={{ padding: "18px 20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          LLM Cost
        </div>
        <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
          What the agents have spent on Claude today
        </div>
      </div>
      {data ? (
        <>
          <div style={{ display: "flex", gap: 20, marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>Today</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: "var(--text-primary)", fontFamily: "var(--font-mono, monospace)" }}>
                ${data.today.cost_usd.toFixed(4)}
              </div>
              <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
                {data.today.calls.toLocaleString()} calls · {(data.today.input_tokens / 1000).toFixed(1)}K in / {(data.today.output_tokens / 1000).toFixed(1)}K out
              </div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>All-time</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text-secondary)", fontFamily: "var(--font-mono, monospace)" }}>
                ${data.all_time.cost_usd.toFixed(2)}
              </div>
              <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
                {data.all_time.calls.toLocaleString()} calls
              </div>
            </div>
          </div>
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 4 }}>By model (today)</div>
            {Object.keys(data.today.by_model).length === 0 ? (
              <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>No calls yet today</div>
            ) : (
              Object.entries(data.today.by_model).map(([model, m]) => (
                <div key={model} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, padding: "3px 0" }}>
                  <span style={{ color: "var(--text-secondary)" }}>{model.replace(/claude-|-2025.*/g, "")}</span>
                  <span style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>
                    {m.calls} calls · {(m.input || 0) / 1000 | 0}K+{(m.output || 0) / 1000 | 0}K tok
                  </span>
                </div>
              ))
            )}
          </div>
        </>
      ) : (
        <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>Loading…</div>
      )}
    </div>
  );
}
