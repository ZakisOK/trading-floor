"use client";
import { useState, useEffect, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface QueueItem {
  symbol: string;
  interval_s: number;
  last_run: string;
  next_run: string;
  seconds_until_next: number;
  is_running_now: boolean;
}

interface InProgress {
  agent: string;
  desk: string;
  symbol: string | null;
  since: string | null;
}

interface DeskInfo {
  key: string;
  label: string;
  agents: string[];
  active_count: number;
  active: InProgress[];
}

interface Completion {
  symbol: string;
  finished_at: string;
  duration_s: number;
  decision: string;
  signals: number;
  approved: boolean;
}

interface TasksPayload {
  queue: QueueItem[];
  in_progress: InProgress[];
  desks: DeskInfo[];
  recent_completions: Completion[];
}

const DESK_COLORS: Record<string, string> = {
  research: "#9677D0",
  execution: "#22C55E",
  oversight: "#F89318",
};

function formatCountdown(s: number): string {
  if (s < 1) return "due now";
  if (s < 60) return `in ${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s - m * 60);
  return rem > 0 ? `in ${m}m ${rem}s` : `in ${m}m`;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  return `${Math.floor(ms / 3_600_000)}h ago`;
}

function decisionColor(d: string) {
  if (d === "LONG") return "var(--accent-profit)";
  if (d === "SHORT") return "var(--accent-loss)";
  return "var(--text-tertiary)";
}

export function DeskTasksPanel() {
  const [data, setData] = useState<TasksPayload | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/desks/tasks`);
      if (r.ok) setData(await r.json());
    } catch {}
  }, []);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 2_000);
    return () => clearInterval(iv);
  }, [refresh]);

  if (!data) {
    return (
      <div className="glass-panel" style={{ padding: 16, fontSize: 12, color: "var(--text-tertiary)" }}>
        Loading desk tasks…
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, marginBottom: 24 }}>
      {/* QUEUE — upcoming cycles */}
      <div className="glass-panel" style={{ padding: "14px 16px" }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>
          Task Queue
        </div>
        <div style={{ fontSize: 9, color: "var(--text-tertiary)", marginBottom: 10, lineHeight: 1.35 }}>
          Symbols next up for a full agent cycle (Alpha Research → Trade Execution → Portfolio Oversight).
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 220, overflowY: "auto" }}>
          {data.queue.slice(0, 10).map((q) => (
            <div key={q.symbol} style={{
              display: "grid", gridTemplateColumns: "90px 1fr 70px", gap: 6, alignItems: "baseline",
              padding: "4px 0", fontSize: 11,
            }}>
              <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{q.symbol}</span>
              <span style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)", fontSize: 10 }}>
                every {q.interval_s < 60 ? `${q.interval_s}s` : `${Math.round(q.interval_s / 60)}m`}
              </span>
              <span style={{ color: q.seconds_until_next < 15 ? "var(--accent-profit)" : "var(--text-secondary)", textAlign: "right", fontFamily: "var(--font-mono, monospace)", fontSize: 10 }}>
                {formatCountdown(q.seconds_until_next)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* IN-PROGRESS per desk */}
      <div className="glass-panel" style={{ padding: "14px 16px" }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>
          In Flight
        </div>
        <div style={{ fontSize: 9, color: "var(--text-tertiary)", marginBottom: 10, lineHeight: 1.35 }}>
          Agents actively working right now. Green = active heartbeat.
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {data.desks.map((d) => {
            const color = DESK_COLORS[d.key] || "var(--text-secondary)";
            return (
              <div key={d.key}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 3 }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color }}>{d.label}</span>
                  <span style={{ fontSize: 10, color: d.active_count > 0 ? "var(--accent-profit)" : "var(--text-tertiary)" }}>
                    {d.active_count}/{d.agents.length} working
                  </span>
                </div>
                {d.active.length === 0 ? (
                  <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>all idle</div>
                ) : (
                  d.active.map((a) => (
                    <div key={a.agent} style={{
                      display: "flex", justifyContent: "space-between", fontSize: 10,
                      padding: "2px 0",
                    }}>
                      <span style={{ color: "var(--text-secondary)", textTransform: "capitalize" }}>
                        {a.agent.replace("_", " ")}
                      </span>
                      {a.symbol && (
                        <span style={{ color: "var(--text-primary)", fontFamily: "var(--font-mono, monospace)" }}>
                          {a.symbol}
                        </span>
                      )}
                    </div>
                  ))
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* RECENT COMPLETIONS */}
      <div className="glass-panel" style={{ padding: "14px 16px" }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>
          Recent Cycles
        </div>
        <div style={{ fontSize: 9, color: "var(--text-tertiary)", marginBottom: 10, lineHeight: 1.35 }}>
          Last 10 completed cycles with final decision.
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 220, overflowY: "auto" }}>
          {data.recent_completions.length === 0 ? (
            <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>No cycles completed yet</div>
          ) : (
            data.recent_completions.map((c, i) => (
              <div key={i} style={{
                display: "grid", gridTemplateColumns: "90px 60px 40px 1fr", gap: 6,
                padding: "3px 0", fontSize: 10, alignItems: "baseline",
              }}>
                <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>{c.symbol}</span>
                <span style={{ fontWeight: 700, color: decisionColor(c.decision) }}>{c.decision}</span>
                <span style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>
                  {c.duration_s.toFixed(0)}s
                </span>
                <span style={{ color: "var(--text-tertiary)", textAlign: "right", fontFamily: "var(--font-mono, monospace)" }}>
                  {timeAgo(c.finished_at)}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
