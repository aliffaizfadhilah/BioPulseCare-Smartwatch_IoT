const API_BASE = "";

export async function fetchDashboardSummary(deviceId = "bp-device-001", category = "Semua Event", q = "") {
  const params = new URLSearchParams({ device_id: deviceId, category, q });
  const res = await fetch(`${API_BASE}/api/dashboard/summary?${params.toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchAlerts(deviceId = "bp-device-001", category = "Semua Event", q = "") {
  const params = new URLSearchParams({ category, q, limit: "25" });
  const res = await fetch(
    `${API_BASE}/api/devices/${encodeURIComponent(deviceId)}/alerts?${params.toString()}`,
    {
      headers: { Accept: "application/json" },
      cache: "no-store",
    }
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

export async function sendDeviceCommand(deviceId, command, durationMs = 3000) {
  const res = await fetch(`${API_BASE}/api/devices/${encodeURIComponent(deviceId)}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, duration_ms: durationMs }),
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

export async function acknowledgeAlert(deviceId, alertId) {
  const res = await fetch(
    `${API_BASE}/api/devices/${encodeURIComponent(deviceId)}/alerts/${encodeURIComponent(alertId)}/acknowledge`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acknowledged_by: "Ibu Siti Rahayu" }),
    }
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

export async function sendTelegramTest(deviceId = "bp-device-001") {
  const res = await fetch(`${API_BASE}/api/notifications/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_id: deviceId }),
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

export async function simulateHardwareEvent(deviceId, type) {
  const res = await fetch(`${API_BASE}/api/devices/${encodeURIComponent(deviceId)}/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type }),
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}
