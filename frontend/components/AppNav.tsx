"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

// ─── Nav structure ────────────────────────────────────────────────────────────
interface NavItem {
  href: string;
  label: string;
  icon: string;
}
interface NavGroup {
  group: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    group: "The Firm",
    items: [
      { href: "/",           label: "Mission Control", icon: "◉" },
      { href: "/firm",       label: "Overview",        icon: "⬡" },
      { href: "/positions",  label: "Positions",       icon: "▦" },
      { href: "/signals",    label: "Signals",         icon: "⚡" },
      { href: "/polymarket", label: "Polymarket",      icon: "◈" },
    ],
  },
  {
    group: "Markets",
    items: [
      { href: "/market",       label: "Crypto",       icon: "₿" },
      { href: "/commodities",  label: "Commodities",  icon: "⬡" },
      { href: "/backtest",     label: "Backtesting",  icon: "⏱" },
    ],
  },
  {
    group: "Intelligence",
    items: [
      { href: "/agents",      label: "Agents",       icon: "⬡" },
      { href: "/copy-trade",  label: "Copy Trade",   icon: "◎" },
      { href: "/floor",       label: "Trading Floor", icon: "⬡" },
      { href: "/risk",        label: "Risk",         icon: "⚠" },
      { href: "/execution",   label: "Execution",    icon: "▶" },
    ],
  },
];

export function AppNav() {
  const pathname = usePathname();

  return (
    <nav style={{
      width: 220, minHeight: "100vh", background: "var(--bg-base)",
      borderRight: "1px solid var(--border-subtle)", display: "flex",
      flexDirection: "column", padding: "20px 0 24px", flexShrink: 0,
      position: "sticky", top: 0, height: "100vh", overflowY: "auto",
    }}>
      {/* Logo / wordmark */}
      <div style={{ padding: "0 18px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
        <div style={{
          fontSize: 15, fontWeight: 800, color: "var(--text-primary)",
          letterSpacing: "0.04em", lineHeight: 1.2,
        }}>
          THE TRADING FLOOR
        </div>
        <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 3, letterSpacing: "0.12em", textTransform: "uppercase" }}>
          Multi-Asset AI Desk
        </div>
      </div>

      {/* Nav groups */}
      <div style={{ flex: 1, padding: "16px 0" }}>
        {NAV_GROUPS.map((group) => (
          <div key={group.group} style={{ marginBottom: 20 }}>
            {/* Group label */}
            <div style={{
              fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)",
              textTransform: "uppercase", letterSpacing: "0.12em",
              padding: "0 18px", marginBottom: 6,
            }}>
              {group.group}
            </div>

            {/* Group items */}
            {group.items.map(({ href, label, icon }) => {
              const isActive = pathname === href || (href !== "/" && pathname.startsWith(href));
              return (
                <Link
                  key={href}
                  href={href}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "8px 18px",
                    textDecoration: "none",
                    fontSize: 13,
                    fontWeight: isActive ? 600 : 400,
                    color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                    background: isActive ? "rgba(255,255,255,0.06)" : "transparent",
                    borderRight: isActive ? "2px solid var(--accent-info)" : "2px solid transparent",
                    transition: "background 0.15s, color 0.15s",
                  }}
                >
                  <span style={{
                    fontSize: 14, width: 18, textAlign: "center", flexShrink: 0,
                    color: isActive ? "var(--accent-info)" : "var(--text-tertiary)",
                  }}>
                    {icon}
                  </span>
                  {label}

                  {/* "New" badge for copy-trade */}
                  {href === "/copy-trade" && (
                    <span style={{
                      marginLeft: "auto", fontSize: 9, fontWeight: 700,
                      background: "rgba(99,102,241,0.2)", color: "var(--accent-info)",
                      padding: "1px 5px", borderRadius: 3, textTransform: "uppercase", letterSpacing: "0.06em",
                    }}>
                      new
                    </span>
                  )}
                  {href === "/commodities" && (
                    <span style={{
                      marginLeft: "auto", fontSize: 9, fontWeight: 700,
                      background: "rgba(99,102,241,0.2)", color: "var(--accent-info)",
                      padding: "1px 5px", borderRadius: 3, textTransform: "uppercase", letterSpacing: "0.06em",
                    }}>
                      new
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </div>

      {/* Status footer */}
      <div style={{
        padding: "14px 18px 0",
        borderTop: "1px solid var(--border-subtle)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <div style={{
            width: 6, height: 6, borderRadius: "50%",
            background: "var(--accent-profit)",
            boxShadow: "0 0 5px var(--accent-profit)",
          }} />
          <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>System Online</span>
        </div>
        <div style={{ fontSize: 10, color: "var(--text-tertiary)", lineHeight: 1.6 }}>
          Crypto · Commodities<br />
          Copy Trade Active
        </div>
      </div>
    </nav>
  );
}
