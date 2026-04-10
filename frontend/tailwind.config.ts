import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        "bg-void": "#0A0D13",
        "bg-base": "#0F1219",
        "bg-surface-1": "#171B24",
        "bg-surface-2": "#1F2430",
        "bg-surface-3": "#292E38",
        "bg-hover": "#313742",
        "accent-primary": "#5E6AD2",
        "accent-cyan": "#2DCCFF",
        "accent-profit": "#58D68D",
        "accent-loss": "#F85149",
        "status-critical": "#FF3838",
        "status-serious": "#FFB302",
        "status-caution": "#FCE83A",
        "status-normal": "#56F000",
        "status-standby": "#2DCCFF",
        "status-off": "#A4ABB6",
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "-apple-system", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "'JetBrains Mono'", "'SF Mono'", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
