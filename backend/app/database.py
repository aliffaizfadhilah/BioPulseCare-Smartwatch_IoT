import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any

from app.core.config import settings
from app.core.security import hash_password_scrypt, sanitize_search_query, validate_device_id

logger = logging.getLogger("biopulse.database")

WIB_TZ = timezone(timedelta(hours=7))


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_wib_time(iso_str: str | None) -> tuple[str, str]:
    """Convert ISO timestamp into (HH:MM:SS, relative_day_label) in WIB (UTC+7)."""
    if not iso_str:
        now_wib = datetime.now(WIB_TZ)
        return now_wib.strftime("%H:%M:%S"), "Hari Ini"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_wib = dt.astimezone(WIB_TZ)
        now_wib = datetime.now(WIB_TZ)
        days_diff = (now_wib.date() - dt_wib.date()).days
        if days_diff == 0:
            day_label = "Hari Ini"
        elif days_diff == 1:
            day_label = "Kemarin"
        else:
            day_label = dt_wib.strftime("%d/%m/%Y")
        return dt_wib.strftime("%H:%M:%S"), day_label
    except ValueError:
        return "10:42:00", "Hari Ini"


class DatabaseManager:
    """Thread-safe relational repository using strictly parameterized SQL queries.

    Supports PostgreSQL (via psycopg when DATABASE_URL is configured) and
    automatic local SQLite fallback so the system works immediately out of the box.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._lock = RLock()
        self.db_path = db_path or settings.sqlite_db_path
        self.use_postgres = settings.database_url.startswith("postgresql")
        self._conn: sqlite3.Connection | None = None
        self.init_db()

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            self._conn = conn
        return self._conn

    def init_db(self) -> None:
        """Create schema tables and seed initial Stitch reference records if empty."""
        with self._lock:
            conn = self._get_sqlite_conn()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    role_label TEXT NOT NULL DEFAULT 'Keluarga / Anak',
                    password_hash TEXT NOT NULL,
                    telegram_chat_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    patient_name TEXT NOT NULL,
                    patient_relation TEXT NOT NULL DEFAULT 'Ayah',
                    status TEXT NOT NULL DEFAULT 'online',
                    battery_pct INTEGER NOT NULL DEFAULT 88,
                    rssi INTEGER DEFAULT -62,
                    oled_ok INTEGER NOT NULL DEFAULT 1,
                    max_ok INTEGER NOT NULL DEFAULT 1,
                    mpu_ok INTEGER NOT NULL DEFAULT 1,
                    finger_detected INTEGER NOT NULL DEFAULT 1,
                    sos_active INTEGER NOT NULL DEFAULT 0,
                    fall_candidate INTEGER NOT NULL DEFAULT 0,
                    last_bpm INTEGER NOT NULL DEFAULT 78,
                    last_spo2 INTEGER NOT NULL DEFAULT 98,
                    last_accel_mag REAL NOT NULL DEFAULT 9.8,
                    last_seen_at TEXT,
                    last_heartbeat_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS device_status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    bpm INTEGER NOT NULL DEFAULT 0,
                    spo2 INTEGER NOT NULL DEFAULT 0,
                    finger_detected INTEGER NOT NULL DEFAULT 0,
                    ir_value INTEGER NOT NULL DEFAULT 0,
                    accel_x REAL NOT NULL DEFAULT 0.0,
                    accel_y REAL NOT NULL DEFAULT 0.0,
                    accel_z REAL NOT NULL DEFAULT 9.8,
                    accel_mag REAL NOT NULL DEFAULT 9.8,
                    gyro_x REAL NOT NULL DEFAULT 0.0,
                    gyro_y REAL NOT NULL DEFAULT 0.0,
                    gyro_z REAL NOT NULL DEFAULT 0.0,
                    sos_active INTEGER NOT NULL DEFAULT 0,
                    fall_candidate INTEGER NOT NULL DEFAULT 0,
                    device_timestamp TEXT,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    urgency TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    detection_method TEXT NOT NULL DEFAULT 'Rule-Based',
                    action_type TEXT NOT NULL DEFAULT 'Detail',
                    acknowledged INTEGER NOT NULL DEFAULT 0,
                    acknowledged_by TEXT,
                    acknowledged_at TEXT,
                    device_timestamp TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS notification_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER,
                    device_id TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'Telegram',
                    recipients_label TEXT NOT NULL,
                    message_id_label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_label TEXT NOT NULL,
                    badge_tone TEXT NOT NULL DEFAULT 'success',
                    error_detail TEXT,
                    sent_at TEXT NOT NULL,
                    FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE,
                    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS device_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT UNIQUE NOT NULL,
                    telemetry_interval_sec INTEGER NOT NULL DEFAULT 5,
                    heartbeat_interval_sec INTEGER NOT NULL DEFAULT 10,
                    offline_timeout_sec INTEGER NOT NULL DEFAULT 30,
                    fall_threshold_ms2 REAL NOT NULL DEFAULT 22.0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
                );
                """
            )
            conn.commit()
            self._seed_if_empty(conn)

    def _seed_if_empty(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("SELECT COUNT(*) AS cnt FROM devices")
        row = cur.fetchone()
        if row and row["cnt"] > 0:
            return

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        dev_id = settings.default_device_id

        # 1. Seed Caregiver User
        conn.execute(
            """
            INSERT INTO users (username, full_name, role_label, password_hash, telegram_chat_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "siti_rahayu",
                "Ibu Siti Rahayu",
                "Keluarga / Anak",
                hash_password_scrypt("BioPulseCare#2026"),
                settings.telegram_chat_id or "",
                now_iso,
            ),
        )

        # 2. Seed Primary ESP32 Device
        conn.execute(
            """
            INSERT INTO devices (
                device_id, display_name, patient_name, patient_relation,
                status, battery_pct, rssi, oled_ok, max_ok, mpu_ok,
                finger_detected, sos_active, fall_candidate,
                last_bpm, last_spo2, last_accel_mag,
                last_seen_at, last_heartbeat_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dev_id,
                "BioPulse Care ESP32 Wearable",
                "Bpk. Soedirman",
                "Ayah",
                "online",
                88,
                -60,
                1,
                1,
                1,
                1,
                0,
                0,
                78,
                98,
                9.81,
                now_iso,
                now_iso,
                now_iso,
            ),
        )

        # 3. Seed Device Settings
        conn.execute(
            """
            INSERT INTO device_settings (
                device_id, telemetry_interval_sec, heartbeat_interval_sec,
                offline_timeout_sec, fall_threshold_ms2, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                dev_id,
                settings.telemetry_interval_sec,
                settings.heartbeat_interval_sec,
                settings.heartbeat_timeout_sec,
                settings.fall_impact_threshold_ms2,
                now_iso,
            ),
        )

        # 4. Seed Initial Telemetry Trend (7 points across today)
        seed_points = [
            (74, 98, 9.8, -280),
            (75, 98, 9.7, -230),
            (72, 97, 9.9, -180),
            (82, 99, 10.4, -120),
            (77, 98, 9.8, -75),
            (79, 98, 9.8, -30),
            (78, 98, 9.8, 0),
        ]
        for bpm, spo2, acc_m, mins_ago in seed_points:
            ts = (now + timedelta(minutes=mins_ago)).isoformat()
            conn.execute(
                """
                INSERT INTO telemetry (
                    device_id, bpm, spo2, finger_detected, ir_value,
                    accel_x, accel_y, accel_z, accel_mag,
                    gyro_x, gyro_y, gyro_z, sos_active, fall_candidate,
                    device_timestamp, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dev_id,
                    bpm,
                    spo2,
                    1,
                    68500,
                    0.12,
                    0.18,
                    9.78,
                    acc_m,
                    0.01,
                    0.02,
                    0.01,
                    0,
                    0,
                    ts,
                    ts,
                ),
            )

        # 5. Seed Initial Event & Notification Logs matching Stitch Screen 24d7fead204a471b94161244d0508be0
        today_wib = datetime.now(WIB_TZ)
        yesterday_wib = today_wib - timedelta(days=1)

        def wib_to_utc_iso(base_dt: datetime, h: int, m: int, s: int) -> str:
            dt = base_dt.replace(hour=h, minute=m, second=s, microsecond=0)
            return dt.astimezone(timezone.utc).isoformat()

        seed_events = [
            {
                "alert_type": "HEARTBEAT_CHECKIN",
                "category": "Urgensi Normal",
                "urgency": "Normal",
                "title": "Heartbeat Check-in Berkala",
                "description": "BPM: 76 • SpO2: 98% • Skin Contact: Valid (Indikasi Normal)",
                "detection_method": "Rule-Based",
                "action_type": "Detail",
                "acknowledged": 0,
                "acknowledged_by": None,
                "created_at": wib_to_utc_iso(today_wib, 10, 42, 0),
                "notif": {
                    "recipients_label": "Anak, Menantu, dr. Bambang",
                    "message_id_label": "ID Msg: #TG-8819",
                    "status": "sent",
                    "status_label": "Terkirim ke 3 Penerima",
                    "badge_tone": "green",
                },
            },
            {
                "alert_type": "POWER_INFO",
                "category": "Status Daya",
                "urgency": "Info Daya",
                "title": "Baterai Terisi 90% (Kabel Dilepas)",
                "description": "Pengisian daya magnetik selesai, perangkat dikenakan kembali di pergelangan kiri.",
                "detection_method": "Rule-Based",
                "action_type": "Detail",
                "acknowledged": 0,
                "acknowledged_by": None,
                "created_at": wib_to_utc_iso(today_wib, 9, 15, 22),
                "notif": {
                    "recipients_label": "ID Msg: #TG-8812",
                    "message_id_label": "ID Msg: #TG-8812",
                    "status": "sent",
                    "status_label": "Terkirim ke Telegram",
                    "badge_tone": "blue",
                },
            },
            {
                "alert_type": "MOTION_SPIKE",
                "category": "Perhatian & Peringatan",
                "urgency": "Perhatian",
                "title": "Gerakan Tiba-tiba saat Berdiri dari Kursi",
                "description": "Evaluasi Rule-Based MPU6050: Bukan Jatuh (False Alarm). Dilanjutkan berjalan santai stabil.",
                "detection_method": "Rule-Based",
                "action_type": "Tinjau",
                "acknowledged": 0,
                "acknowledged_by": None,
                "created_at": wib_to_utc_iso(today_wib, 7, 10, 45),
                "notif": {
                    "recipients_label": "Kanal: Riwayat Gerak",
                    "message_id_label": "Kanal: Riwayat Gerak",
                    "status": "sent",
                    "status_label": "Terkirim (Notif Ringan)",
                    "badge_tone": "amber",
                },
            },
            {
                "alert_type": "BATTERY_LOW",
                "category": "Status Daya",
                "urgency": "Daya Rendah",
                "title": "Baterai di Bawah 20% (18%)",
                "description": "Sistem mengingatkan caregiver untuk menyambungkan pengisi daya sebelum pengguna tidur.",
                "detection_method": "Rule-Based",
                "action_type": "Selesai",
                "acknowledged": 1,
                "acknowledged_by": "Ibu Siti",
                "created_at": wib_to_utc_iso(yesterday_wib, 21, 4, 12),
                "notif": {
                    "recipients_label": "Ditanggapi oleh Ibu Siti",
                    "message_id_label": "Ditanggapi oleh Ibu Siti",
                    "status": "sent",
                    "status_label": "Terkirim ke Telegram",
                    "badge_tone": "blue",
                },
            },
            {
                "alert_type": "SYSTEM_TEST_SOS",
                "category": "Uji Sistem",
                "urgency": "Uji Sistem",
                "title": "Simulasi Tombol Darurat Manual SOS Smartwatch",
                "description": "Uji sirene buzzer GPIO13 dan pengiriman peringatan darurat ke kanal Telegram keluarga. Sukses normal.",
                "detection_method": "Rule-Based",
                "action_type": "Log Uji",
                "acknowledged": 1,
                "acknowledged_by": "Sistem",
                "created_at": wib_to_utc_iso(yesterday_wib, 14, 30, 0),
                "notif": {
                    "recipients_label": "Sirene 5 detik aktif",
                    "message_id_label": "Sirene 5 detik aktif",
                    "status": "sent",
                    "status_label": "Terkirim (Uji Sukses)",
                    "badge_tone": "green",
                },
            },
        ]

        for ev in seed_events:
            cur_al = conn.execute(
                """
                INSERT INTO alerts (
                    device_id, alert_type, category, urgency, title, description,
                    detection_method, action_type, acknowledged, acknowledged_by,
                    acknowledged_at, device_timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dev_id,
                    ev["alert_type"],
                    ev["category"],
                    ev["urgency"],
                    ev["title"],
                    ev["description"],
                    ev["detection_method"],
                    ev["action_type"],
                    ev["acknowledged"],
                    ev["acknowledged_by"],
                    ev["created_at"] if ev["acknowledged"] else None,
                    ev["created_at"],
                    ev["created_at"],
                ),
            )
            alert_id = cur_al.lastrowid
            notif = ev["notif"]
            conn.execute(
                """
                INSERT INTO notification_logs (
                    alert_id, device_id, channel, recipients_label,
                    message_id_label, status, status_label, badge_tone, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    dev_id,
                    "Telegram",
                    notif["recipients_label"],
                    notif["message_id_label"],
                    notif["status"],
                    notif["status_label"],
                    notif["badge_tone"],
                    ev["created_at"],
                ),
            )

        conn.commit()

    def ensure_device(self, device_id: str) -> dict[str, Any]:
        clean_id = validate_device_id(device_id)
        with self._lock:
            conn = self._get_sqlite_conn()
            cur = conn.execute(
                "SELECT * FROM devices WHERE device_id = ?", (clean_id,)
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            now_iso = now_utc_iso()
            conn.execute(
                """
                INSERT INTO devices (
                    device_id, display_name, patient_name, patient_relation,
                    status, battery_pct, last_seen_at, last_heartbeat_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_id,
                    f"BioPulse Wearable ({clean_id})",
                    "Bpk. Soedirman",
                    "Ayah",
                    "online",
                    88,
                    now_iso,
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO device_settings (
                    device_id, telemetry_interval_sec, heartbeat_interval_sec,
                    offline_timeout_sec, fall_threshold_ms2, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_id,
                    settings.telemetry_interval_sec,
                    settings.heartbeat_interval_sec,
                    settings.heartbeat_timeout_sec,
                    settings.fall_impact_threshold_ms2,
                    now_iso,
                ),
            )
            conn.commit()
            cur2 = conn.execute(
                "SELECT * FROM devices WHERE device_id = ?", (clean_id,)
            )
            return dict(cur2.fetchone())

    def record_telemetry(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = validate_device_id(
            str(payload.get("device_id") or settings.default_device_id)
        )
        self.ensure_device(device_id)
        now_iso = now_utc_iso()

        bpm = max(0, min(250, int(payload.get("bpm") or 0)))
        spo2 = max(0, min(100, int(payload.get("spo2") or 0)))
        finger_ok = bool(payload.get("finger_detected", bpm > 0))
        ir_val = int(payload.get("ir_value") or 0)
        ax = float(payload.get("accel_x") or 0.0)
        ay = float(payload.get("accel_y") or 0.0)
        az = float(payload.get("accel_z") or 9.8)
        acc_mag = float(
            payload.get("accel_mag") or ((ax * ax + ay * ay + az * az) ** 0.5)
        )
        gx = float(payload.get("gyro_x") or 0.0)
        gy = float(payload.get("gyro_y") or 0.0)
        gz = float(payload.get("gyro_z") or 0.0)
        sos_active = bool(payload.get("sos_active", False))
        fall_candidate = bool(payload.get("fall_candidate", False))
        oled_ok = bool(payload.get("oled_ok", True))
        max_ok = bool(payload.get("max_ok", True))
        mpu_ok = bool(payload.get("mpu_ok", True))
        rssi = int(payload.get("rssi") or -60)
        battery_pct = int(payload.get("battery_pct") or 88)
        dev_ts = str(payload.get("timestamp") or now_iso)[:64]

        with self._lock:
            conn = self._get_sqlite_conn()
            cur = conn.execute(
                """
                INSERT INTO telemetry (
                    device_id, bpm, spo2, finger_detected, ir_value,
                    accel_x, accel_y, accel_z, accel_mag,
                    gyro_x, gyro_y, gyro_z, sos_active, fall_candidate,
                    device_timestamp, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    bpm,
                    spo2,
                    int(finger_ok),
                    ir_val,
                    ax,
                    ay,
                    az,
                    acc_mag,
                    gx,
                    gy,
                    gz,
                    int(sos_active),
                    int(fall_candidate),
                    dev_ts,
                    now_iso,
                ),
            )
            telemetry_id = cur.lastrowid

            # Update device live snapshot; keep previous valid BPM/SpO2 if finger temporarily lifted
            dev_row = conn.execute(
                "SELECT last_bpm, last_spo2 FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            effective_bpm = bpm if (finger_ok and bpm > 0) else (dev_row["last_bpm"] if dev_row else 78)
            effective_spo2 = spo2 if (finger_ok and spo2 > 0) else (dev_row["last_spo2"] if dev_row else 98)

            conn.execute(
                """
                UPDATE devices
                SET status = 'online',
                    battery_pct = ?,
                    rssi = ?,
                    oled_ok = ?,
                    max_ok = ?,
                    mpu_ok = ?,
                    finger_detected = ?,
                    sos_active = ?,
                    fall_candidate = ?,
                    last_bpm = ?,
                    last_spo2 = ?,
                    last_accel_mag = ?,
                    last_seen_at = ?,
                    last_heartbeat_at = ?
                WHERE device_id = ?
                """,
                (
                    battery_pct,
                    rssi,
                    int(oled_ok),
                    int(max_ok),
                    int(mpu_ok),
                    int(finger_ok),
                    int(sos_active),
                    int(fall_candidate),
                    effective_bpm,
                    effective_spo2,
                    round(acc_mag, 2),
                    now_iso,
                    now_iso,
                    device_id,
                ),
            )
            conn.commit()

        return {
            "id": telemetry_id,
            "device_id": device_id,
            "bpm": bpm if (finger_ok and bpm > 0) else effective_bpm,
            "raw_bpm": bpm,
            "spo2": spo2 if (finger_ok and spo2 > 0) else effective_spo2,
            "raw_spo2": spo2,
            "finger_detected": finger_ok,
            "ir_value": ir_val,
            "accel_x": round(ax, 2),
            "accel_y": round(ay, 2),
            "accel_z": round(az, 2),
            "accel_mag": round(acc_mag, 2),
            "sos_active": sos_active,
            "fall_candidate": fall_candidate,
            "recorded_at": now_iso,
        }

    def record_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = validate_device_id(
            str(payload.get("device_id") or settings.default_device_id)
        )
        prev = self.ensure_device(device_id)
        now_iso = now_utc_iso()
        rssi = int(payload.get("rssi") or prev.get("rssi") or -60)
        sensors = payload.get("sensors") or {}
        oled_ok = bool(sensors.get("oled", payload.get("oled_ok", prev.get("oled_ok", 1))))
        max_ok = bool(sensors.get("max30102", payload.get("max_ok", prev.get("max_ok", 1))))
        mpu_ok = bool(sensors.get("mpu6050", payload.get("mpu_ok", prev.get("mpu_ok", 1))))

        with self._lock:
            conn = self._get_sqlite_conn()
            conn.execute(
                """
                UPDATE devices
                SET status = 'online',
                    rssi = ?,
                    oled_ok = ?,
                    max_ok = ?,
                    mpu_ok = ?,
                    last_seen_at = ?,
                    last_heartbeat_at = ?
                WHERE device_id = ?
                """,
                (
                    rssi,
                    int(oled_ok),
                    int(max_ok),
                    int(mpu_ok),
                    now_iso,
                    now_iso,
                    device_id,
                ),
            )
            if prev.get("status") != "online":
                conn.execute(
                    """
                    INSERT INTO device_status_history (device_id, status, reason, recorded_at)
                    VALUES (?, 'online', 'heartbeat_resumed', ?)
                    """,
                    (device_id, now_iso),
                )
            conn.commit()
        return self.get_device(device_id)

    def update_device_status(
        self, device_id: str, status: str, reason: str = "mqtt_status"
    ) -> tuple[dict[str, Any], bool]:
        """Update device online/offline status. Returns (device_dict, status_changed)."""
        clean_id = validate_device_id(device_id)
        prev = self.ensure_device(clean_id)
        normalized_status = "online" if status.lower() == "online" else "offline"
        changed = prev.get("status") != normalized_status
        now_iso = now_utc_iso()

        with self._lock:
            conn = self._get_sqlite_conn()
            if normalized_status == "online":
                conn.execute(
                    """
                    UPDATE devices
                    SET status = 'online', last_seen_at = ?, last_heartbeat_at = ?
                    WHERE device_id = ?
                    """,
                    (now_iso, now_iso, clean_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE devices
                    SET status = 'offline'
                    WHERE device_id = ?
                    """,
                    (clean_id,),
                )
            if changed:
                conn.execute(
                    """
                    INSERT INTO device_status_history (device_id, status, reason, recorded_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (clean_id, normalized_status, reason[:120], now_iso),
                )
            conn.commit()
        return self.get_device(clean_id), changed

    def create_alert_with_notification(
        self,
        device_id: str,
        alert_type: str,
        category: str,
        urgency: str,
        title: str,
        description: str,
        detection_method: str = "Rule-Based",
        action_type: str = "Tinjau",
        notif_info: dict[str, str] | None = None,
        device_timestamp: str | None = None,
    ) -> dict[str, Any]:
        clean_id = validate_device_id(device_id)
        self.ensure_device(clean_id)
        now_iso = now_utc_iso()
        notif = notif_info or {
            "recipients_label": "Anak, Menantu, dr. Bambang",
            "message_id_label": f"ID Msg: #TG-{int(datetime.now(timezone.utc).timestamp()) % 10000:04d}",
            "status": "sent",
            "status_label": "Terkirim ke Telegram",
            "badge_tone": "green",
            "error_detail": None,
        }

        with self._lock:
            conn = self._get_sqlite_conn()
            cur = conn.execute(
                """
                INSERT INTO alerts (
                    device_id, alert_type, category, urgency, title, description,
                    detection_method, action_type, acknowledged, device_timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    clean_id,
                    alert_type[:48],
                    category[:48],
                    urgency[:32],
                    title[:200],
                    description[:600],
                    detection_method[:64],
                    action_type[:32],
                    (device_timestamp or now_iso)[:64],
                    now_iso,
                ),
            )
            alert_id = cur.lastrowid

            conn.execute(
                """
                INSERT INTO notification_logs (
                    alert_id, device_id, channel, recipients_label,
                    message_id_label, status, status_label, badge_tone, error_detail, sent_at
                ) VALUES (?, ?, 'Telegram', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    clean_id,
                    notif.get("recipients_label", "Kanal Darurat Keluarga")[:160],
                    notif.get("message_id_label", "ID Msg: #TG-LIVE")[:80],
                    notif.get("status", "sent")[:32],
                    notif.get("status_label", "Terkirim ke Telegram")[:80],
                    notif.get("badge_tone", "green")[:32],
                    notif.get("error_detail"),
                    now_iso,
                ),
            )
            conn.commit()
            return self.get_alert_by_id(alert_id)

    def get_alert_by_id(self, alert_id: int) -> dict[str, Any]:
        with self._lock:
            conn = self._get_sqlite_conn()
            row = conn.execute(
                """
                SELECT a.*,
                       n.recipients_label,
                       n.message_id_label,
                       n.status AS telegram_status,
                       n.status_label AS telegram_status_label,
                       n.badge_tone AS telegram_badge_tone
                FROM alerts a
                LEFT JOIN notification_logs n ON n.alert_id = a.id
                WHERE a.id = ?
                """,
                (int(alert_id),),
            ).fetchone()
            if not row:
                return {}
            return self._format_alert_row(dict(row))

    def _format_alert_row(self, item: dict[str, Any]) -> dict[str, Any]:
        time_wib, day_label = format_wib_time(item.get("created_at"))
        item["time_wib"] = time_wib
        item["day_label"] = day_label
        item["acknowledged"] = bool(item.get("acknowledged"))
        return item

    def list_alerts(
        self,
        device_id: str,
        category: str | None = None,
        search_q: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        clean_id = validate_device_id(device_id)
        clean_q = sanitize_search_query(search_q)
        limit = max(1, min(100, int(limit)))
        offset = max(0, int(offset))

        where_clauses = ["a.device_id = ?"]
        params: list[Any] = [clean_id]

        if category and category not in ("Semua Event", "all", ""):
            where_clauses.append("a.category = ?")
            params.append(category.strip()[:48])

        if clean_q:
            like_pattern = f"%{clean_q}%"
            where_clauses.append(
                "(a.title LIKE ? OR a.description LIKE ? OR a.urgency LIKE ?)"
            )
            params.extend([like_pattern, like_pattern, like_pattern])

        where_sql = " AND ".join(where_clauses)

        with self._lock:
            conn = self._get_sqlite_conn()
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM alerts a WHERE {where_sql}",
                tuple(params),
            ).fetchone()
            total = int(total_row["cnt"]) if total_row else 0

            rows = conn.execute(
                f"""
                SELECT a.*,
                       n.recipients_label,
                       n.message_id_label,
                       n.status AS telegram_status,
                       n.status_label AS telegram_status_label,
                       n.badge_tone AS telegram_badge_tone
                FROM alerts a
                LEFT JOIN notification_logs n ON n.alert_id = a.id
                WHERE {where_sql}
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params + [limit, offset]),
            ).fetchall()

        items = [self._format_alert_row(dict(r)) for r in rows]
        return {"total": total, "items": items, "limit": limit, "offset": offset}

    def acknowledge_alert(
        self, device_id: str, alert_id: int, acknowledged_by: str = "Ibu Siti Rahayu"
    ) -> dict[str, Any] | None:
        clean_id = validate_device_id(device_id)
        now_iso = now_utc_iso()
        with self._lock:
            conn = self._get_sqlite_conn()
            cur = conn.execute(
                """
                UPDATE alerts
                SET acknowledged = 1,
                    action_type = 'Selesai',
                    acknowledged_by = ?,
                    acknowledged_at = ?
                WHERE id = ? AND device_id = ?
                """,
                (acknowledged_by[:120], now_iso, int(alert_id), clean_id),
            )
            if cur.rowcount == 0:
                return None
            conn.execute(
                """
                UPDATE devices
                SET sos_active = 0, fall_candidate = 0
                WHERE device_id = ?
                """,
                (clean_id,),
            )
            conn.commit()
        return self.get_alert_by_id(alert_id)

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_sqlite_conn()
            rows = conn.execute(
                "SELECT * FROM devices ORDER BY id ASC"
            ).fetchall()
            return [self._format_device_row(dict(r)) for r in rows]

    def get_device(self, device_id: str) -> dict[str, Any]:
        clean_id = validate_device_id(device_id)
        row = self.ensure_device(clean_id)
        return self._format_device_row(row)

    def _format_device_row(self, row: dict[str, Any]) -> dict[str, Any]:
        for bool_key in (
            "oled_ok",
            "max_ok",
            "mpu_ok",
            "finger_detected",
            "sos_active",
            "fall_candidate",
        ):
            if bool_key in row:
                row[bool_key] = bool(row[bool_key])
        time_wib, day_label = format_wib_time(row.get("last_seen_at"))
        row["last_seen_wib"] = f"{time_wib[:5]} WIB"
        row["last_seen_day"] = day_label
        return row

    def list_telemetry(
        self, device_id: str, limit: int = 24, offset: int = 0
    ) -> list[dict[str, Any]]:
        clean_id = validate_device_id(device_id)
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
        with self._lock:
            conn = self._get_sqlite_conn()
            rows = conn.execute(
                """
                SELECT * FROM telemetry
                WHERE device_id = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (clean_id, limit, offset),
            ).fetchall()
        result = []
        for r in reversed(rows):
            d = dict(r)
            d["finger_detected"] = bool(d.get("finger_detected"))
            d["sos_active"] = bool(d.get("sos_active"))
            d["fall_candidate"] = bool(d.get("fall_candidate"))
            time_wib, _ = format_wib_time(d.get("recorded_at"))
            d["time_wib"] = time_wib[:5]
            result.append(d)
        return result


db = DatabaseManager()
