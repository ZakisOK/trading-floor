"use client";
import { useEffect, useState, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── types ──────────────────────────────────────────────────────────────────

type ExecutionVenue = "sim" | "alpaca_paper" | "live";

interface SystemConfig {
  paper_trading: string;
  execution_venue: ExecutionVenue;
  max_daily_loss_pct: number;
  max_position_size_pct: number;
  trailing_stop_pct: number;
  kill_switch_enabled: string;
}

const VENUE_META: Record<ExecutionVenue, { label: string; icon: string; blurb: string; tone: string }> = {
  sim: {
    label: "Simulation",
    icon: "🧪",
    blurb: "Local fills with slippage + commission. Nothing leaves the box.",
    tone: "var(--text-tertiary)",
  },
  alpaca_paper: {
    label: "Alpaca Paper",
    icon: "📄",
    blurb: "Real orders to Alpaca's paper endpoint. Equities + crypto. No real money.",
    tone: "var(--accent-info)",
  },
  live: {
    label: "LIVE",
    icon: "⚡",
    blurb: "Real orders on live Alpaca account. Real money at risk.",
    tone: "#ef4444",
  },
};

interface ExchangeConfig {
  api_key: string;
  secret: string;
  passphrase: string;
  sandbox: string;
  enabled: string;
}

interface AgentConfig {
  enabled: string;
  confidence_threshold: number;
}

interface SettingsData {
  system: SystemConfig;
  exchanges: Record<string, ExchangeConfig>;
  agents: Record<string, AgentConfig>;
  assets: { enabled: string[]; all: string[] };
  notifications: { webhook_url: string };
}

type ConnectionStatus = "idle" | "testing" | "ok" | "fail";

const AGENT_LABELS: Record<string, string> = {
  atlas: "Atlas", bear: "Bear", bull: "Bull", carry_agent: "Carry Agent",
  commodities_analyst: "Commodities Analyst", copy_trade_scout: "Copy Trade Scout",
  cot_analyst: "COT Analyst", diana: "Diana", eia_analyst: "EIA Analyst",
  macro_analyst: "Macro Analyst", marcus: "Marcus", momentum_agent: "Momentum Agent",
  nova: "Nova", options_flow_agent: "Options Flow Agent", polymarket_scout: "Polymarket Scout",
  rex: "Rex", sage: "Sage", scout: "Scout", sentiment_analyst: "Sentiment Analyst",
  vera: "Vera", xrp_analyst: "XRP Analyst",
};

const ASSET_GROUPS = [
  { label: "Crypto Tier 1", symbols: ["BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT"] },
  { label: "Crypto Alts", symbols: ["BNB/USDT", "ADA/USDT", "AVAX/USDT", "DOGE/USDT", "LINK/USDT", "DOT/USDT", "MATIC/USDT", "UNI/USDT"] },
  { label: "Commodity Futures", symbols: ["GC=F", "CL=F", "SI=F", "HG=F", "NG=F", "ZW=F", "ZC=F", "ZS=F"] },
];

// ── styles ─────────────────────────────────────────────────────────────────

const S = {
  page: { padding: "28px 32px", maxWidth: 960, margin: "0 auto" } as React.CSSProperties,
  heading: { fontSize: 22, fontWeight: 800, color: "var(--text-primary)", marginBottom: 6 } as React.CSSProperties,
  subheading: { fontSize: 13, color: "var(--text-tertiary)", marginBottom: 32 } as React.CSSProperties,
  section: { marginBottom: 36 } as React.CSSProperties,
  sectionTitle: { fontSize: 13, fontWeight: 700, color: "var(--text-secondary)", textTransform: "uppercase" as const, letterSpacing: "0.1em", marginBottom: 16, paddingBottom: 8, borderBottom: "1px solid var(--border-subtle)" },
  card: { background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: "20px 22px", marginBottom: 14 } as React.CSSProperties,
  label: { fontSize: 12, color: "var(--text-tertiary)", marginBottom: 6, display: "block" } as React.CSSProperties,
  input: { width: "100%", background: "#1a1f2e", border: "1px solid var(--border-subtle)", borderRadius: 6, padding: "8px 12px", color: "var(--text-primary)", fontSize: 13, outline: "none", boxSizing: "border-box" as const },
  btn: { padding: "8px 18px", borderRadius: 6, border: "none", cursor: "pointer", fontSize: 13, fontWeight: 600 } as React.CSSProperties,
  btnPrimary: { background: "var(--accent-info)", color: "#fff" } as React.CSSProperties,
  btnDanger: { background: "#ef4444", color: "#fff" } as React.CSSProperties,
  btnGhost: { background: "rgba(255,255,255,0.06)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" } as React.CSSProperties,
  row: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 } as React.CSSProperties,
  grid2: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 } as React.CSSProperties,
  sliderLabel: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 } as React.CSSProperties,
};

// ── Toggle component ───────────────────────────────────────────────────────

function Toggle({ on, onChange, danger }: { on: boolean; onChange: (v: boolean) => void; danger?: boolean }) {
  return (
    <button
      onClick={() => onChange(!on)}
      style={{
        width: 44, height: 24, borderRadius: 12, border: "none", cursor: "pointer",
        background: on ? (danger ? "#ef4444" : "var(--accent-info)") : "rgba(255,255,255,0.12)",
        position: "relative", transition: "background 0.2s", flexShrink: 0,
      }}
    >
      <span style={{
        position: "absolute", top: 3, left: on ? 22 : 3, width: 18, height: 18,
        borderRadius: "50%", background: "#fff", transition: "left 0.2s",
      }} />
    </button>
  );
}

// ── Slider component ───────────────────────────────────────────────────────

function Slider({ label, value, min, max, step = 0.5, unit = "%", onChange }: {
  label: string; value: number; min: number; max: number; step?: number; unit?: string; onChange: (v: number) => void;
}) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={S.sliderLabel}>
        <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{label}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{value}{unit}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: "100%", accentColor: "var(--accent-info)" }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-tertiary)", marginTop: 2 }}>
        <span>{min}{unit}</span><span>{max}{unit}</span>
      </div>
    </div>
  );
}

// ── Live-mode warning modal ────────────────────────────────────────────────

function LiveWarningModal({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  const [phrase, setPhrase] = useState("");
  const required = "I understand this uses real money";
  const match = phrase === required;

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: "#111827", border: "1px solid #ef4444", borderRadius: 12, padding: 32, maxWidth: 480, width: "90%" }}>
        <div style={{ fontSize: 20, fontWeight: 800, color: "#ef4444", marginBottom: 8 }}>⚠ Switch to LIVE Trading</div>
        <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7, marginBottom: 20 }}>
          You are about to enable <strong style={{ color: "#ef4444" }}>real-money trading</strong>. Orders will be submitted
          directly to your connected exchange using real funds. Ensure your risk controls,
          position limits, and kill switch are properly configured before proceeding.
        </p>
        <p style={{ fontSize: 12, color: "var(--text-tertiary)", marginBottom: 10 }}>
          Type exactly to confirm: <strong style={{ color: "var(--text-primary)" }}>{required}</strong>
        </p>
        <input
          value={phrase} onChange={(e) => setPhrase(e.target.value)}
          placeholder="Type confirmation phrase..."
          style={{ ...S.input, marginBottom: 20, borderColor: match ? "#22c55e" : "var(--border-subtle)" }}
        />
        <div style={{ display: "flex", gap: 12 }}>
          <button onClick={onCancel} style={{ ...S.btn, ...S.btnGhost, flex: 1 }}>Cancel</button>
          <button onClick={onConfirm} disabled={!match} style={{ ...S.btn, ...S.btnDanger, flex: 1, opacity: match ? 1 : 0.4, cursor: match ? "pointer" : "not-allowed" }}>
            Enable Live Trading
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [showLiveModal, setShowLiveModal] = useState(false);
  const [connStatus, setConnStatus] = useState<Record<string, ConnectionStatus>>({});
  const [connLatency, setConnLatency] = useState<Record<string, number>>({});
  const [webhookTesting, setWebhookTesting] = useState(false);
  const [webhookResult, setWebhookResult] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/settings`);
      if (res.ok) setData(await res.json() as SettingsData);
    } catch { /* redis may be offline in dev */ }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    if (!data) return;
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/settings`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          system: data.system,
          exchanges: data.exchanges,
          agents: data.agents,
          assets: { enabled: data.assets.enabled },
          notifications: data.notifications,
        }),
      });
      setSaveMsg(res.ok ? "✓ Saved" : "✗ Save failed");
    } catch { setSaveMsg("✗ Network error"); }
    setSaving(false);
    setTimeout(() => setSaveMsg(""), 3000);
  };

  const updateSystem = (key: keyof SystemConfig, val: string | number) => {
    setData((d) => d ? { ...d, system: { ...d.system, [key]: val } } : d);
  };

  const updateExchange = (exId: string, key: keyof ExchangeConfig, val: string) => {
    setData((d) => d ? { ...d, exchanges: { ...d.exchanges, [exId]: { ...d.exchanges[exId], [key]: val } } } : d);
  };

  const updateAgent = (name: string, key: keyof AgentConfig, val: string | number) => {
    setData((d) => d ? { ...d, agents: { ...d.agents, [name]: { ...d.agents[name], [key]: val } } } : d);
  };

  const toggleAsset = (sym: string) => {
    setData((d) => {
      if (!d) return d;
      const enabled = d.assets.enabled.includes(sym)
        ? d.assets.enabled.filter((s) => s !== sym)
        : [...d.assets.enabled, sym];
      return { ...d, assets: { ...d.assets, enabled } };
    });
  };

  const venue: ExecutionVenue = (data?.system.execution_venue as ExecutionVenue | undefined)
    ?? (data?.system.paper_trading === "false" ? "alpaca_paper" : "sim");

  // Persist venue immediately so it takes effect without a full "Save".
  const persistVenue = async (next: ExecutionVenue) => {
    updateSystem("execution_venue", next);
    updateSystem("paper_trading", next === "sim" ? "true" : "false");
    try {
      await fetch(`${API}/api/settings`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          system: {
            execution_venue: next,
            paper_trading: next === "sim" ? "true" : "false",
          },
        }),
      });
    } catch { /* shown via save banner on next save */ }
  };

  const handleVenueChange = (next: ExecutionVenue) => {
    if (next === "live") {
      setShowLiveModal(true);
      return;
    }
    void persistVenue(next);
  };

  const confirmLive = () => {
    setShowLiveModal(false);
    void persistVenue("live");
  };

  const testExchange = async (exId: string) => {
    setConnStatus((s) => ({ ...s, [exId]: "testing" }));
    try {
      const res = await fetch(`${API}/api/settings/exchange/test`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ exchange_id: exId }),
      });
      const json = await res.json() as { connected: boolean; latency_ms: number };
      setConnStatus((s) => ({ ...s, [exId]: json.connected ? "ok" : "fail" }));
      setConnLatency((l) => ({ ...l, [exId]: json.latency_ms }));
    } catch {
      setConnStatus((s) => ({ ...s, [exId]: "fail" }));
    }
  };

  const testWebhook = async () => {
    if (!data?.notifications.webhook_url) return;
    setWebhookTesting(true);
    setWebhookResult("");
    try {
      const res = await fetch(data.notifications.webhook_url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "The Trading Floor — webhook test ✓" }),
      });
      setWebhookResult(res.ok ? "✓ Delivered" : `✗ HTTP ${res.status}`);
    } catch { setWebhookResult("✗ Failed"); }
    setWebhookTesting(false);
  };

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "60vh" }}>
        <div style={{ fontSize: 14, color: "var(--text-tertiary)" }}>Loading settings…</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ padding: 32 }}>
        <div style={{ color: "#ef4444", fontSize: 14 }}>Could not load settings. Is the API running?</div>
      </div>
    );
  }


  return (
    <div style={S.page}>
      {showLiveModal && <LiveWarningModal onConfirm={confirmLive} onCancel={() => setShowLiveModal(false)} />}

      {/* Header */}
      <div style={S.heading}>Settings</div>
      <div style={S.subheading}>Configure trading mode, risk controls, exchange credentials, and agents.</div>

      {/* ── 1. Execution Venue ───────────────────────────────────────────── */}
      <div style={S.section}>
        <div style={S.sectionTitle}>Execution Venue</div>
        <div style={{ ...S.card, border: venue === "live" ? "1px solid #ef4444" : "1px solid var(--border-subtle)" }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
            {(Object.keys(VENUE_META) as ExecutionVenue[]).map((v) => {
              const meta = VENUE_META[v];
              const active = venue === v;
              return (
                <button key={v} onClick={() => handleVenueChange(v)} style={{
                  flex: 1, padding: "14px 12px", borderRadius: 8, cursor: "pointer",
                  background: active ? (v === "live" ? "rgba(239,68,68,0.15)" : "rgba(99,102,241,0.15)") : "transparent",
                  border: `1px solid ${active ? meta.tone : "var(--border-subtle)"}`,
                  color: active ? meta.tone : "var(--text-tertiary)",
                  fontSize: 14, fontWeight: 700, textAlign: "left" as const,
                  transition: "all 0.15s",
                }}>
                  <div style={{ fontSize: 16, marginBottom: 4 }}>{meta.icon} {meta.label}</div>
                  <div style={{ fontSize: 11, fontWeight: 500, color: active ? meta.tone : "var(--text-tertiary)", opacity: 0.85 }}>
                    {meta.blurb}
                  </div>
                </button>
              );
            })}
          </div>
          {venue === "alpaca_paper" && (
            <div style={{ padding: "10px 14px", background: "rgba(99,102,241,0.08)", border: "1px solid rgba(99,102,241,0.3)", borderRadius: 8, fontSize: 12, color: "var(--accent-info)" }}>
              📄 Paper orders route to https://paper-api.alpaca.markets — visible in your Alpaca paper dashboard.
            </div>
          )}
          {venue === "live" && (
            <div style={{ padding: "10px 14px", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 8, fontSize: 12, color: "#fca5a5" }}>
              ⚠ LIVE MODE ACTIVE — real orders are being placed. Use the Kill Switch below to halt all trading.
            </div>
          )}
        </div>
      </div>

      {/* ── 2. Risk Controls ─────────────────────────────────────────────── */}
      <div style={S.section}>
        <div style={S.sectionTitle}>Risk Controls</div>
        <div style={S.card}>
          <Slider label="Max Daily Loss" value={data.system.max_daily_loss_pct} min={0.5} max={10} step={0.5}
            onChange={(v) => updateSystem("max_daily_loss_pct", v)} />
          <Slider label="Max Position Size" value={data.system.max_position_size_pct} min={1} max={20} step={1}
            onChange={(v) => updateSystem("max_position_size_pct", v)} />
          <Slider label="Trailing Stop" value={data.system.trailing_stop_pct} min={1} max={15} step={0.5}
            onChange={(v) => updateSystem("trailing_stop_pct", v)} />
          <div style={{ ...S.row, paddingTop: 8, borderTop: "1px solid var(--border-subtle)" }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#ef4444" }}>Kill Switch</div>
              <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 2 }}>Halt all order flow immediately</div>
            </div>
            <Toggle
              on={data.system.kill_switch_enabled === "true"}
              onChange={(v) => updateSystem("kill_switch_enabled", v ? "true" : "false")}
              danger
            />
          </div>
        </div>
      </div>

      {/* ── 3. Exchange Connections ───────────────────────────────────────── */}
      <div style={S.section}>
        <div style={S.sectionTitle}>Exchange Connections</div>
        {(["binance", "coinbase", "kraken", "polymarket"] as const).map((exId) => {
          const ex = data.exchanges[exId] ?? { api_key: "", secret: "", passphrase: "", sandbox: "true", enabled: "false" };
          const st = connStatus[exId] ?? "idle";
          const lat = connLatency[exId];
          return (
            <div key={exId} style={S.card}>
              <div style={{ ...S.row, marginBottom: 16 }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)", textTransform: "capitalize" }}>{exId}</div>
                  <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2 }}>
                    {exId === "polymarket" ? "Prediction markets" : "Spot & derivatives"}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  {st === "ok" && <span style={{ fontSize: 12, color: "#22c55e" }}>✓ {lat}ms</span>}
                  {st === "fail" && <span style={{ fontSize: 12, color: "#ef4444" }}>✗ Failed</span>}
                  {st === "testing" && <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>Testing…</span>}
                  <button onClick={() => void testExchange(exId)} style={{ ...S.btn, ...S.btnGhost, padding: "5px 12px", fontSize: 12 }}>
                    Test Connection
                  </button>
                  <Toggle on={ex.enabled === "true"} onChange={(v) => updateExchange(exId, "enabled", v ? "true" : "false")} />
                </div>
              </div>
              <div style={S.grid2}>
                <div>
                  <label style={S.label}>API Key</label>
                  <input style={S.input} type="password" value={ex.api_key}
                    onChange={(e) => updateExchange(exId, "api_key", e.target.value)}
                    placeholder="Paste API key…" />
                </div>
                <div>
                  <label style={S.label}>Secret</label>
                  <input style={S.input} type="password" value={ex.secret}
                    onChange={(e) => updateExchange(exId, "secret", e.target.value)}
                    placeholder="Paste secret…" />
                </div>
                {exId === "coinbase" && (
                  <div>
                    <label style={S.label}>Passphrase</label>
                    <input style={S.input} type="password" value={ex.passphrase}
                      onChange={(e) => updateExchange(exId, "passphrase", e.target.value)}
                      placeholder="Passphrase…" />
                  </div>
                )}
                <div style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 20 }}>
                  <Toggle on={ex.sandbox === "true"} onChange={(v) => updateExchange(exId, "sandbox", v ? "true" : "false")} />
                  <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Sandbox / Testnet</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── 4. Agent Controls ────────────────────────────────────────────── */}
      <div style={S.section}>
        <div style={S.sectionTitle}>Agent Controls</div>
        <div style={S.card}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 80px 200px", gap: "0 16px", marginBottom: 10 }}>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em" }}>Agent</div>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em" }}>Enabled</div>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em" }}>Confidence Threshold</div>
          </div>
          {Object.keys(AGENT_LABELS).map((name) => {
            const cfg = data.agents[name] ?? { enabled: "true", confidence_threshold: 0.65 };
            const threshold = Number(cfg.confidence_threshold ?? 0.65);
            return (
              <div key={name} style={{ display: "grid", gridTemplateColumns: "1fr 80px 200px", gap: "0 16px", alignItems: "center", padding: "10px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                <div style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 500 }}>{AGENT_LABELS[name]}</div>
                <div>
                  <Toggle on={cfg.enabled !== "false"} onChange={(v) => updateAgent(name, "enabled", v ? "true" : "false")} />
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <input
                    type="range" min={0.5} max={0.95} step={0.05} value={threshold}
                    onChange={(e) => updateAgent(name, "confidence_threshold", Number(e.target.value))}
                    style={{ flex: 1, accentColor: "var(--accent-info)" }}
                    disabled={cfg.enabled === "false"}
                  />
                  <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", minWidth: 36, textAlign: "right" }}>
                    {threshold.toFixed(2)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── 5. Asset Universe ────────────────────────────────────────────── */}
      <div style={S.section}>
        <div style={S.sectionTitle}>Asset Universe</div>
        <div style={S.card}>
          {ASSET_GROUPS.map((group) => (
            <div key={group.label} style={{ marginBottom: 22 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-secondary)", marginBottom: 10 }}>{group.label}</div>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 8 }}>
                {group.symbols.map((sym) => {
                  const active = data.assets.enabled.includes(sym);
                  return (
                    <button key={sym} onClick={() => toggleAsset(sym)} style={{
                      padding: "5px 12px", borderRadius: 6, border: "1px solid",
                      fontSize: 12, fontWeight: 600, cursor: "pointer",
                      background: active ? "rgba(99,102,241,0.15)" : "transparent",
                      borderColor: active ? "var(--accent-info)" : "var(--border-subtle)",
                      color: active ? "var(--accent-info)" : "var(--text-tertiary)",
                      transition: "all 0.15s",
                    }}>
                      {sym}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── 6. Notifications ─────────────────────────────────────────────── */}
      <div style={S.section}>
        <div style={S.sectionTitle}>Notifications</div>
        <div style={S.card}>
          <label style={S.label}>Webhook URL (Discord or Slack incoming webhook)</label>
          <div style={{ display: "flex", gap: 10 }}>
            <input
              style={{ ...S.input, flex: 1 }}
              type="url"
              value={data.notifications.webhook_url}
              onChange={(e) => setData((d) => d ? { ...d, notifications: { webhook_url: e.target.value } } : d)}
              placeholder="https://discord.com/api/webhooks/… or https://hooks.slack.com/…"
            />
            <button onClick={() => void testWebhook()} disabled={webhookTesting || !data.notifications.webhook_url}
              style={{ ...S.btn, ...S.btnGhost, whiteSpace: "nowrap" as const }}>
              {webhookTesting ? "Sending…" : "Test"}
            </button>
          </div>
          {webhookResult && (
            <div style={{ marginTop: 8, fontSize: 12, color: webhookResult.startsWith("✓") ? "#22c55e" : "#ef4444" }}>
              {webhookResult}
            </div>
          )}
        </div>
      </div>

      {/* ── Save bar ─────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 16, padding: "20px 0", borderTop: "1px solid var(--border-subtle)" }}>
        {saveMsg && <span style={{ fontSize: 13, color: saveMsg.startsWith("✓") ? "#22c55e" : "#ef4444" }}>{saveMsg}</span>}
        <button onClick={() => void load()} style={{ ...S.btn, ...S.btnGhost }}>Discard Changes</button>
        <button onClick={() => void save()} disabled={saving} style={{ ...S.btn, ...S.btnPrimary }}>
          {saving ? "Saving…" : "Save Settings"}
        </button>
      </div>
    </div>
  );
}
