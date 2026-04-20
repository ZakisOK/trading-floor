"use client";
// ─────────────────────────────────────────────────────────────────────────────
// AppNav — ported from the Claude Design handoff
// (.claude/_handoff_design/project/Mission Control.html, lines 813–886).
// Inline SVG icons match the mock exactly. Uses the .nav / .brand / .nav-group
// / .nav-item / .nav-foot classes defined in globals.css.
// ─────────────────────────────────────────────────────────────────────────────
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";

interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
  meta?: string;
  badge?: string;
  dot?: boolean;
}
interface NavGroup { group: string; items: NavItem[]; }

// SVG paths transcribed from the mock. Inline so we don't need an icon lib.
const ICON = {
  home: <svg viewBox="0 0 20 20"><path d="M3 11 10 4l7 7M5 9v8h10V9"/></svg>,
  grid: <svg viewBox="0 0 20 20"><rect x="3" y="4" width="14" height="12" rx="2"/><path d="M3 9h14M8 4v12"/></svg>,
  chartUp: <svg viewBox="0 0 20 20"><path d="M3 14l4-6 4 4 6-8"/><circle cx="17" cy="4" r="1.5"/></svg>,
  coin: <svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="M10 3v14M3 10h14"/></svg>,
  building: <svg viewBox="0 0 20 20"><path d="M4 16V8l6-4 6 4v8M8 16v-5h4v5"/></svg>,
  beaker: <svg viewBox="0 0 20 20"><path d="M4 4h12v12H4z"/><path d="M4 10h12M10 4v12"/></svg>,
  ekg: <svg viewBox="0 0 20 20"><path d="M3 10h4l2-6 2 12 2-8 2 2h2"/></svg>,
  target: <svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><circle cx="10" cy="10" r="2.5"/></svg>,
  shield: <svg viewBox="0 0 20 20"><path d="M10 3l7 4v6l-7 4-7-4V7z"/><path d="M3 7l7 4 7-4M10 11v10"/></svg>,
  bolt: <svg viewBox="0 0 20 20"><path d="M4 17V3M4 6h10l-2 3 2 3H4"/></svg>,
  cycle: <svg viewBox="0 0 20 20"><path d="M4 9a6 6 0 0 1 11-3M16 11a6 6 0 0 1-11 3M4 3v6h6M16 17v-6h-6"/></svg>,
  phone: <svg viewBox="0 0 20 20"><rect x="6" y="2" width="8" height="16" rx="2"/><path d="M8 15h4"/></svg>,
  gear: <svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="3"/><path d="M10 2v2m0 12v2m8-8h-2M4 10H2m13.5-5.5l-1.5 1.5M6 14l-1.5 1.5m11-0l-1.5-1.5M6 6L4.5 4.5"/></svg>,
};

const NAV_GROUPS: NavGroup[] = [
  {
    group: "Firm",
    items: [
      { href: "/",          label: "Mission Control", icon: ICON.home },
      { href: "/positions", label: "Positions",       icon: ICON.grid },
      { href: "/signals",   label: "Signals",         icon: ICON.chartUp },
    ],
  },
  {
    group: "Markets",
    items: [
      { href: "/market",             label: "Crypto",        icon: ICON.coin, dot: true },
      { href: "/commodities",        label: "Commodities",   icon: ICON.building, badge: "new" },
      { href: "/backtest/ensemble",  label: "Ensemble Test", icon: ICON.beaker, badge: "new" },
      { href: "/backtest",           label: "Indicator Lab", icon: ICON.ekg },
    ],
  },
  {
    group: "Intelligence",
    items: [
      { href: "/floor",     label: "Trading Floor", icon: ICON.target },
      { href: "/risk",      label: "Risk",          icon: ICON.shield },
      { href: "/execution", label: "Execution",     icon: ICON.bolt },
      { href: "/agents",    label: "Agents",        icon: ICON.cycle },
    ],
  },
  {
    group: "System",
    items: [
      { href: "/mobile",   label: "Mobile",   icon: ICON.phone },
      { href: "/settings", label: "Settings", icon: ICON.gear },
    ],
  },
];

export function AppNav() {
  const pathname = usePathname();

  return (
    <aside className="nav">
      {/* Brand */}
      <div className="brand">
        <div className="mark">
          <div className="logo" />
          <div>
            <h1>The Trading Floor</h1>
            <div className="sub">AI Desk · v2.4</div>
          </div>
        </div>
      </div>

      {/* Nav groups */}
      {NAV_GROUPS.map((group) => (
        <div key={group.group} className="nav-group">
          <h6>{group.group}</h6>
          {group.items.map(({ href, label, icon, meta, badge, dot }) => {
            const isActive = pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <Link
                key={href}
                href={href as never}
                className={`nav-item${isActive ? " active" : ""}`}
              >
                {icon}
                {label}
                {meta && <span className="meta">{meta}</span>}
                {badge && <span className="badge">{badge}</span>}
                {dot && <span className="dot" />}
              </Link>
            );
          })}
        </div>
      ))}

      {/* Foot */}
      <div className="nav-foot">
        <div className="sys"><span className="pulse" /> System online</div>
        <div className="row"><span>Latency</span><span style={{ color: "var(--text-secondary)" }}>42ms</span></div>
        <div className="row"><span>Copy trade</span><span style={{ color: "var(--accent-profit)" }}>Active</span></div>
        <div className="row"><span>Build</span><span style={{ color: "var(--text-secondary)" }}>v2.4</span></div>
      </div>
    </aside>
  );
}
