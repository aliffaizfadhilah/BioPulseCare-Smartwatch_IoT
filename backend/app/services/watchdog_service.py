import logging
import threading
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.database import db
from app.services.mqtt_service import mqtt_service

logger = logging.getLogger("biopulse.watchdog")


class HeartbeatWatchdog:
    """Monitors device heartbeats and marks devices offline after HEARTBEAT_TIMEOUT_SEC (30s)."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="biopulse-heartbeat-watchdog",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def check_expired_devices(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Check all currently online devices and mark offline if heartbeat timed out."""
        now_utc = now or datetime.now(timezone.utc)
        timeout_sec = settings.heartbeat_timeout_sec
        marked_offline: list[dict[str, Any]] = []

        for dev in db.list_devices():
            if dev.get("status") != "online":
                continue
            last_hb_str = dev.get("last_heartbeat_at") or dev.get("last_seen_at")
            if not last_hb_str:
                continue
            try:
                last_hb = datetime.fromisoformat(last_hb_str.replace("Z", "+00:00"))
                if last_hb.tzinfo is None:
                    last_hb = last_hb.replace(tzinfo=timezone.utc)
                elapsed = (now_utc - last_hb).total_seconds()
                if elapsed > timeout_sec:
                    device_id = dev["device_id"]
                    updated, changed = db.update_device_status(
                        device_id, "offline", reason="heartbeat_timeout"
                    )
                    if changed:
                        logger.warning(
                            "Device %s marked OFFLINE by watchdog (%.1fs without heartbeat)",
                            device_id,
                            elapsed,
                        )
                        mqtt_service._emit_ws("device_status", {"device": updated})
                        mqtt_service._trigger_alert(
                            device_id=device_id,
                            alert_type="HEARTBEAT_TIMEOUT",
                            category="Perhatian & Peringatan",
                            urgency="Perhatian",
                            title=f"Perangkat Offline (Tidak Ada Heartbeat >{timeout_sec} Detik)",
                            description=(
                                f"Perangkat BioPulse Care ({device_id}) tidak mengirim heartbeat selama "
                                f"{int(elapsed)} detik. Silakan periksa daya/koneksi perangkat dan kondisi pengguna."
                            ),
                        )
                        marked_offline.append(updated)
            except ValueError:
                continue
        return marked_offline

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check_expired_devices()
            except Exception as exc:
                logger.error("Watchdog check error: %s", type(exc).__name__)
            self._stop_event.wait(5.0)


watchdog_service = HeartbeatWatchdog()
