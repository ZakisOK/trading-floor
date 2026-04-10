export default function HomePage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "var(--space-4)",
      }}
    >
      <div className="glass-panel" style={{ padding: "var(--space-8)", textAlign: "center" }}>
        <h1 style={{ color: "var(--text-primary)", fontSize: "2rem", fontWeight: 700 }}>
          The Trading Floor
        </h1>
        <p style={{ color: "var(--text-secondary)", marginTop: "var(--space-3)" }}>
          Multi-agent AI trading system — Phase 0 scaffold
        </p>
        <p style={{ color: "var(--accent-cyan)", marginTop: "var(--space-2)", fontSize: "0.875rem" }}>
          API running at{" "}
          <a href="http://localhost:8000/health" style={{ color: "var(--accent-primary)" }}>
            localhost:8000/health
          </a>
        </p>
      </div>
    </main>
  );
}
