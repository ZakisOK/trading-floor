"use client";

import {
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { OHLCVBar } from "@/lib/api";

interface OHLCVChartProps {
  data: OHLCVBar[];
  liveBar?: OHLCVBar | null;
  height?: number;
}

function toChartBar(bar: OHLCVBar): CandlestickData {
  return {
    time: (new Date(bar.ts).getTime() / 1000) as Time,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  };
}

export function OHLCVChart({ data, liveBar, height = 480 }: OHLCVChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  // Initialize chart once
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: height - 80, // Reserve space for volume pane
      layout: {
        background: { color: "transparent" },
        textColor: "rgba(238,239,241,0.65)",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: {
        vertLine: { color: "rgba(94,106,210,0.6)", width: 1, style: 2 },
        horzLine: { color: "rgba(94,106,210,0.6)", width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.08)",
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#58D68D",
      downColor: "#F85149",
      borderVisible: false,
      wickUpColor: "#58D68D",
      wickDownColor: "#F85149",
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;

    // Volume pane
    const volumeSeries = chart.addHistogramSeries({
      color: "rgba(94,106,210,0.3)",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    volumeSeriesRef.current = volumeSeries;

    // Responsive resize
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [height]);

  // Update data when it changes
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || data.length === 0) return;

    const candleData = data.map(toChartBar);
    const volumeData = data.map((bar) => ({
      time: (new Date(bar.ts).getTime() / 1000) as Time,
      value: bar.volume,
      color: bar.close >= bar.open ? "rgba(88,214,141,0.3)" : "rgba(248,81,73,0.3)",
    }));

    candleSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  // Live bar updates
  useEffect(() => {
    if (!liveBar || !candleSeriesRef.current || !volumeSeriesRef.current) return;
    candleSeriesRef.current.update(toChartBar(liveBar));
    volumeSeriesRef.current.update({
      time: (new Date(liveBar.ts).getTime() / 1000) as Time,
      value: liveBar.volume,
      color: liveBar.close >= liveBar.open ? "rgba(88,214,141,0.3)" : "rgba(248,81,73,0.3)",
    });
  }, [liveBar]);

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: `${height}px`,
        background: "transparent",
      }}
    />
  );
}
