"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/",          label: "Mission Control", icon: "🎯" },
  { href: "/firm",      label: "The Firm",        icon: "🏛" },   // three-desk overview
  { href: "/market",    label: "Market Data",     icon: "📈" },
  { href: "/backtest",  label: "Backtesting",     icon: "📊" },
  { href: "/agents",    label: "Agents",          icon: "🤖" },
  { href: "/floor",     label: "Trading Floor",   icon: "🏢" },
  { href: "/risk",      label: "Risk",            icon: "🛡" },
  { href: "/execution", label: "Execution",       icon: "⚡" },
  { href: "/polymarket", label: "Polymarket",     icon: "🎲" },
];

export function AppNav() {
  const pathname = usePathname();
  return (
    <nav style={{
      width: 220, minHeight: "100vh", background: "var(--bg-base)",
      borderRight: "1px solid var(--border-subtle)", display: "flex",
      flexDirection: "column", padding: "24px 0", flexShrink: 0,
      position: "sticky", top: 0, height: "100vh", overflowY: "auto",
    }}>
      {/* Logo */}
      <div style={{ padding: "0 20px 24px", borderBottom: "1px solid var(--border-subtle)", marginBottom: 12 }}>
        <div style={{ fontSize: 16, fontWeight: 800, color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
          The Trading Floor
        </div>
        <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2 }}>Paper Trading System</div>
      </div>

      {/* Nav items */}
      {NAV.map(({ href, label, icon }) => {
        const active = pathname === href;
        const isFirm = href === "/firm";
        return (
          <Link key={href} href={href} style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "9px 20px", textDecoration: "none", transition: "all 0.15s",
            background: active
              ? "rgba(94,106,210,0.12)"
              : isFirm
                ? "rgba(245,158,11,0.04)"
                : "transparent",
            borderLeft: active
              ? "2px solid var(--accent-primary)"
              : isFirm
                ? "2px solid rgba(245,158,11,0.3)"
                : "2px solid transparent",
            color: active ? "var(--text-primary)" : "var(--text-secondary)",
            fontSize: 14, fontWeight: active ? 600 : isFirm ? 500 : 400,
          }}>
            <span style={{ fontSize: 15, lineHeight: 1 }}>{icon}</span>
            {label}
            {isFirm && !active && (
              <span style={{
                marginLeft: "auto", fontSize: 9, fontWeight: 700,
                padding: "1px 4px", borderRadius: 3,
                background: "rgba(245,158,11,0.15)", color: "#f59e0b",
                letterSpacing: "0.05em", textTransform: "uppercase",
              }}>
                NEW
              </span>
            )}
          </Link>
        );
      })}

      {/* Bottom status */}
      <div style={{ marginTop: "auto", padding: "16px 20px", borderTop: "1px solid var(--border-subtle)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--status-normal)", boxShadow: "0 0 4px var(--status-normal)" }} />
          <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>System Online</span>
        </div>
        <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 4 }}>3-Desk Architecture</div>
      </div>
    </nav>
  );
}
