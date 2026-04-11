"use client";
import { useState, useEffect, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── Types ────────────────────────────────────────────────────────────────────
interface CopySignal {
  symbol: string;
  direction: string;
  confidence: number;
  thesis: string;
  sources: string[];
  binance_positions?: number;
  whale_moves?: number;
  cot_signal?: string;
  score_breakdown?: Record<string, number>;
  ts?: string;
}

interface WhaleMove {
  wallet: string;
  amount_xrp: number;
  direction: string;
  interpretation: string;
  to_exchange: boolean;
  from_exchange: boolean;
  exchange: string;
}

interface BinanceTrader {
  trader_uid: string;
  roi_30d: number;
  direction: string;
  symbol: string;
  leverage: number;
  unrealized_pnl: number;
}

interface CotReading {
  symbol: string;
  name: string;
  signal: string;
  strength: number;
  commercial_net: number;
  commercial_net_pct: number;
  speculator_net_pct: number;
  reasoning: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function fmt(n: number | undefined | null, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function directionColor(d: string) {
  if (d === "LONG" || d === "BULLISH") return "var(--accent-profit)";
  if (d === "SHORT" || d === "BEARISH") return "var(--accent-loss)";
  return "var(--text-tertiary)";
}

function directionBadge(d: string) {
  const color = directionColor(d);
  return (
    <span style={{
      display: "inline-block", padding: "2px 8px", borderRadius: 4,
      fontSize: 11, fontWeight: 700, color,
      background: `${color}22`,
      border: `1px solid ${color}44`,
    }}>
      {d}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.75 ? "var(--accent-profit)" : value >= 0.55 ? "#f59e0b" : "var(--accent-loss)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: "var(--border-subtle)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.4s" }} />
      </div>
      <span style={{ fontSize: 12, color, fontWeight: 700, minWidth: 36, textAlign: "right" }}>{pct}%</span>
    </div>
  );
}

function CotGauge({ value, label }: { value: number; label: string }) {
  // value: -50 to +50 (commercial net % OI)
  const clamped = Math.max(-50, Math.min(50, value));
  const pct = (clamped + 50) / 100 * 100; // 0-100%
  const color = clamped > 0 ? "var(--accent-profit)" : clamped < -10 ? "var(--accent-loss)" : "#f59e0b";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{label}</div>
      <div style={{ position: "relative", height: 8, background: "var(--border-subtle)", borderRadius: 4, overflow: "hidden" }}>
        {/* Center line */}
        <div style={{
          position: "absolute", left: "50%", top: 0, width: 1, height: "100%",
          background: "rgba(255,255,255,0.15)",
        }} />
        <div style={{
          position: "absolute",
          left: clamped >= 0 ? "50%" : `${pct}%`,
          width: `${Math.abs(clamped) / 100 * 100 / 2}%`,
          height: "100%", background: color, borderRadius: 2,
        }} />
      </div>
      <div style={{ fontSize: 11, color, fontWeight: 600 }}>
        {clamped >= 0 ? "+" : ""}{fmt(clamped, 1)}% OI
      </div>
    </div>
  );
}

// ─── Section header ───────────────────────────────────────────────────────────
function SectionHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700 }}>
        {title}
      </div>
      {sub && <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

// ─── Mocked data (replace with real API endpoints when ready) ─────────────────
const MOCK_COT: CotReading[] = [
  {
    symbol: "GC=F", name: "Gold", signal: "BULLISH", strength: 0.71,
    commercial_net: 12400, commercial_net_pct: 4.2, speculator_net_pct: 18.5,
    reasoning: "Commercials net LONG — rare signal. Speculators crowded long reduces conviction.",
  },
  {
    symbol: "CL=F", name: "WTI Crude", signal: "BEARISH", strength: 0.52,
    commercial_net: -145000, commercial_net_pct: -18.3, speculator_net_pct: 22.1,
    reasoning: "Commercials heavily short. Speculators crowded long — fade risk on any supply surprise.",
  },
  {
    symbol: "NG=F", name: "Natural Gas", signal: "BULLISH", strength: 0.63,
    commercial_net: -28000, commercial_net_pct: -8.1, speculator_net_pct: -24.6,
    reasoning: "Speculators historically crowded short. Short squeeze potential with any weather surprise.",
  },
  {
    symbol: "ZC=F", name: "Corn", signal: "NEUTRAL", strength: 0.31,
    commercial_net: -52000, commercial_net_pct: -12.4, speculator_net_pct: -5.2,
    reasoning: "Commercial positioning in normal range. No extreme readings.",
  },
];

const MOCK_WHALE_MOVES: WhaleMove[] = [
  {
    wallet: "rPT1Sjq2YG...", amount_xrp: 2_450_000, direction: "BULLISH",
    interpretation: "2,450,000 XRP withdrawn FROM Binance — accumulation signal",
    to_exchange: false, from_exchange: true, exchange: "Binance",
  },
  {
    wallet: "rN7n3473Sa...", amount_xrp: 850_000, direction: "BEARISH",
    interpretation: "850,000 XRP flowing TO Bitstamp — potential sell pressure",
    to_exchange: true, from_exchange: false, exchange: "Bitstamp",
  },
  {
    wallet: "r3kmLJN5D2...", amount_xrp: 1_200_000, direction: "NEUTRAL",
    interpretation: "1,200,000 XRP whale-to-whale transfer",
    to_exchange: false, from_exchange: false, exchange: "unknown",
  },
];

const MOCK_BINANCE: BinanceTrader[] = [
  { trader_uid: "a3f8b2...", roi_30d: 142.3, direction: "LONG", symbol: "XRPUSDT", leverage: 5, unrealized_pnl: 4820 },
  { trader_uid: "c9d1e4...", roi_30d: 98.7, direction: "LONG", symbol: "XRPUSDT", leverage: 3, unrealized_pnl: 2100 },
  { trader_uid: "f2a7c1...", roi_30d: 87.2, direction: "SHORT", symbol: "XRPUSDT", leverage: 2, unrealized_pnl: -340 },
  { trader_uid: "b5e3d9...", roi_30d: 76.4, direction: "LONG", symbol: "XRPUSDT", leverage: 10, unrealized_pnl: 8900 },
  { trader_uid: "e8g2h4...", roi_30d: 65.1, direction: "LONG", symbol: "XRPUSDT", leverage: 5, unrealized_pnl: 1250 },
];

// ─── Main page ────────────────────────────────────────────────────────────────
export default function CopyTradePage() {
  const [copySignals, setCopySignals] = useState<CopySignal[]>([]);
  const [whaleMoves] = useState<WhaleMove[]>(MOCK_WHALE_MOVES);
  const [binanceTraders] = useState<BinanceTrader[]>(MOCK_BINANCE);
  const [cotReadings] = useState<CotReading[]>(MOCK_COT);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchSignals = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/signals/recent?limit=20&type=copy_trade`);
      const data = await res.json();
      const signals = Array.isArray(data) ? data : data?.signals ?? [];
      const copyOnly = signals.filter((s: CopySignal & { signal_type?: string }) =>
        s.signal_type === "copy_trade"
      );
      setCopySignals(copyOnly.length > 0 ? copyOnly : []);
      setLastUpdate(new Date());
    } catch {
      // API unavailable — show mock state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSignals();
    const interval = setInterval(fetchSignals, 15000); // 15s refresh
    return () => clearInterval(interval);
  }, [fetchSignals]);

  // Leaderboard summary
  const longCount = binanceTraders.filter(t => t.direction === "LONG").length;
  const shortCount = binanceTraders.filter(t => t.direction === "SHORT").length;
  const longPct = Math.round(longCount / binanceTraders.length * 100);

  // Whale flow summary
  const bullWhaleVol = whaleMoves
    .filter(m => m.direction === "BULLISH")
    .reduce((s, m) => s + m.amount_xrp, 0);
  const bearWhaleVol = whaleMoves
    .filter(m => m.direction === "BEARISH")
    .reduce((s, m) => s + m.amount_xrp, 0);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "28px 28px" }}>
      {/* Page header */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", marginBottom: 4 }}>
          Copy Trade Intelligence
        </div>
        <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          Binance leaderboard · XRPL whale tracking · COT smart money
          {lastUpdate && (
            <span style={{ marginLeft: 16, fontSize: 11, color: "var(--text-tertiary)" }}>
              Last updated {lastUpdate.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {/* Summary KPIs */}
      <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
        {[
          {
            label: "Binance Top Traders",
            value: `${longPct}% LONG`,
            color: longPct > 60 ? "var(--accent-profit)" : longPct < 40 ? "var(--accent-loss)" : "var(--text-primary)",
            sub: `${longCount} long / ${shortCount} short of top ${binanceTraders.length} traders`,
          },
          {
            label: "XRPL Whale Flow",
            value: bullWhaleVol > bearWhaleVol ? "Net Bullish" : "Net Bearish",
            color: bullWhaleVol > bearWhaleVol ? "var(--accent-profit)" : "var(--accent-loss)",
            sub: `${(bullWhaleVol / 1_000_000).toFixed(1)}M XRP withdrawn vs ${(bearWhaleVol / 1_000_000).toFixed(1)}M to exchanges`,
          },
          {
            label: "COT Smart Money",
            value: cotReadings.filter(c => c.signal === "BULLISH").length > cotReadings.filter(c => c.signal === "BEARISH").length
              ? "Net Bullish" : "Mixed",
            color: "var(--text-primary)",
            sub: `${cotReadings.filter(c => c.signal === "BULLISH").length} bullish / ${cotReadings.filter(c => c.signal === "BEARISH").length} bearish commodities`,
          },
          {
            label: "Active Copy Signals",
            value: String(copySignals.length),
            color: copySignals.length > 0 ? "var(--accent-info)" : "var(--text-secondary)",
            sub: "Signals meeting minimum confidence",
          },
        ].map(card => (
          <div key={card.label} className="glass-panel" style={{
            flex: 1, minWidth: 180, padding: "16px 18px",
          }}>
            <div style={{ fontSize: 10, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
              {card.label}
            </div>
            <div style={{ fontSize: 20, fontWeight: 700, color: card.color, marginBottom: 4, fontFamily: "var(--font-mono, monospace)" }}>
              {card.value}
            </div>
            <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>{card.sub}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>

        {/* Binance leaderboard */}
        <div className="glass-panel" style={{ padding: "20px" }}>
          <SectionHeader
            title="Binance Futures Leaderboard"
            sub="Top traders by 30-day ROI — their XRP positions"
          />
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              <div style={{
                flex: longPct, height: 6, background: "var(--accent-profit)", borderRadius: "3px 0 0 3px",
                transition: "flex 0.4s",
              }} />
              <div style={{
                flex: 100 - longPct, height: 6, background: "var(--accent-loss)", borderRadius: "0 3px 3px 0",
              }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
              <span style={{ color: "var(--accent-profit)" }}>{longPct}% LONG ({longCount})</span>
              <span style={{ color: "var(--accent-loss)" }}>{100 - longPct}% SHORT ({shortCount})</span>
            </div>
          </div>

          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {["Trader", "30d ROI", "Position", "Leverage", "Unreal. P&L"].map(h => (
                  <th key={h} style={{
                    textAlign: "left", padding: "6px 0", color: "var(--text-tertiary)",
                    fontWeight: 500, borderBottom: "1px solid var(--border-subtle)", fontSize: 11,
                  }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {binanceTraders.map((tr, i) => (
                <tr key={i} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <td style={{ padding: "8px 0", fontFamily: "var(--font-mono, monospace)", fontSize: 11, color: "var(--text-tertiary)" }}>
                    #{i + 1} {tr.trader_uid}
                  </td>
                  <td style={{ color: "var(--accent-profit)", fontWeight: 600 }}>
                    +{fmt(tr.roi_30d, 1)}%
                  </td>
                  <td>
                    <span style={{
                      color: directionColor(tr.direction), fontWeight: 700,
                      fontSize: 11,
                    }}>
                      {tr.direction}
                    </span>
                  </td>
                  <td style={{ color: "var(--text-secondary)" }}>{tr.leverage}x</td>
                  <td style={{
                    color: tr.unrealized_pnl >= 0 ? "var(--accent-profit)" : "var(--accent-loss)",
                    fontWeight: 600,
                  }}>
                    {tr.unrealized_pnl >= 0 ? "+" : ""}${fmt(tr.unrealized_pnl, 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 10, fontSize: 10, color: "var(--text-tertiary)" }}>
            Source: Binance Futures public leaderboard · Positions visible only if trader has enabled sharing
          </div>
        </div>

        {/* XRPL whale tracking */}
        <div className="glass-panel" style={{ padding: "20px" }}>
          <SectionHeader
            title="XRPL Whale Wallet Tracker"
            sub="Large XRP movements (>500k XRP) from monitored wallets"
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {whaleMoves.map((move, i) => (
              <div key={i} style={{
                padding: "12px 14px", borderRadius: 8,
                background: "rgba(255,255,255,0.03)",
                border: `1px solid ${
                  move.direction === "BULLISH" ? "rgba(34,197,94,0.2)" :
                  move.direction === "BEARISH" ? "rgba(239,68,68,0.2)" :
                  "var(--border-subtle)"
                }`,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
                  <div>
                    <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 11, color: "var(--text-tertiary)" }}>
                      {move.wallet}
                    </span>
                    {move.exchange !== "unknown" && (
                      <span style={{
                        marginLeft: 8, fontSize: 10, padding: "1px 6px", borderRadius: 3,
                        background: "rgba(255,255,255,0.08)", color: "var(--text-secondary)",
                      }}>
                        {move.to_exchange ? "→" : "←"} {move.exchange}
                      </span>
                    )}
                  </div>
                  {directionBadge(move.direction)}
                </div>
                <div style={{
                  fontSize: 16, fontWeight: 700, color: "var(--text-primary)",
                  fontFamily: "var(--font-mono, monospace)", marginBottom: 4,
                }}>
                  {(move.amount_xrp / 1_000_000).toFixed(2)}M XRP
                </div>
                <div style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  {move.interpretation}
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 10, fontSize: 10, color: "var(--text-tertiary)" }}>
            Monitoring {8} wallets via XRPL public RPC · Exchange inflow = sell pressure · Outflow = accumulation
          </div>
        </div>
      </div>

      {/* COT Smart Money — full width */}
      <div className="glass-panel" style={{ padding: "20px", marginBottom: 20 }}>
        <SectionHeader
          title="COT Smart Money — Commercial Hedger Positioning"
          sub='Commitment of Traders report (CFTC, weekly). Commercials are the "smart money" in commodities — they know the physical market.'
        />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          {cotReadings.map(cot => (
            <div key={cot.symbol} style={{
              padding: "14px 16px", borderRadius: 8,
              background: "rgba(255,255,255,0.03)",
              border: `1px solid ${
                cot.signal === "BULLISH" ? "rgba(34,197,94,0.2)" :
                cot.signal === "BEARISH" ? "rgba(239,68,68,0.2)" :
                "var(--border-subtle)"
              }`,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{cot.name}</div>
                  <div style={{ fontSize: 10, color: "var(--text-tertiary)", fontFamily: "var(--font-mono, monospace)" }}>{cot.symbol}</div>
                </div>
                {directionBadge(cot.signal)}
              </div>
              <CotGauge value={cot.commercial_net_pct} label="Commercial net % OI" />
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 4 }}>Conviction</div>
                <ConfidenceBar value={cot.strength} />
              </div>
              <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                {cot.reasoning}
              </div>
              <div style={{ marginTop: 8, fontSize: 10, color: "var(--text-tertiary)" }}>
                Spec net: {cot.speculator_net_pct >= 0 ? "+" : ""}{fmt(cot.speculator_net_pct, 1)}% OI
              </div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 12, fontSize: 10, color: "var(--text-tertiary)" }}>
          Source: CFTC disaggregated futures report (public, free) · Released Fridays 3:30 PM ET · Refreshed every 6 hours
        </div>
      </div>

      {/* Active copy signals from the pipeline */}
      <div className="glass-panel" style={{ padding: "20px" }}>
        <SectionHeader
          title="Pipeline Copy Signals"
          sub="Signals generated by CopyTradeScout that passed the minimum confidence threshold"
        />
        {loading ? (
          <div style={{ fontSize: 13, color: "var(--text-tertiary)" }}>Loading…</div>
        ) : copySignals.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--text-tertiary)", padding: "16px 0" }}>
            No copy signals currently active. The scout runs each 15-minute commodity cycle and 2-minute crypto cycle.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {copySignals.map((sig, i) => (
              <div key={i} style={{
                padding: "14px 16px", borderRadius: 8,
                background: "rgba(255,255,255,0.03)",
                border: "1px solid var(--border-subtle)",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 14, fontWeight: 700 }}>{sig.symbol}</span>
                    {directionBadge(sig.direction)}
                  </div>
                  <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                    {sig.ts ? new Date(sig.ts).toLocaleTimeString() : ""}
                  </span>
                </div>
                <ConfidenceBar value={sig.confidence} />
                <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  {sig.thesis}
                </div>
                {sig.sources && sig.sources.length > 0 && (
                  <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 3 }}>
                    {sig.sources.map((src, j) => (
                      <div key={j} style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                        · {src}
                      </div>
                    ))}
                  </div>
                )}
                {sig.score_breakdown && (
                  <div style={{ marginTop: 8, display: "flex", gap: 12 }}>
                    {Object.entries(sig.score_breakdown).map(([k, v]) => (
                      <div key={k} style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                        <span style={{ color: directionColor(k) }}>{k}</span> {(v * 100).toFixed(0)}%
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
