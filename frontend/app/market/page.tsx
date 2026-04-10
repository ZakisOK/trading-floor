import { MarketExplorer } from "@/components/MarketExplorer";

export const metadata = {
  title: "Market Explorer — The Trading Floor",
  description: "Real-time OHLCV market data explorer",
};

export default function MarketPage() {
  return <MarketExplorer />;
}
