"use client";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1D"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

interface TimeframeToggleProps {
  value: Timeframe;
  onChange: (tf: Timeframe) => void;
}

export function TimeframeToggle({ value, onChange }: TimeframeToggleProps) {
  return (
    <div
      style={{
        display: "flex",
        gap: "2px",
        background: "var(--bg-surface-2)",
        borderRadius: "var(--radius-sm)",
        padding: "2px",
        border: "1px solid var(--border-subtle)",
      }}
    >
      {TIMEFRAMES.map((tf, i) => (
        <button
          key={tf}
          onClick={() => onChange(tf)}
          title={`Timeframe: ${tf} (${i + 1})`}
          style={{
            padding: "4px 10px",
            borderRadius: "4px",
            border: "none",
            cursor: "pointer",
            fontSize: "12px",
            fontFamily: "var(--font-mono)",
            fontWeight: value === tf ? 600 : 400,
            background: value === tf ? "var(--accent-primary)" : "transparent",
            color: value === tf ? "#fff" : "var(--text-secondary)",
            transition: "all 0.1s",
          }}
        >
          {tf}
        </button>
      ))}
    </div>
  );
}
