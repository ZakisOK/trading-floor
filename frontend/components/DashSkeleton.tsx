"use client";
// ─────────────────────────────────────────────────────────────────────────────
// DashSkeleton — initial-load skeleton shown while the first data fetch is in
// flight. Replaces the 7s of blank screen a cold dashboard used to render.
// ─────────────────────────────────────────────────────────────────────────────
import { ReactNode } from "react";

interface DashSkeletonProps {
  /** Breadcrumb path for the top meta (matches PageShell). */
  crumbs?: string[];
  /** Override text — default "LOADING TRADING FLOOR…" */
  label?: string;
}

export function DashSkeleton({ crumbs = ["The Firm", "Mission Control"], label = "LOADING TRADING FLOOR" }: DashSkeletonProps) {
  return (
    <>
      <div className="aurora" />
      <div className="grain" />
      <main style={{
        flex: 1, minWidth: 0, padding: "28px 36px 64px",
        display: "flex", flexDirection: "column", gap: 32,
        position: "relative", zIndex: 2,
      }}>
        {/* Top meta */}
        <div className="top-meta">
          <div className="crumbs">
            {crumbs.slice(0, -1).map((c, i) => (
              <span key={i}>{c}<span className="sep" style={{ marginLeft: 14 }}>/</span></span>
            ))}
            <span className="here">{crumbs[crumbs.length - 1]}</span>
          </div>
          <div className="status-cluster">
            <div className="loader-pulse"><span className="pip" /><span>{label}…</span></div>
          </div>
        </div>

        {/* Mode-row placeholder */}
        <div className="skel" style={{ height: 48 }} />

        {/* Briefing placeholder — matches the briefing grid proportions */}
        <div className="briefing">
          <div className="left" style={{ minHeight: 220 }}>
            <div className="skel" style={{ height: 14, width: "40%", marginBottom: 18 }} />
            <div className="skel" style={{ height: 12, width: "78%", marginBottom: 8 }} />
            <div className="skel" style={{ height: 12, width: "66%", marginBottom: 24 }} />
            <div className="skel" style={{ height: 48, width: "72%" }} />
          </div>
          <div className="right">
            {[0,1,2,3].map(i => (
              <div key={i} className="cell" style={{ minHeight: 100 }}>
                <div className="skel" style={{ height: 10, width: "55%" }} />
                <div className="skel" style={{ height: 22, width: "40%" }} />
                <div className="skel" style={{ height: 10, width: "60%" }} />
              </div>
            ))}
          </div>
        </div>

        {/* Perf row placeholder */}
        <div className="perf">
          <div className="card" style={{ minHeight: 300, padding: 22 }}>
            <div className="skel" style={{ height: 12, width: "30%", marginBottom: 10 }} />
            <div className="skel" style={{ height: 180, marginTop: 16 }} />
          </div>
          <div className="card" style={{ minHeight: 300, padding: 22 }}>
            <div className="skel" style={{ height: 12, width: "40%", marginBottom: 14 }} />
            {[0,1,2,3].map(i => (
              <div key={i} className="skel" style={{ height: 36, marginTop: 10 }} />
            ))}
          </div>
        </div>

        {/* Three desks placeholder */}
        <div className="desks">
          {[0,1,2].map(i => (
            <div key={i} className="card" style={{ minHeight: 180, padding: 22 }}>
              <div className="skel" style={{ height: 10, width: "30%" }} />
              <div className="skel" style={{ height: 18, width: "60%", marginTop: 10 }} />
              <div className="skel" style={{ height: 36, marginTop: 14 }} />
              <div className="skel" style={{ height: 24, marginTop: 16, width: "80%" }} />
            </div>
          ))}
        </div>
      </main>
    </>
  );
}

/** Compact inline loader used as a status-cluster fallback when we have partial data. */
export function InlineLoader({ label = "syncing" }: { label?: string }) {
  return (
    <div className="loader-pulse">
      <span className="pip" />
      <span>{label}</span>
    </div>
  );
}
