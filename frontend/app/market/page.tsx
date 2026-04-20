import { MarketExplorer } from "@/components/MarketExplorer";
import { PageShell } from "@/components/PageShell";

export const metadata = {
  title: "Market Explorer — The Trading Floor",
  description: "Real-time OHLCV market data explorer",
};

export default function MarketPage() {
  return (
    <PageShell
      crumbs={["The Firm", "Markets", "Crypto"]}
      status={<div className="st"><span className="d ok" /> OHLCV streaming</div>}
    >
      <MarketExplorer />
    </PageShell>
  );
}
