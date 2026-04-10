import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { AppNav } from "@/components/AppNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "The Trading Floor",
  description: "Multi-agent AI trading system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body style={{ background: "var(--bg-void)", color: "var(--text-primary)", display: "flex", minHeight: "100vh" }}>
        <AppNav />
        <main style={{ flex: 1, minWidth: 0, overflowY: "auto" }}>
          {children}
        </main>
      </body>
    </html>
  );
}
