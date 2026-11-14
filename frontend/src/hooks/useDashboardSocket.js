import { useEffect, useState } from "react";

export function useDashboardSocket(onMessage) {
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    let ws = null;
    let retryTimer = null;
    let active = true;

    function connect() {
      if (!active) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${proto}//${window.location.host}/ws/dashboard`;
      ws = new WebSocket(url);

      ws.onopen = () => {
        if (active) setWsConnected(true);
      };

      ws.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data);
          if (onMessage) onMessage(payload);
        } catch {
          // Ignore malformed WS message
        }
      };

      ws.onclose = () => {
        if (active) {
          setWsConnected(false);
          retryTimer = window.setTimeout(connect, 4000);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();
    return () => {
      active = false;
      if (retryTimer) window.clearTimeout(retryTimer);
      if (ws) ws.close();
    };
  }, [onMessage]);

  return wsConnected;
}
