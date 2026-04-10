"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createWebSocket } from "@/lib/api";

export type WSStatus = "connecting" | "open" | "closed";

export function useWebSocket(onMessage: (data: unknown) => void) {
  const [status, setStatus] = useState<WSStatus>("closed");
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    setStatus("connecting");
    wsRef.current = createWebSocket(
      (data) => onMessageRef.current(data),
      () => setStatus("open"),
      () => {
        setStatus("closed");
        // Reconnect after 3s
        setTimeout(connect, 3000);
      }
    );
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  return status;
}
