"""Lapisan ML opsional BioPulse Care (berjalan di server, BUKAN di ESP32).

- Random Forest  : klasifikasi jendela IMU 3 detik (60 sampel @20 Hz) -> fall / adl
- Isolation Forest: pola BPM/SpO2 jendela 5 menit yang menyimpang dari baseline

Model dibuat oleh notebook (artefak .joblib). Jika model/library belum tersedia,
layanan ini menonaktifkan dirinya dan sistem tetap berjalan dengan aturan (rule-based).
Hasil ML hanya indikasi tambahan, bukan diagnosis medis, dan TIDAK menggantikan
SOS / alarm lokal pada perangkat.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

logger = logging.getLogger("biopulse.ml")

_BACKEND_DIR = Path(__file__).resolve().parents[2]
MODEL_DIR = Path(os.getenv("ML_MODEL_DIR", str(_BACKEND_DIR / "models")))
FALL_MODEL_FILE = "biopulse_random_forest_fall.joblib"
VITAL_MODEL_FILE = "biopulse_isolation_forest_vitals.joblib"

IMU_COLS = ["ax", "ay", "az", "gx", "gy", "gz"]
FALL_COOLDOWN_SEC = float(os.getenv("ML_FALL_COOLDOWN_SEC", "30"))
VITAL_EVAL_INTERVAL_SEC = float(os.getenv("ML_VITAL_EVAL_SEC", "30"))
VITAL_WINDOW_SEC = 300.0


def _std(values: list[float]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


def extract_fall_features(window: list[list[float]], fs_hz: int,
                          accel_to_g: float | None, gyro_to_dps: float | None) -> dict[str, float]:
    """Sama persis dengan extract_fall_window_features() di notebook.

    window: list of [ax, ay, az, gx, gy, gz]; satuan mentah (m/s2 dan rad/s dari MPU6050).
    """
    rows = []
    for r in window:
        ax, ay, az, gx, gy, gz = (float(v) for v in r)
        if accel_to_g is not None:
            ax, ay, az = ax * accel_to_g, ay * accel_to_g, az * accel_to_g
        if gyro_to_dps is not None:
            gx, gy, gz = gx * gyro_to_dps, gy * gyro_to_dps, gz * gyro_to_dps
        rows.append((ax, ay, az, gx, gy, gz))

    feats: dict[str, float] = {}
    for idx, name in enumerate(IMU_COLS):
        col = [r[idx] for r in rows]
        feats[f"{name}_mean"] = sum(col) / len(col)
        feats[f"{name}_std"] = _std(col)
        feats[f"{name}_min"] = min(col)
        feats[f"{name}_max"] = max(col)
        feats[f"{name}_range"] = max(col) - min(col)

    acc_mag = [math.sqrt(r[0] ** 2 + r[1] ** 2 + r[2] ** 2) for r in rows]
    gyro_mag = [math.sqrt(r[3] ** 2 + r[4] ** 2 + r[5] ** 2) for r in rows]
    for name, v in (("acc_mag", acc_mag), ("gyro_mag", gyro_mag)):
        feats[f"{name}_mean"] = sum(v) / len(v)
        feats[f"{name}_std"] = _std(v)
        feats[f"{name}_min"] = min(v)
        feats[f"{name}_max"] = max(v)
        feats[f"{name}_range"] = max(v) - min(v)

    if len(rows) > 1:
        jerk = [
            math.sqrt(sum((rows[i][k] - rows[i - 1][k]) ** 2 for k in range(3))) * fs_hz
            for i in range(1, len(rows))
        ]
    else:
        jerk = [0.0]
    feats["jerk_mean"] = sum(jerk) / len(jerk)
    feats["jerk_max"] = max(jerk)
    tail = acc_mag[-min(fs_hz, len(acc_mag)):]
    feats["post_event_acc_std"] = _std(tail)
    return feats


def _slope_per_min(times: list[float], values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    t0 = times[0]
    x = [(t - t0) / 60.0 for t in times]
    mx = sum(x) / len(x)
    my = sum(values) / len(values)
    den = sum((xi - mx) ** 2 for xi in x)
    if den < 1e-12:
        return 0.0
    return sum((xi - mx) * (yi - my) for xi, yi in zip(x, values)) / den


class MLService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fall: dict[str, Any] | None = None
        self._vital: dict[str, Any] | None = None
        self._np: Any = None
        self.load_error: str | None = None
        self._last_fall_alert: dict[str, float] = {}
        self._vitals_buf: dict[str, deque] = {}
        self._vital_last_eval: dict[str, float] = {}
        self._vital_prev_flag: dict[str, bool] = {}
        self._last_result: dict[str, dict[str, Any]] = {}
        self._load()

    # ---------------------------------------------------------------- loading
    def _load(self) -> None:
        try:
            import joblib  # noqa: WPS433
            import numpy as np  # noqa: WPS433
            self._np = np
        except ImportError as exc:
            self.load_error = (
                f"Library ML belum terpasang ({exc.name}). "
                "Jalankan: pip install -r requirements-ml.txt"
            )
            logger.info(self.load_error)
            return

        fall_path = MODEL_DIR / FALL_MODEL_FILE
        vital_path = MODEL_DIR / VITAL_MODEL_FILE
        for path, attr in ((fall_path, "_fall"), (vital_path, "_vital")):
            if not path.exists():
                continue
            try:
                artifact = joblib.load(path)
                if isinstance(artifact, dict) and "model" in artifact:
                    setattr(self, attr, artifact)
                    logger.info("Model ML dimuat: %s", path.name)
            except Exception as exc:  # noqa: BLE001 - file model tidak valid
                self.load_error = f"Gagal memuat {path.name}: {type(exc).__name__}"
                logger.warning(self.load_error)
        if not self._fall and not self._vital and not self.load_error:
            self.load_error = (
                f"Model belum ditemukan di {MODEL_DIR}. Salin file .joblib dari notebook ke folder tersebut."
            )

    @property
    def fall_ready(self) -> bool:
        return self._fall is not None

    @property
    def vital_ready(self) -> bool:
        return self._vital is not None

    # ------------------------------------------------------------------- fall
    def predict_fall(self, device_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """data: {"fs":20,"n":60,"a":[ax,ay,az,...]*n,"g":[gx,gy,gz,...]*n, "scale":100}"""
        if not self._fall:
            return {"ok": False, "reason": "model_jatuh_belum_dimuat"}
        art = self._fall
        n_expected = int(art.get("window_samples", 60))
        scale = float(data.get("scale") or 100.0) or 100.0
        a, g = data.get("a"), data.get("g")
        if not isinstance(a, list) or not isinstance(g, list):
            return {"ok": False, "reason": "format_jendela_tidak_valid"}
        n = len(a) // 3
        if n != n_expected or len(g) != n * 3:
            return {"ok": False, "reason": f"jendela_harus_{n_expected}_sampel"}
        try:
            window = [
                [a[3 * i] / scale, a[3 * i + 1] / scale, a[3 * i + 2] / scale,
                 g[3 * i] / scale, g[3 * i + 1] / scale, g[3 * i + 2] / scale]
                for i in range(n)
            ]
            # Faktor konversi satuan PERANGKAT (MPU6050: m/s2 & rad/s) ke satuan data latih.
            # Default 1.0 = satuan sama dengan data latih (BITS-2 & MPU6050 sama-sama m/s2, rad/s).
            feats = extract_fall_features(
                window, int(art.get("imu_fs_hz", 20)),
                float(art.get("device_accel_factor", 1.0)), float(art.get("device_gyro_factor", 1.0))
            )
            cols = art["feature_columns"]
            medians = art.get("medians", {})
            row = []
            for c in cols:
                v = feats.get(c)
                if v is None or not math.isfinite(v):
                    v = medians.get(c, 0.0)
                row.append(float(v))
            model = art["model"]
            proba = model.predict_proba(self._np.array([row]))[0]
            classes = [str(c) for c in model.classes_]
            p_fall = float(proba[classes.index("fall")]) if "fall" in classes else 0.0
        except Exception as exc:  # noqa: BLE001
            logger.warning("Prediksi jatuh gagal: %s", exc)
            return {"ok": False, "reason": "prediksi_gagal"}

        threshold = float(art.get("decision_threshold", 0.4))
        bpm_spike, latest_bpm = self.has_recent_bpm_spike(device_id)
        # Fusion multimodal: jika saat kejadian jatuh detak jantung ikut melonjak drastis,
        # model dibuat lebih peka (menurunkan ambang skor 0.08) sebagai penguat bukti.
        effective_threshold = max(0.25, threshold - 0.08) if bpm_spike else threshold
        is_fall = p_fall >= effective_threshold
        now = time.time()
        alert = False
        with self._lock:
            if is_fall and now - self._last_fall_alert.get(device_id, 0.0) >= FALL_COOLDOWN_SEC:
                self._last_fall_alert[device_id] = now
                alert = True
            result = {
                "ok": True, "p_fall": round(p_fall, 3), "threshold": round(effective_threshold, 3),
                "is_fall": is_fall, "should_alert": alert,
                "bpm_spike": bpm_spike, "latest_bpm": latest_bpm,
                "acc_mag_max": round(feats["acc_mag_max"], 2), "at": now,
            }
            self._last_result.setdefault(device_id, {})["fall"] = result
        return result

    def has_recent_bpm_spike(self, device_id: str) -> tuple[bool, int]:
        """Cek apakah telemetri valid terbaru menunjukkan lonjakan BPM drastis (>=115 atau +20 dari baseline)."""
        buf = list(self._vitals_buf.get(device_id, []))
        good_bpms = [b[1] for b in buf if b[3] and b[1] > 0]
        if not good_bpms:
            return False, 0
        latest = int(round(good_bpms[-1]))
        if latest >= 115:
            return True, latest
        if len(good_bpms) >= 4:
            baseline = sum(good_bpms[:-1]) / (len(good_bpms) - 1)
            if latest >= baseline + 20.0:
                return True, latest
        return False, latest

    # ----------------------------------------------------------------- vitals
    def feed_telemetry(self, device_id: str, saved: dict[str, Any]) -> dict[str, Any] | None:
        """Dipanggil tiap telemetri. Mengembalikan hasil bila ada evaluasi baru."""
        now = time.time()
        buf = self._vitals_buf.setdefault(device_id, deque())
        bpm, spo2 = saved.get("bpm"), saved.get("spo2")
        valid = bool(saved.get("finger_detected")) and bpm and spo2 and 0 < float(bpm) and 0 < float(spo2) <= 100
        buf.append((now, float(bpm or 0), float(spo2 or 0), bool(valid)))
        while buf and now - buf[0][0] > VITAL_WINDOW_SEC:
            buf.popleft()
        if not self._vital:
            return None
        if now - self._vital_last_eval.get(device_id, 0.0) < VITAL_EVAL_INTERVAL_SEC:
            return None
        self._vital_last_eval[device_id] = now
        return self._score_vitals(device_id, now)

    def _score_vitals(self, device_id: str, now: float) -> dict[str, Any]:
        art = self._vital
        buf = list(self._vitals_buf.get(device_id, []))
        good = [b for b in buf if b[3]]
        min_samples = int(art.get("min_valid_samples", 6))
        min_ratio = float(art.get("min_valid_ratio", 0.6))
        span = (buf[-1][0] - buf[0][0]) if len(buf) > 1 else 0.0
        ratio = len(good) / len(buf) if buf else 0.0
        if span < VITAL_WINDOW_SEC * 0.9 or len(good) < min_samples or ratio < min_ratio:
            res = {"ok": False, "reason": "mengumpulkan_data_5_menit", "at": now,
                   "valid_ratio": round(ratio, 2)}
            self._last_result.setdefault(device_id, {})["vital"] = res
            self._vital_prev_flag[device_id] = False
            return res
        t = [b[0] for b in good]
        bpm = [b[1] for b in good]
        sp = [b[2] for b in good]
        feats = {
            "bpm_mean": sum(bpm) / len(bpm), "bpm_min": min(bpm), "bpm_max": max(bpm),
            "bpm_std": _std(bpm), "bpm_slope_per_min": _slope_per_min(t, bpm),
            "spo2_mean": sum(sp) / len(sp), "spo2_min": min(sp), "spo2_max": max(sp),
            "spo2_std": _std(sp), "spo2_slope_per_min": _slope_per_min(t, sp),
            "valid_ratio": ratio,
        }
        medians = art.get("medians", {})
        row = [float(feats.get(c, medians.get(c, 0.0))) for c in art["feature_columns"]]
        try:
            score = float(art["model"].score_samples(self._np.array([row]))[0])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skor vital gagal: %s", exc)
            return {"ok": False, "reason": "skor_gagal", "at": now}
        candidate = score <= float(art["score_threshold"])
        prev = self._vital_prev_flag.get(device_id, False)
        alert = bool(candidate and prev) if art.get("require_two_consecutive_flags", True) else candidate
        self._vital_prev_flag[device_id] = candidate
        res = {"ok": True, "score": round(score, 4), "candidate": candidate,
               "should_alert": alert, "bpm_mean": round(feats["bpm_mean"], 1),
               "spo2_mean": round(feats["spo2_mean"], 1), "at": now}
        self._last_result.setdefault(device_id, {})["vital"] = res
        return res

    # ----------------------------------------------------------------- status
    def status(self, device_id: str | None = None) -> dict[str, Any]:
        info: dict[str, Any] = {
            "fall_model_loaded": self.fall_ready,
            "vital_model_loaded": self.vital_ready,
            "model_dir": str(MODEL_DIR),
            "note": self.load_error,
            "disclaimer": "Hasil ML hanya indikasi tambahan, bukan diagnosis medis.",
        }
        if self.fall_ready:
            info["fall_threshold"] = float(self._fall.get("decision_threshold", 0.4))
        if device_id:
            info["last"] = self._last_result.get(device_id, {})
        return info


ml_service = MLService()
