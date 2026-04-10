"use client";

import type { WSStatus } from "@/hooks/useWebSocket";

interface DataFeedStatusProps {
  wsStatus: WSStatus;
  lastUpdate: Date | null;
}

export function DataFeedStatus({ wsStatus, lastUpdate }: DataFeedStatusProps) {
  const isLive = wsStatus === "open";
  const age = lastUpdate ? Math.floor((Date.now() - lastUpdate.getTime()) / 1000) : null;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "4px 10px",
        borderRadius: "var(--radius-sm)",
        background: "var(--bg-surface-2)",
        border: "1px solid var(--border-subtle)",
        fontSize: "11px",
        fontFamily: "var(--font-mono)",
      }}
    >
      <span
        style={{
          width: "6px",
          height: "6px",
          borderRadius: "50%",
          background: isLive
            ? "var(--status-normal)"
            : wsStatus === "connecting"
              ? "var(--status-caution)"
              : "var(--status-off)",
          boxShadow: isLive ? "0 0 6px var(--status-normal)" : "none",
          flexShrink: 0,
        }}
        aria-hidden="true"
      />
      <span
        style={{ color: isLive ? "var(--status-normal)" : "var(--text-tertiary)" }}
        aria-label={`WebSocket status: ${wsStatus}`}
      >
        {isLive ? "LIVE" : wsStatus === "connecting" ? "CONNECTING" : "OFFLINE"}
      </span>
      {age !== null && (
        <span style={{ color: "var(--text-tertiary)" }}>
          {age === 0 ? "just now" : `${age}s ago`}
        </span>
      )}
    </div>
  );
}
