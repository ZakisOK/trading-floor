import Link from "next/link";

export default function HomePage() {
  const pages = [
    { href: "/market", label: "Market Explorer", description: "Live OHLCV charts" },
  ];

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "var(--space-4)",
        padding: "var(--space-8)",
      }}
    >
      <div className="glass-panel" style={{ padding: "var(--space-8)", maxWidth: "480px", width: "100%" }}>
        <h1
          style={{
            color: "var(--text-primary)",
            fontSize: "1.75rem",
            fontWeight: 700,
            letterSpacing: "-0.04em",
            marginBottom: "var(--space-2)",
          }}
        >
          The Trading Floor
        </h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: "var(--space-6)", fontSize: "13px" }}>
          Multi-agent AI trading system
        </p>

        <nav style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
          {pages.map((page) => (
            <Link
              key={page.href}
              href={page.href}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "var(--space-3) var(--space-4)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-default)",
                background: "var(--bg-surface-2)",
                color: "var(--text-primary)",
                textDecoration: "none",
                fontSize: "13px",
                fontWeight: 500,
                transition: "border-color 0.1s",
              }}
            >
              <span>{page.label}</span>
              <span style={{ color: "var(--text-tertiary)", fontSize: "11px" }}>
                {page.description}
              </span>
            </Link>
          ))}
        </nav>

        <div
          style={{
            marginTop: "var(--space-6)",
            paddingTop: "var(--space-4)",
            borderTop: "1px solid var(--border-subtle)",
            fontSize: "11px",
            color: "var(--text-tertiary)",
            fontFamily: "var(--font-mono)",
          }}
        >
          <a
            href="http://localhost:8000/health"
            style={{ color: "var(--accent-primary)" }}
            target="_blank"
            rel="noopener noreferrer"
          >
            localhost:8000/health
          </a>
          {" · Phase 1"}
        </div>
      </div>
    </main>
  );
}
