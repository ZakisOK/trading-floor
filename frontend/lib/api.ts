const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

export interface OHLCVBar {
  symbol: string;
  exchange: string;
  timeframe: string;
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SymbolInfo {
  symbol: string;
  exchange: string;
  asset_class: string;
  base: string;
  quote: string;
}

export async function fetchOHLCV(
  symbol: string,
  exchange: string,
  timeframe: string,
  limit = 200
): Promise<OHLCVBar[]> {
  const url = new URL(`${API_BASE}/market/ohlcv/${encodeURIComponent(symbol)}`);
  url.searchParams.set("exchange", exchange);
  url.searchParams.set("timeframe", timeframe);
  url.searchParams.set("limit", String(limit));
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`OHLCV fetch failed: ${res.status}`);
  return res.json() as Promise<OHLCVBar[]>;
}

export async function fetchSymbols(exchange?: string): Promise<SymbolInfo[]> {
  const url = new URL(`${API_BASE}/market/symbols`);
  if (exchange) url.searchParams.set("exchange", exchange);
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`Symbols fetch failed: ${res.status}`);
  return res.json() as Promise<SymbolInfo[]>;
}

export function createWebSocket(
  onMessage: (data: unknown) => void,
  onOpen?: () => void,
  onClose?: () => void
): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/ws`);
  ws.onopen = () => {
    onOpen?.();
    // Keep-alive ping every 30s
    const interval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      } else {
        clearInterval(interval);
      }
    }, 30_000);
  };
  ws.onmessage = (event) => {
    try {
      const data: unknown = JSON.parse(event.data as string);
      onMessage(data);
    } catch {
      // ignore malformed messages
    }
  };
  ws.onclose = () => onClose?.();
  return ws;
}
