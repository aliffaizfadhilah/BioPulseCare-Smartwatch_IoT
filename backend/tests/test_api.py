import os
import unittest
from datetime import datetime, timedelta, timezone
from http import HTTPStatus

os.environ["SQLITE_DB_PATH"] = "/tmp/biopulse_test.db"

from app.database import db
from app.main import dispatch_api_request
from app.services.mqtt_service import mqtt_service
from app.services.watchdog_service import watchdog_service


class BioPulseBackendTestCase(unittest.TestCase):
    """Integration tests for REST API, MQTT ingestion, LWT, Watchdog, and Telegram log."""

    def test_01_health_and_summary(self) -> None:
        status, health = dispatch_api_request("GET", "/api/health", {})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(health["status"], "ok")

        status, summary = dispatch_api_request("GET", "/api/dashboard/summary", {})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(summary["device"]["device_id"], "bp-device-001")
        self.assertIn("indikasi", summary["disclaimer"].lower())
        self.assertGreaterEqual(len(summary["alerts"]["items"]), 5)

    def test_02_mqtt_telemetry_and_fall_candidate(self) -> None:
        # Normal telemetry
        saved = mqtt_service.handle_mqtt_message(
            "telemetry",
            {
                "device_id": "bp-device-001",
                "bpm": 81,
                "spo2": 99,
                "finger_detected": True,
                "accel_x": 0.2,
                "accel_y": 0.1,
                "accel_z": 9.8,
                "accel_mag": 9.81,
                "sos_active": False,
                "fall_candidate": False,
            },
        )
        self.assertEqual(saved["bpm"], 81)
        self.assertEqual(saved["spo2"], 99)

        # Fall candidate transition triggers alert + notification log
        fall_saved = mqtt_service.handle_mqtt_message(
            "telemetry",
            {
                "device_id": "bp-device-001",
                "bpm": 95,
                "spo2": 97,
                "finger_detected": True,
                "accel_mag": 25.4,
                "sos_active": False,
                "fall_candidate": True,
            },
        )
        self.assertTrue(fall_saved["fall_candidate"])
        alerts = db.list_alerts("bp-device-001", category="Perhatian & Peringatan")["items"]
        self.assertTrue(any("Dugaan Jatuh" in a["title"] for a in alerts))

    def test_03_lwt_offline_and_watchdog_timeout(self) -> None:
        # Simulate MQTT LWT offline message
        dev_off = mqtt_service.handle_mqtt_message(
            "status",
            {"device_id": "bp-device-001", "status": "offline", "reason": "lwt"},
        )
        self.assertEqual(dev_off["status"], "offline")

        # Bring device back online via heartbeat
        dev_on = mqtt_service.handle_mqtt_message(
            "heartbeat",
            {"device_id": "bp-device-001", "rssi": -55},
        )
        self.assertEqual(dev_on["status"], "online")

        # Simulate 35 seconds elapsed without heartbeat -> Watchdog marks offline
        future_time = datetime.now(timezone.utc) + timedelta(seconds=35)
        expired = watchdog_service.check_expired_devices(now=future_time)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["status"], "offline")

        # Restore online for subsequent tests
        mqtt_service.handle_mqtt_message(
            "status",
            {"device_id": "bp-device-001", "status": "online", "reason": "mqtt_connect"},
        )

    def test_04_commands_and_telegram_test(self) -> None:
        status, cmd_resp = dispatch_api_request(
            "POST",
            "/api/devices/bp-device-001/command",
            {},
            {"command": "buzzer", "duration_ms": 3000},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(cmd_resp["ok"])

        status, tg_resp = dispatch_api_request(
            "POST",
            "/api/notifications/test",
            {},
            {"device_id": "bp-device-001"},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(tg_resp["ok"])

    def test_05_input_validation_blocks_invalid_device_id(self) -> None:
        status, resp = dispatch_api_request(
            "GET",
            "/api/devices/../../etc/passwd",
            {},
        )
        self.assertIn(status, (HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND))


if __name__ == "__main__":
    unittest.main()
