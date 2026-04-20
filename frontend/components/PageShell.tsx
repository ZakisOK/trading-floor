"use client";
// ─────────────────────────────────────────────────────────────────────────────
// PageShell — the common scaffolding that wraps every non-Mission-Control
// page, giving the app a consistent top-meta breadcrumb + section rhythm
// matching the Mission Control handoff design.
// ─────────────────────────────────────────────────────────────────────────────
import { ReactNode } from "react";

interface PageShellProps {
  /** Breadcrumb trail. First element is the group (e.g. "Markets"); last is "here". */
  crumbs: string[];
  /** Optional right-side status badges rendered in the top meta. */
  status?: ReactNode;
  /** Page content — sections, cards, tables. */
  children: ReactNode;
}

export function PageShell({ crumbs, status, children }: PageShellProps) {
  return (
    <>
      <div className="aurora" />
      <div className="grain" />
      <main
        style={{
          flex: 1,
          minWidth: 0,
          padding: "28px 36px 64px",
          display: "flex",
          flexDirection: "column",
          gap: 32,
          position: "relative",
          zIndex: 2,
        }}
      >
        <div className="top-meta">
          <div className="crumbs">
            {crumbs.slice(0, -1).map((c, i) => (
              <span key={i}>
                {c}
                <span className="sep" style={{ marginLeft: 14 }}>/</span>
              </span>
            ))}
            <span className="here">{crumbs[crumbs.length - 1]}</span>
          </div>
          <div className="status-cluster">{status}</div>
        </div>
        {children}
      </main>
    </>
  );
}

/** Section header — `01 — Label  /  Title  /  Sub-note` */
export function SectionHeader({
  n,
  label,
  title,
  sub,
  tools,
}: {
  n: string;
  label: string;
  title: string;
  sub?: string;
  tools?: ReactNode;
}) {
  return (
    <div className="sect-hd">
      <div className="title-group">
        <span className="n">{n} — {label}</span>
        <h3>{title}</h3>
      </div>
      {sub && <div className="sub">{sub}</div>}
      {tools && <div className="tools">{tools}</div>}
    </div>
  );
}
