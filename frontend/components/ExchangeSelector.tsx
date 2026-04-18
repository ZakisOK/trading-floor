"use client";

const EXCHANGES = [
  { id: "coinbase", label: "Coinbase", class: "crypto" },
  { id: "kraken", label: "Kraken", class: "crypto" },
  { id: "alpaca", label: "Alpaca", class: "equity" },
] as const;

export type ExchangeId = (typeof EXCHANGES)[number]["id"];

interface ExchangeSelectorProps {
  value: ExchangeId;
  onChange: (exchange: ExchangeId) => void;
}

export function ExchangeSelector({ value, onChange }: ExchangeSelectorProps) {
  return (
    <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
      {EXCHANGES.map((ex) => (
        <button
          key={ex.id}
          onClick={() => onChange(ex.id)}
          style={{
            padding: "5px 12px",
            borderRadius: "var(--radius-sm)",
            border: `1px solid ${value === ex.id ? "var(--accent-primary)" : "var(--border-default)"}`,
            background: value === ex.id ? "rgba(94,106,210,0.15)" : "transparent",
            color: value === ex.id ? "var(--accent-primary)" : "var(--text-secondary)",
            fontSize: "12px",
            fontWeight: value === ex.id ? 600 : 400,
            cursor: "pointer",
            transition: "all 0.1s",
          }}
        >
          {ex.label}
          <span
            style={{
              marginLeft: "5px",
              fontSize: "10px",
              opacity: 0.6,
              textTransform: "uppercase",
            }}
          >
            {ex.class}
          </span>
        </button>
      ))}
    </div>
  );
}
