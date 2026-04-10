"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { OHLCVBar } from "@/lib/api";
import { fetchOHLCV } from "@/lib/api";
import { useWebSocket } from "@/hooks/useWebSocket";
import { OHLCVChart } from "./OHLCVChart";
import { TimeframeToggle, type Timeframe } from "./TimeframeToggle";
import { ExchangeSelector, type ExchangeId } from "./ExchangeSelector";
import { DataFeedStatus } from "./DataFeedStatus";

const DEFAULT_SYMBOL = "BTC/USDT";
const DEFAULT_EXCHANGE: ExchangeId = "binance";
const DEFAULT_TIMEFRAME: Timeframe = "1h";

export function MarketExplorer() {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [symbolInput, setSymbolInput] = useState(DEFAULT_SYMBOL);
  const [exchange, setExchange] = useState<ExchangeId>(DEFAULT_EXCHANGE);
  const [timeframe, setTimeframe] = useState<Timeframe>(DEFAULT_TIMEFRAME);
  const [bars, setBars] = useState<OHLCVBar[]>([]);
  const [liveBar, setLiveBar] = useState<OHLCVBar | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // Load OHLCV from REST on symbol/exchange/timeframe change
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchOHLCV(symbol, exchange, timeframe, 300)
      .then((data) => {
        if (!cancelled) {
          setBars(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load data");
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [symbol, exchange, timeframe]);

  // WebSocket live updates
  const handleMessage = useCallback(
    (data: unknown) => {
      if (
        typeof data !== "object" ||
        data === null ||
        (data as Record<string, unknown>).type !== "ohlcv"
      ) {
        return;
      }
      const bar = data as OHLCVBar;
      if (bar.symbol === symbol && bar.exchange === exchange && bar.timeframe === timeframe) {
        setLiveBar(bar);
        setLastUpdate(new Date());
      }
    },
    [symbol, exchange, timeframe]
  );

  const wsStatus = useWebSocket(handleMessage);

  function handleSymbolSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSymbol(symbolInput.toUpperCase().trim());
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-4)",
        padding: "var(--space-6)",
        minHeight: "100vh",
        background: "var(--bg-base)",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "var(--space-3)",
        }}
      >
        <h1
          style={{
            fontSize: "18px",
            fontWeight: 600,
            letterSpacing: "-0.03em",
            color: "var(--text-primary)",
          }}
        >
          Market Explorer
        </h1>
        <DataFeedStatus wsStatus={wsStatus} lastUpdate={lastUpdate} />
      </div>

      {/* Controls */}
      <div className="glass-panel" style={{ padding: "var(--space-4)" }}>
        <div
          style={{
            display: "flex",
            gap: "var(--space-4)",
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          {/* Symbol input */}
          <form onSubmit={handleSymbolSubmit} style={{ display: "flex", gap: "6px" }}>
            <input
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value)}
              placeholder="Symbol e.g. BTC/USDT"
              style={{
                padding: "6px 12px",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-default)",
                background: "var(--bg-surface-3)",
                color: "var(--text-primary)",
                fontSize: "13px",
                fontFamily: "var(--font-mono)",
                outline: "none",
                width: "160px",
              }}
              aria-label="Symbol"
            />
            <button
              type="submit"
              style={{
                padding: "6px 14px",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-default)",
                background: "var(--accent-primary)",
                color: "#fff",
                fontSize: "12px",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Go
            </button>
          </form>

          {/* Exchange selector */}
          <ExchangeSelector value={exchange} onChange={setExchange} />

          {/* Timeframe toggle */}
          <TimeframeToggle value={timeframe} onChange={setTimeframe} />
        </div>
      </div>

      {/* Chart panel */}
      <div
        className="glass-panel"
        style={{ padding: "var(--space-4)", flex: 1, minHeight: "560px" }}
      >
        {/* Chart header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "var(--space-3)",
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: "8px" }}>
            <span
              style={{
                fontSize: "16px",
                fontWeight: 700,
                fontFamily: "var(--font-mono)",
                color: "var(--text-primary)",
                letterSpacing: "-0.02em",
              }}
            >
              {symbol}
            </span>
            <span style={{ fontSize: "11px", color: "var(--text-tertiary)" }}>
              {exchange.toUpperCase()} · {timeframe}
            </span>
          </div>
          {liveBar && (
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "20px",
                fontWeight: 700,
                color:
                  liveBar.close >= liveBar.open ? "var(--accent-profit)" : "var(--accent-loss)",
                letterSpacing: "-0.03em",
              }}
              aria-label={`Current price: ${liveBar.close}`}
            >
              {liveBar.close.toLocaleString("en-US", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 8,
              })}
            </div>
          )}
        </div>

        {loading && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "400px",
              color: "var(--text-tertiary)",
              fontSize: "13px",
            }}
            role="status"
            aria-label="Loading chart data"
          >
            Loading {symbol} {timeframe}...
          </div>
        )}

        {error && !loading && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "400px",
              gap: "8px",
            }}
            role="alert"
          >
            <span style={{ color: "var(--status-critical)", fontSize: "13px" }}>
              No data — {error}
            </span>
          </div>
        )}

        {!loading && !error && bars.length === 0 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "400px",
              color: "var(--text-tertiary)",
              fontSize: "13px",
            }}
          >
            No data for {symbol} {timeframe} on {exchange}. Start a data feed first.
          </div>
        )}

        {!loading && bars.length > 0 && (
          <OHLCVChart data={bars} liveBar={liveBar} height={520} />
        )}
      </div>

      {/* OHLCV stats row (last bar) */}
      {(liveBar ?? bars[bars.length - 1]) && (
        <div
          className="glass-panel"
          style={{ padding: "var(--space-3) var(--space-4)" }}
        >
          <OHLCVStats bar={liveBar ?? bars[bars.length - 1]} />
        </div>
      )}
    </div>
  );
}

function OHLCVStats({ bar }: { bar: OHLCVBar }) {
  const fields = [
    { label: "O", value: bar.open, color: "var(--text-secondary)" },
    {
      label: "H",
      value: bar.high,
      color: "var(--accent-profit)",
    },
    { label: "L", value: bar.low, color: "var(--accent-loss)" },
    {
      label: "C",
      value: bar.close,
      color: bar.close >= bar.open ? "var(--accent-profit)" : "var(--accent-loss)",
    },
    { label: "VOL", value: bar.volume, color: "var(--text-secondary)" },
  ];

  return (
    <div style={{ display: "flex", gap: "var(--space-6)", flexWrap: "wrap" }}>
      {fields.map((f) => (
        <div key={f.label} style={{ display: "flex", gap: "6px", alignItems: "baseline" }}>
          <span style={{ fontSize: "10px", color: "var(--text-tertiary)", letterSpacing: "0.05em" }}>
            {f.label}
          </span>
          <span
            style={{
              fontSize: "13px",
              fontFamily: "var(--font-mono)",
              fontWeight: 600,
              color: f.color,
              letterSpacing: "-0.02em",
            }}
          >
            {f.value.toLocaleString("en-US", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 6,
            })}
          </span>
        </div>
      ))}
    </div>
  );
}
