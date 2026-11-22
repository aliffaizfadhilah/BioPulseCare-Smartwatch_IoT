import os
import unittest

os.environ["SQLITE_DB_PATH"] = "/tmp/biopulse_test_ml.db"
os.environ["TELEGRAM_BOT_TOKEN"] = ""

from app.database import db  # noqa: E402
from app.services.ml_service import ml_service, extract_fall_features  # noqa: E402
from app.services.mqtt_service import mqtt_service  # noqa: E402


class _StubNP:
    @staticmethod
    def array(x):
        return x


class _StubFallModel:
    classes_ = ["adl", "fall"]

    def __init__(self, p_fall: float) -> None:
        self.p = p_fall

    def predict_proba(self, X):
        return [[1 - self.p, self.p] for _ in X]


def _window(peak: float = 25.0) -> dict:
    a, g = [], []
    for i in range(60):
        z = peak if i == 30 else 9.8
        a += [0, 0, int(z * 100)]
        g += [0, 0, 0]
    return {"device_id": "bp-device-001", "fs": 20, "n": 60, "scale": 100, "a": a, "g": g}


class MLIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        feats = extract_fall_features([[0, 0, 9.8, 0, 0, 0]] * 60, 20, 1.0, 1.0)
        ml_service._np = _StubNP()
        ml_service._last_fall_alert.clear()
        self.cols = list(feats.keys())

    def _install(self, p: float, thr: float = 0.5) -> None:
        ml_service._fall = {
            "model": _StubFallModel(p), "feature_columns": self.cols, "medians": {},
            "imu_fs_hz": 20, "window_samples": 60, "decision_threshold": thr,
        }

    def test_feature_count_matches_notebook(self) -> None:
        self.assertEqual(len(self.cols), 43)

    def test_fall_window_creates_ml_alert(self) -> None:
        self._install(0.9)
        res = mqtt_service.handle_mqtt_message("imu_window", _window())
        self.assertTrue(res["ok"])
        self.assertTrue(res["should_alert"])
        alerts = db.list_alerts("bp-device-001", limit=5)["items"]
        self.assertTrue(any(a["alert_type"] == "ML_FALL_SUSPECTED" for a in alerts))

    def test_below_threshold_no_alert_and_cooldown(self) -> None:
        self._install(0.2)
        res = mqtt_service.handle_mqtt_message("imu_window", _window())
        self.assertTrue(res["ok"])
        self.assertFalse(res["should_alert"])
        self._install(0.9)
        first = mqtt_service.handle_mqtt_message("imu_window", _window())
        second = mqtt_service.handle_mqtt_message("imu_window", _window())
        self.assertTrue(first["should_alert"])
        self.assertFalse(second["should_alert"])  # cooldown

    def test_bad_window_rejected(self) -> None:
        self._install(0.9)
        res = mqtt_service.handle_mqtt_message("imu_window", {"device_id": "bp-device-001", "a": [1, 2, 3], "g": [1, 2, 3]})
        self.assertFalse(res["ok"])

    def test_without_model_is_safe(self) -> None:
        ml_service._fall = None
        res = mqtt_service.handle_mqtt_message("imu_window", _window())
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()
