import json
import logging
import secrets
import socket
import struct
import threading
import time
from typing import Any, Callable

from app.core.config import settings
from app.core.security import validate_device_id
from app.database import db
from app.services.ml_service import ml_service
from app.services.telegram_service import telegram_service

logger = logging.getLogger("biopulse.mqtt")


def _encode_remaining_length(length: int) -> bytes:
    out = bytearray()
    while True:
        encoded = length % 128
        length //= 128
        if length > 0:
            encoded |= 128
        out.append(encoded)
        if length == 0:
            break
    return bytes(out)


def _encode_utf8(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack("!H", len(raw)) + raw


class NativeMQTTClient:
    """Zero-dependency MQTT v3.1.1 TCP client for subscribing and publishing."""

    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        on_message: Callable[[str, bytes], None],
        username: str = "",
        password: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.on_message = on_message
        self.username = username
        self.password = password
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self.connected = False
        self._stop_event = threading.Event()
        self._packet_id = 1

    def _next_packet_id(self) -> int:
        self._packet_id = (self._packet_id % 65535) + 1
        return self._packet_id

    def connect_and_loop(self, topics: list[str]) -> None:
        while not self._stop_event.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=8.0)
                sock.settimeout(2.0)
                self._sock = sock
                self._send_connect()
                if not self._expect_connack():
                    raise ConnectionError("MQTT CONNACK rejected")
                self.connected = True
                logger.info("Connected to MQTT broker %s:%d as %s", self.host, self.port, self.client_id)
                for t in topics:
                    self._send_subscribe(t)

                last_ping = time.monotonic()
                while not self._stop_event.is_set():
                    now = time.monotonic()
                    if now - last_ping >= 25.0:
                        with self._lock:
                            if self._sock:
                                self._sock.sendall(b"\xc0\x00")
                        last_ping = now
                    try:
                        self._read_one_packet()
                    except socket.timeout:
                        continue
            except OSError as exc:
                if self.connected:
                    logger.warning("MQTT connection lost (%s). Reconnecting...", type(exc).__name__)
                self.connected = False
            finally:
                with self._lock:
                    if self._sock:
                        try:
                            self._sock.close()
                        except OSError:
                            pass
                        self._sock = None
            if not self._stop_event.is_set():
                self._stop_event.wait(5.0)

    def _send_connect(self) -> None:
        var_header = _encode_utf8("MQTT") + bytes([4])  # Protocol Level 4 (3.1.1)
        flags = 0x02  # Clean Session
        payload = _encode_utf8(self.client_id)
        if self.username:
            flags |= 0x80
            payload += _encode_utf8(self.username)
            if self.password:
                flags |= 0x40
                payload += _encode_utf8(self.password)
        var_header += bytes([flags]) + struct.pack("!H", 60)
        body = var_header + payload
        pkt = bytes([0x10]) + _encode_remaining_length(len(body)) + body
        with self._lock:
            if self._sock:
                self._sock.sendall(pkt)

    def _expect_connack(self) -> bool:
        if not self._sock:
            return False
        hdr = self._sock.recv(4)
        return len(hdr) == 4 and hdr[0] == 0x20 and hdr[3] == 0x00

    def _send_subscribe(self, topic: str) -> None:
        pkt_id = self._next_packet_id()
        body = struct.pack("!H", pkt_id) + _encode_utf8(topic) + bytes([0x00])
        pkt = bytes([0x82]) + _encode_remaining_length(len(body)) + body
        with self._lock:
            if self._sock:
                self._sock.sendall(pkt)

    def publish(self, topic: str, payload: str, retain: bool = False) -> bool:
        body = _encode_utf8(topic) + payload.encode("utf-8")
        first_byte = 0x31 if retain else 0x30
        pkt = bytes([first_byte]) + _encode_remaining_length(len(body)) + body
        with self._lock:
            if not self._sock or not self.connected:
                return False
            try:
                self._sock.sendall(pkt)
                return True
            except OSError:
                self.connected = False
                return False

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n and self._sock:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Socket EOF")
            buf.extend(chunk)
        return bytes(buf)

    def _read_one_packet(self) -> None:
        if not self._sock:
            return
        first = self._sock.recv(1)
        if not first:
            raise ConnectionError("Broker closed socket")
        pkt_type = first[0] & 0xF0
        flags = first[0] & 0x0F

        multiplier = 1
        rem_len = 0
        while True:
            b = self._recv_exact(1)[0]
            rem_len += (b & 127) * multiplier
            if (b & 128) == 0:
                break
            multiplier *= 128

        data = self._recv_exact(rem_len) if rem_len > 0 else b""
        if pkt_type == 0x30 and len(data) >= 2:  # PUBLISH
            topic_len = struct.unpack("!H", data[:2])[0]
            pos = 2 + topic_len
            topic = data[2:pos].decode("utf-8", errors="replace")
            qos = (flags >> 1) & 0x03
            if qos > 0 and len(data) >= pos + 2:
                pkt_id = struct.unpack("!H", data[pos : pos + 2])[0]
                pos += 2
                if qos == 1:
                    with self._lock:
                        if self._sock:
                            self._sock.sendall(b"\x40\x02" + struct.pack("!H", pkt_id))
            msg_bytes = data[pos:]
            self.on_message(topic, msg_bytes)

    def stop(self) -> None:
        self._stop_event.set()


class MQTTService:
    """Manages MQTT subscription, message ingestion, and command publishing."""

    def __init__(self) -> None:
        self.broadcast_fn: Callable[[dict[str, Any]], None] | None = None
        client_id = f"{settings.mqtt_client_id_prefix}-{secrets.token_hex(4)}"
        self._client = NativeMQTTClient(
            host=settings.mqtt_broker_host,
            port=settings.mqtt_broker_port,
            client_id=client_id,
            on_message=self._on_raw_message,
            username=settings.mqtt_username,
            password=settings.mqtt_password,
        )
        self._thread: threading.Thread | None = None
        self._last_vital_alert_ts: dict[str, float] = {}

    @property
    def is_connected(self) -> bool:
        return self._client.connected

    def set_broadcaster(self, fn: Callable[[dict[str, Any]], None]) -> None:
        self.broadcast_fn = fn

    def _emit_ws(self, event_type: str, data: dict[str, Any]) -> None:
        if self.broadcast_fn:
            self.broadcast_fn({"event": event_type, "data": data})

    def start(self) -> None:
        if not settings.mqtt_enabled:
            logger.info("MQTT service disabled via configuration.")
            return
        if self._thread and self._thread.is_alive():
            return
        prefix = settings.mqtt_topic_prefix
        topics = [
            f"{prefix}/+/telemetry",
            f"{prefix}/+/heartbeat",
            f"{prefix}/+/status",
            f"{prefix}/+/alert",
            f"{prefix}/+/imu_window",
        ]
        self._thread = threading.Thread(
            target=self._client.connect_and_loop,
            args=(topics,),
            daemon=True,
            name="biopulse-mqtt-worker",
        )
        self._thread.start()

    def stop(self) -> None:
        self._client.stop()

    def _on_raw_message(self, topic: str, payload_bytes: bytes) -> None:
        try:
            parts = topic.strip("/").split("/")
            if len(parts) < 3:
                return
            topic_device_id = validate_device_id(parts[1])
            channel = parts[2]
            payload_str = payload_bytes.decode("utf-8", errors="replace").strip()
            data = json.loads(payload_str) if payload_str.startswith("{") else {"status": payload_str}
            if not isinstance(data, dict):
                return
            data.setdefault("device_id", topic_device_id)
            self.handle_mqtt_message(channel, data)
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("Ignored malformed MQTT message on %s: %s", topic, exc)

    def handle_mqtt_message(self, channel: str, data: dict[str, Any]) -> dict[str, Any]:
        """Process validated MQTT message from ESP32 or test harness."""
        device_id = validate_device_id(
            str(data.get("device_id") or settings.default_device_id)
        )

        if channel == "telemetry":
            prev_dev = db.get_device(device_id)
            saved = db.record_telemetry(data)
            updated_dev = db.get_device(device_id)
            self._emit_ws("telemetry", {"telemetry": saved, "device": updated_dev})

            # Lapisan ML opsional (Isolation Forest BPM/SpO2, jendela 5 menit)
            vital_res = ml_service.feed_telemetry(device_id, saved)
            if vital_res and vital_res.get("should_alert"):
                self._trigger_alert(
                    device_id=device_id,
                    alert_type="ML_VITAL_PATTERN",
                    category="Perhatian & Peringatan",
                    urgency="Perhatian",
                    title="Pola BPM/SpO2 Tidak Biasa (Indikasi Model)",
                    description=(
                        f"Model Isolation Forest menandai pola rata-rata 5 menit yang menyimpang dari baseline "
                        f"(BPM rata-rata {vital_res['bpm_mean']}, SpO2 estimasi {vital_res['spo2_mean']}%). "
                        "Ini hanya indikasi, bukan diagnosis. Mohon cek kondisi pengguna secara langsung."
                    ),
                    detection_method="Isolation Forest (ML)",
                )

            # Automatic rule-based edge detection if sos_active or fall_candidate transitioned to True
            if saved["sos_active"] and not prev_dev.get("sos_active"):
                self._trigger_alert(
                    device_id=device_id,
                    alert_type="SOS_MANUAL",
                    category="Perhatian & Peringatan",
                    urgency="Perhatian",
                    title="Indikasi Tombol Darurat SOS Ditekan",
                    description=(
                        f"Tombol SOS pada gelang ditekan >=2 detik. "
                        f"BPM: {saved['bpm']} • SpO2: {saved['spo2']}% • |a|: {saved['accel_mag']} m/s²."
                    ),
                )
            if saved["fall_candidate"] and not prev_dev.get("fall_candidate"):
                raw_bpm_fall = int(saved.get("raw_bpm") or 0)
                has_bpm_spike = bool(saved.get("finger_detected") and raw_bpm_fall >= 115)
                if has_bpm_spike:
                    self._trigger_alert(
                        device_id=device_id,
                        alert_type="FALL_CANDIDATE",
                        category="Perhatian & Peringatan",
                        urgency="Perhatian",
                        title="Prioritas Tinggi: Dugaan Jatuh + Lonjakan Detak Jantung",
                        description=(
                            f"Sensor MPU6050 mendeteksi hentakan {saved['accel_mag']} m/s² disertai lonjakan "
                            f"detak jantung drastis ({raw_bpm_fall} BPM). Segera periksa kondisi pengguna!"
                        ),
                        detection_method="Sensor Fusion (MPU6050 + MAX30102)",
                    )
                else:
                    self._trigger_alert(
                        device_id=device_id,
                        alert_type="FALL_CANDIDATE",
                        category="Perhatian & Peringatan",
                        urgency="Perhatian",
                        title="Dugaan Jatuh / Hentakan Kuat Terdeteksi",
                        description=(
                            f"Rule-Based MPU6050 mendeteksi lonjakan percepatan {saved['accel_mag']} m/s² "
                            f"(ambang {settings.fall_impact_threshold_ms2} m/s²). Segera periksa kondisi pengguna."
                        ),
                    )

            # Deteksi indikasi anomali BPM & SpO2 (Rule-Based Threshold saat jari terdeteksi)
            raw_bpm = int(saved.get("raw_bpm") or 0)
            raw_spo2 = int(saved.get("raw_spo2") or 0)
            if saved.get("finger_detected") and (raw_bpm > 0 or raw_spo2 > 0):
                issues: list[str] = []
                if 0 < raw_bpm < 50:
                    issues.append(f"BPM rendah ({raw_bpm} BPM < 50)")
                elif raw_bpm > 115:
                    issues.append(f"BPM tinggi ({raw_bpm} BPM > 115)")
                if 0 < raw_spo2 < 94:
                    issues.append(f"SpO2 rendah ({raw_spo2}% < 94%)")

                now_ts = time.time()
                if issues and (now_ts - self._last_vital_alert_ts.get(device_id, 0.0) >= 60.0):
                    self._last_vital_alert_ts[device_id] = now_ts
                    issue_str = " & ".join(issues)
                    self._trigger_alert(
                        device_id=device_id,
                        alert_type="VITAL_ANOMALY",
                        category="Perhatian & Peringatan",
                        urgency="Perhatian",
                        title=f"Indikasi Anomali Tanda Vital: {issue_str}",
                        description=(
                            f"Sensor MAX30102 membaca {issue_str} (BPM: {raw_bpm}, SpO2: {raw_spo2}%). "
                            "Nilai ini merupakan indikasi awal sensor (bukan diagnosis medis). "
                            "Mohon periksa posisi gelang dan kondisi pengguna."
                        ),
                        detection_method="Rule-Based Vital",
                    )
            return saved

        if channel == "imu_window":
            res = ml_service.predict_fall(device_id, data)
            self._emit_ws("ml_fall", {"device_id": device_id, "result": res})
            if res.get("should_alert"):
                if res.get("bpm_spike"):
                    self._trigger_alert(
                        device_id=device_id,
                        alert_type="ML_FALL_SUSPECTED",
                        category="Perhatian & Peringatan",
                        urgency="Perhatian",
                        title="Prioritas Tinggi: Dugaan Jatuh (ML) + Lonjakan BPM",
                        description=(
                            f"Random Forest menilai pola gerak 3 detik mirip jatuh (skor {res['p_fall']}, "
                            f"ambang {res['threshold']}; |a| maks {res['acc_mag_max']} m/s²) dan disertai "
                            f"lonjakan detak jantung ({res.get('latest_bpm')} BPM). Segera periksa pengguna!"
                        ),
                        detection_method="ML + Vital Fusion",
                    )
                else:
                    self._trigger_alert(
                        device_id=device_id,
                        alert_type="ML_FALL_SUSPECTED",
                        category="Perhatian & Peringatan",
                        urgency="Perhatian",
                        title="Dugaan Jatuh Terdeteksi Model ML",
                        description=(
                            f"Random Forest menilai pola gerak 3 detik mirip jatuh (skor {res['p_fall']}, "
                            f"ambang {res['threshold']}; |a| maks {res['acc_mag_max']} m/s²). "
                            "Ini indikasi, bukan kepastian. Segera periksa kondisi pengguna."
                        ),
                        detection_method="Random Forest (ML)",
                    )
            return res

        if channel == "heartbeat":
            updated_dev = db.record_heartbeat(data)
            self._emit_ws("device_status", {"device": updated_dev})
            return updated_dev

        if channel == "status":
            raw_status = str(data.get("status") or "offline").lower()
            reason = str(data.get("reason") or ("lwt" if raw_status == "offline" else "mqtt_connect"))
            updated_dev, changed = db.update_device_status(device_id, raw_status, reason=reason)
            self._emit_ws("device_status", {"device": updated_dev})
            if changed:
                if raw_status == "offline":
                    self._trigger_alert(
                        device_id=device_id,
                        alert_type="DEVICE_OFFLINE_LWT",
                        category="Perhatian & Peringatan",
                        urgency="Perhatian",
                        title="Perangkat BioPulse Care Terdeteksi Offline (LWT)",
                        description=(
                            "Koneksi perangkat terputus secara tidak normal (MQTT Last Will). "
                            "Silakan periksa koneksi perangkat dan lakukan pengecekan langsung terhadap pengguna."
                        ),
                    )
                else:
                    self._trigger_alert(
                        device_id=device_id,
                        alert_type="DEVICE_ONLINE",
                        category="Urgensi Normal",
                        urgency="Normal",
                        title="Perangkat Kembali Online & Tersinkronisasi",
                        description="Perangkat ESP32 berhasil terhubung kembali ke broker MQTT dan melanjutkan telemetri.",
                        action_type="Detail",
                    )
            return updated_dev

        if channel == "alert":
            alert_type = str(data.get("alert_type") or "DEVICE_ALERT").upper()
            urgency = str(data.get("urgency") or "Perhatian")
            category = str(data.get("category") or "Perhatian & Peringatan")
            title = str(data.get("title") or "Peringatan Sensor Perangkat")
            desc = str(data.get("description") or "Peringatan awal diterima dari perangkat ESP32.")
            if alert_type == "SOS_MANUAL":
                title = "Indikasi Tombol Darurat SOS Ditekan"
                category = "Perhatian & Peringatan"
                urgency = "Perhatian"
            elif alert_type == "FALL_CANDIDATE":
                title = "Dugaan Jatuh / Hentakan Kuat Terdeteksi"
                category = "Perhatian & Peringatan"
                urgency = "Perhatian"
            elif alert_type == "ALARM_RESET":
                title = "Alarm Di-reset dari Perangkat Fisik"
                category = "Urgensi Normal"
                urgency = "Normal"
            return self._trigger_alert(
                device_id=device_id,
                alert_type=alert_type,
                category=category,
                urgency=urgency,
                title=title,
                description=desc,
                action_type="Detail" if urgency == "Normal" else "Tinjau",
                device_timestamp=str(data.get("timestamp") or ""),
            )

        return {}

    def _trigger_alert(
        self,
        device_id: str,
        alert_type: str,
        category: str,
        urgency: str,
        title: str,
        description: str,
        action_type: str = "Tinjau",
        device_timestamp: str | None = None,
        detection_method: str = "Rule-Based",
    ) -> dict[str, Any]:
        notif_info = telegram_service.send_alert_notification(
            device_id=device_id,
            alert_type=alert_type,
            title=title,
            description=description,
            urgency=urgency,
        )
        alert_record = db.create_alert_with_notification(
            device_id=device_id,
            alert_type=alert_type,
            category=category,
            urgency=urgency,
            title=title,
            description=description,
            detection_method=detection_method,
            action_type=action_type,
            notif_info=notif_info,
            device_timestamp=device_timestamp,
        )
        self._emit_ws("alert", {"alert": alert_record})
        return alert_record

    def publish_command(self, device_id: str, command: str, duration_ms: int = 3000) -> dict[str, Any]:
        clean_id = validate_device_id(device_id)
        allowed_commands = {"buzzer", "voice_ping", "reset_alarm", "test_sos"}
        if command not in allowed_commands:
            raise ValueError(f"Unsupported command '{command}'. Allowed: {sorted(allowed_commands)}")

        topic = f"{settings.mqtt_topic_prefix}/{clean_id}/command"
        payload = json.dumps(
            {
                "device_id": clean_id,
                "command": command,
                "duration_ms": int(duration_ms),
                "timestamp": int(time.time()),
            }
        )
        published = self._client.publish(topic, payload, retain=False)

        # Log command action into event log so the caregiver sees immediate feedback in the table
        cmd_titles = {
            "buzzer": (
                "Perintah Bunyikan Gelang Dikirim ke ESP32",
                f"Mengaktifkan buzzer GPIO13 selama {duration_ms // 1000} detik melalui topik {topic}.",
                "Uji Sistem",
                "Uji Sistem",
            ),
            "voice_ping": (
                "Panggilan Nada Suara Dikirim ke Gelang",
                "Mengirim pola nada panggil perhatian ke perangkat pengguna (simulasi panggilan suara).",
                "Urgensi Normal",
                "Normal",
            ),
            "reset_alarm": (
                "Perintah Reset Alarm Jarak Jauh",
                "Mematikan status SOS dan kandidat jatuh dari dashboard caregiver.",
                "Urgensi Normal",
                "Normal",
            ),
            "test_sos": (
                "Simulasi Uji Sistem Darurat SOS",
                "Menguji respons sirene buzzer dan pengiriman log darurat ke kanal Telegram keluarga.",
                "Uji Sistem",
                "Uji Sistem",
            ),
        }
        title, desc, category, urgency = cmd_titles[command]
        if command == "reset_alarm":
            db.acknowledge_alert(clean_id, 0)

        alert_rec = db.create_alert_with_notification(
            device_id=clean_id,
            alert_type=f"CMD_{command.upper()}",
            category=category,
            urgency=urgency,
            title=title,
            description=desc,
            detection_method="Remote Command",
            action_type="Log Uji" if category == "Uji Sistem" else "Detail",
            notif_info={
                "recipients_label": (
                    f"MQTT Terkirim ({topic})"
                    if published
                    else "Disimpan Lokal (Menunggu Koneksi Broker)"
                ),
                "message_id_label": f"CMD #{int(time.time()) % 10000:04d}",
                "status": "sent" if published else "queued",
                "status_label": "Terkirim (Uji Sukses)" if published else "Tercatat di Sistem",
                "badge_tone": "green" if published else "blue",
                "error_detail": None,
            },
        )
        self._emit_ws("alert", {"alert": alert_rec})
        return {
            "ok": True,
            "mqtt_published": published,
            "topic": topic,
            "command": command,
            "alert": alert_rec,
        }


mqtt_service = MQTTService()
