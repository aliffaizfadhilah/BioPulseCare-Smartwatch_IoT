import base64
import hashlib
import json
import logging
import mimetypes
import socket
import struct
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.core.config import settings
from app.core.security import (
    action_rate_limiter,
    api_rate_limiter,
    get_security_headers,
    validate_device_id,
)
from app.database import db
from app.services.ml_service import ml_service
from app.services.mqtt_service import mqtt_service
from app.services.telegram_service import telegram_service
from app.services.watchdog_service import watchdog_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("biopulse.main")

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketHub:
    """Thread-safe RFC 6455 WebSocket broadcast hub."""

    def __init__(self) -> None:
        self._clients: set[socket.socket] = set()
        self._lock = threading.Lock()

    def register(self, sock: socket.socket) -> None:
        with self._lock:
            self._clients.add(sock)

    def unregister(self, sock: socket.socket) -> None:
        with self._lock:
            self._clients.discard(sock)

    @staticmethod
    def encode_frame(text: str) -> bytes:
        payload = text.encode("utf-8")
        length = len(payload)
        header = bytearray([0x81])  # FIN + text frame
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))
        return bytes(header) + payload

    def broadcast(self, message: dict[str, Any]) -> None:
        frame = self.encode_frame(json.dumps(message))
        dead: list[socket.socket] = []
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.sendall(frame)
            except OSError:
                dead.append(client)
        if dead:
            with self._lock:
                for d in dead:
                    self._clients.discard(d)


ws_hub = WebSocketHub()
mqtt_service.set_broadcaster(ws_hub.broadcast)


def dispatch_api_request(
    method: str,
    path: str,
    query_params: dict[str, list[str]],
    body: dict[str, Any] | None = None,
    client_ip: str = "127.0.0.1",
) -> tuple[int, dict[str, Any]]:
    """Core REST API router usable by both HTTP Server and unit test suite."""
    if not api_rate_limiter.is_allowed(f"api:{client_ip}"):
        return HTTPStatus.TOO_MANY_REQUESTS, {"error": "Rate limit exceeded. Try again shortly."}

    clean_path = path.rstrip("/") or "/"
    payload = body or {}

    try:
        # 1. GET /api/health
        if method == "GET" and clean_path == "/api/health":
            return HTTPStatus.OK, {
                "status": "ok",
                "service": "BioPulse Care Backend",
                "mqtt_connected": mqtt_service.is_connected,
                "mqtt_broker": f"{settings.mqtt_broker_host}:{settings.mqtt_broker_port}",
                "database_mode": "postgresql" if db.use_postgres else "sqlite",
                "telemetry_interval_sec": settings.telemetry_interval_sec,
                "heartbeat_interval_sec": settings.heartbeat_interval_sec,
                "heartbeat_timeout_sec": settings.heartbeat_timeout_sec,
            }

        # 2. GET /api/devices
        if method == "GET" and clean_path == "/api/devices":
            devices = db.list_devices()
            return HTTPStatus.OK, {"items": devices, "total": len(devices)}

        # 2b. GET /api/ml/status
        if method == "GET" and clean_path == "/api/ml/status":
            dev_id = (query_params.get("device_id") or [settings.default_device_id])[0]
            return HTTPStatus.OK, ml_service.status(dev_id)

        # 3. GET /api/dashboard/summary
        if method == "GET" and clean_path == "/api/dashboard/summary":
            dev_id = (query_params.get("device_id") or [settings.default_device_id])[0]
            category = (query_params.get("category") or ["Semua Event"])[0]
            search_q = (query_params.get("q") or [""])[0]
            days_window = int((query_params.get("days") or ["3"])[0])
            device = db.get_device(dev_id)
            telemetry_series = db.list_telemetry(
                dev_id, limit=16, reset_after_offline=True, days_window=days_window
            )
            telemetry_history = db.list_telemetry_history(
                dev_id, limit=30, days_window=days_window
            )
            alerts_data = db.list_alerts(
                dev_id,
                category=category,
                search_q=search_q,
                limit=20,
                days_window=days_window,
            )

            return HTTPStatus.OK, {
                "device": device,
                "caregiver": {
                    "full_name": "Ibu Siti Rahayu",
                    "role_label": "Keluarga / Anak",
                    "telegram_bot": settings.telegram_bot_handle,
                },
                "intervals": {
                    "telemetry_sec": settings.telemetry_interval_sec,
                    "heartbeat_sec": settings.heartbeat_interval_sec,
                    "offline_timeout_sec": settings.heartbeat_timeout_sec,
                    "fall_threshold_ms2": settings.fall_impact_threshold_ms2,
                    "dashboard_retention_days": days_window,
                },
                "mqtt": {
                    "connected": mqtt_service.is_connected,
                    "broker": settings.mqtt_broker_host,
                    "topic_prefix": f"{settings.mqtt_topic_prefix}/{device['device_id']}",
                },
                "telemetry_series": telemetry_series,
                "ml": ml_service.status(dev_id),
                "telemetry_history": telemetry_history,
                "recent_activities": [],
                "alerts": alerts_data,
                "disclaimer": (
                    "Sistem BioPulse Care merupakan prototipe pemantauan dan peringatan awal, "
                    "bukan alat diagnosis medis. Nilai BPM, SpO2, dan deteksi jatuh merupakan "
                    "indikasi/estimasi sensor."
                ),
            }

        # 4. Device-scoped routes: /api/devices/{device_id}[/...]
        if clean_path.startswith("/api/devices/"):
            segments = clean_path.split("/")[3:]
            if not segments:
                return HTTPStatus.NOT_FOUND, {"error": "Missing device_id"}
            device_id = validate_device_id(segments[0])

            # GET /api/devices/{device_id}
            if method == "GET" and len(segments) == 1:
                return HTTPStatus.OK, db.get_device(device_id)

            # GET /api/devices/{device_id}/telemetry
            if method == "GET" and len(segments) == 2 and segments[1] == "telemetry":
                limit = int((query_params.get("limit") or ["24"])[0])
                offset = int((query_params.get("offset") or ["0"])[0])
                items = db.list_telemetry(device_id, limit=limit, offset=offset)
                return HTTPStatus.OK, {"device_id": device_id, "items": items, "count": len(items)}

            # GET /api/devices/{device_id}/alerts
            if method == "GET" and len(segments) == 2 and segments[1] == "alerts":
                category = (query_params.get("category") or ["Semua Event"])[0]
                search_q = (query_params.get("q") or [""])[0]
                limit = int((query_params.get("limit") or ["25"])[0])
                offset = int((query_params.get("offset") or ["0"])[0])
                return HTTPStatus.OK, db.list_alerts(
                    device_id=device_id,
                    category=category,
                    search_q=search_q,
                    limit=limit,
                    offset=offset,
                )

            # POST /api/devices/{device_id}/alerts/{alert_id}/acknowledge
            if (
                method == "POST"
                and len(segments) == 4
                and segments[1] == "alerts"
                and segments[3] == "acknowledge"
            ):
                alert_id = int(segments[2])
                by_user = str(payload.get("acknowledged_by") or "Ibu Siti Rahayu")
                updated = db.acknowledge_alert(device_id, alert_id, acknowledged_by=by_user)
                if not updated:
                    return HTTPStatus.NOT_FOUND, {"error": "Alert not found"}
                ws_hub.broadcast({"event": "alert_updated", "data": {"alert": updated}})
                return HTTPStatus.OK, {"ok": True, "alert": updated}

            # POST /api/devices/{device_id}/command
            if method == "POST" and len(segments) == 2 and segments[1] == "command":
                if not action_rate_limiter.is_allowed(f"cmd:{client_ip}"):
                    return HTTPStatus.TOO_MANY_REQUESTS, {
                        "error": "Terlalu banyak perintah dalam waktu singkat. Tunggu sebentar."
                    }
                cmd = str(payload.get("command") or "buzzer").strip().lower()
                duration_ms = int(payload.get("duration_ms") or 3000)
                result = mqtt_service.publish_command(device_id, cmd, duration_ms=duration_ms)
                return HTTPStatus.OK, result

            # POST /api/devices/{device_id}/simulate
            if method == "POST" and len(segments) == 2 and segments[1] == "simulate":
                sim_type = str(payload.get("type") or "telemetry").strip().lower()
                if sim_type == "sos":
                    res = mqtt_service.handle_mqtt_message(
                        "telemetry",
                        {
                            "device_id": device_id,
                            "bpm": int(payload.get("bpm") or 96),
                            "spo2": int(payload.get("spo2") or 97),
                            "finger_detected": True,
                            "accel_mag": 11.4,
                            "sos_active": True,
                            "fall_candidate": False,
                        },
                    )
                    return HTTPStatus.OK, {"ok": True, "simulated": "sos", "result": res}
                if sim_type == "fall":
                    res = mqtt_service.handle_mqtt_message(
                        "telemetry",
                        {
                            "device_id": device_id,
                            "bpm": int(payload.get("bpm") or 92),
                            "spo2": int(payload.get("spo2") or 96),
                            "finger_detected": True,
                            "accel_x": 14.2,
                            "accel_y": 15.1,
                            "accel_z": 12.8,
                            "accel_mag": 24.6,
                            "sos_active": False,
                            "fall_candidate": True,
                        },
                    )
                    return HTTPStatus.OK, {"ok": True, "simulated": "fall", "result": res}
                if sim_type == "offline":
                    res = mqtt_service.handle_mqtt_message(
                        "status",
                        {"device_id": device_id, "status": "offline", "reason": "lwt"},
                    )
                    return HTTPStatus.OK, {"ok": True, "simulated": "offline", "result": res}
                if sim_type == "online":
                    res = mqtt_service.handle_mqtt_message(
                        "status",
                        {"device_id": device_id, "status": "online", "reason": "mqtt_connect"},
                    )
                    return HTTPStatus.OK, {"ok": True, "simulated": "online", "result": res}
                if sim_type == "vital_anomaly":
                    mqtt_service._last_vital_alert_ts.pop(device_id, None)
                    res = mqtt_service.handle_mqtt_message(
                        "telemetry",
                        {
                            "device_id": device_id,
                            "bpm": int(payload.get("bpm") or 132),
                            "spo2": int(payload.get("spo2") or 89),
                            "finger_detected": True,
                            "accel_mag": 9.8,
                            "sos_active": False,
                            "fall_candidate": False,
                        },
                    )
                    return HTTPStatus.OK, {"ok": True, "simulated": "vital_anomaly", "result": res}
                res = mqtt_service.handle_mqtt_message(
                    "telemetry",
                    {
                        "device_id": device_id,
                        "bpm": int(payload.get("bpm") or 78),
                        "spo2": int(payload.get("spo2") or 98),
                        "finger_detected": bool(payload.get("finger_detected", True)),
                        "accel_mag": float(payload.get("accel_mag") or 9.8),
                        "sos_active": False,
                        "fall_candidate": False,
                    },
                )
                return HTTPStatus.OK, {"ok": True, "simulated": "telemetry", "result": res}

        # 5. POST /api/notifications/test
        if method == "POST" and clean_path == "/api/notifications/test":
            if not action_rate_limiter.is_allowed(f"tgtest:{client_ip}"):
                return HTTPStatus.TOO_MANY_REQUESTS, {
                    "error": "Batas pengiriman uji Telegram tercapai. Tunggu beberapa saat."
                }
            dev_id = validate_device_id(
                str(payload.get("device_id") or settings.default_device_id)
            )
            notif_meta = telegram_service.send_alert_notification(
                device_id=dev_id,
                alert_type="TELEGRAM_TEST",
                title="Uji Koneksi Bot Telegram (@BioPulseCare_bot)",
                description=(
                    "Pengujian sinkronisasi bot darurat keluarga dari Dashboard Web BioPulse Care. "
                    "Status koneksi sistem berjalan normal."
                ),
                urgency="Uji Sistem",
                bypass_cooldown=True,
            )
            alert_rec = db.create_alert_with_notification(
                device_id=dev_id,
                alert_type="TELEGRAM_TEST",
                category="Uji Sistem",
                urgency="Uji Sistem",
                title="Uji Kirim Notifikasi Telegram Manual",
                description=(
                    f"Sinkronisasi bot {settings.telegram_bot_handle} diuji oleh Ibu Siti Rahayu. "
                    f"Hasil: {notif_meta['status_label']}."
                ),
                detection_method="Manual Test",
                action_type="Log Uji",
                notif_info=notif_meta,
            )
            ws_hub.broadcast({"event": "alert", "data": {"alert": alert_rec}})
            return HTTPStatus.OK, {"ok": True, "notification": notif_meta, "alert": alert_rec}

        return HTTPStatus.NOT_FOUND, {"error": "Endpoint not found"}

    except ValueError as exc:
        return HTTPStatus.BAD_REQUEST, {"error": str(exc)}
    except Exception as exc:
        logger.error("Unhandled API error on %s: %s", clean_path, type(exc).__name__)
        return HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal server error"}


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


class BioPulseHTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP + RFC 6455 WebSocket handler serving REST API, WebSocket, and frontend static files."""

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status_code: int, data: dict[str, Any]) -> None:
        body = json.dumps(data).encode("utf-8")
        origin = self.headers.get("Origin")
        sec_headers = get_security_headers(origin, settings.cors_allowed_origins)

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in sec_headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin")
        sec_headers = get_security_headers(origin, settings.cors_allowed_origins)
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        for k, v in sec_headers.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/ws/dashboard" and self.headers.get("Upgrade", "").lower() == "websocket":
            self._handle_websocket()
            return

        if parsed.path.startswith("/api/"):
            q = parse_qs(parsed.query)
            status, resp = dispatch_api_request(
                "GET", parsed.path, q, None, self.client_address[0]
            )
            self._send_json(status, resp)
            return

        self._serve_frontend_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Method not allowed"})
            return

        content_len = int(self.headers.get("Content-Length") or "0")
        if content_len > 65536:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Payload too large"})
            return

        raw_body = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            body_dict = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body"})
            return

        q = parse_qs(parsed.query)
        status, resp = dispatch_api_request(
            "POST", parsed.path, q, body_dict, self.client_address[0]
        )
        self._send_json(status, resp)

    def _serve_frontend_static(self, req_path: str) -> None:
        """Safely serve frontend files with strict path boundary verification."""
        dist_dir = (FRONTEND_DIR / "dist").resolve()
        base_dir = dist_dir if dist_dir.exists() else FRONTEND_DIR.resolve()

        rel = req_path.lstrip("/") or "index.html"
        candidate = (base_dir / rel).resolve()

        # Strict boundary check against directory traversal (mandatory-secure-web-skills)
        if not str(candidate).startswith(str(base_dir) + "/") and candidate != base_dir / "index.html":
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Access denied"})
            return

        if not candidate.is_file():
            candidate = (base_dir / "index.html").resolve()
            if not candidate.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Frontend file not found"})
                return

        data = candidate.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(candidate))
        content_type = mime_type or "text/html; charset=utf-8"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def _handle_websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key", "").strip()
        if not key:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing Sec-WebSocket-Key")
            return
        accept_val = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
        ).decode("ascii")

        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept_val)
        self.end_headers()

        sock = self.request
        ws_hub.register(sock)
        try:
            # Send initial connection confirmation
            welcome = ws_hub.encode_frame(
                json.dumps(
                    {
                        "event": "connected",
                        "data": {
                            "device": db.get_device(settings.default_device_id),
                            "mqtt_connected": mqtt_service.is_connected,
                        },
                    }
                )
            )
            sock.sendall(welcome)
            while True:
                hdr = sock.recv(2)
                if not hdr:
                    break
                opcode = hdr[0] & 0x0F
                if opcode == 0x08:  # Close frame
                    break
                masked = (hdr[1] & 0x80) != 0
                payload_len = hdr[1] & 0x7F
                if payload_len == 126:
                    ext = sock.recv(2)
                    payload_len = struct.unpack("!H", ext)[0]
                elif payload_len == 127:
                    ext = sock.recv(8)
                    payload_len = struct.unpack("!Q", ext)[0]
                if masked:
                    _ = sock.recv(4)
                if payload_len > 0:
                    _ = sock.recv(min(payload_len, 4096))
                if opcode == 0x09:  # Ping -> Pong
                    sock.sendall(b"\x8a\x00")
        except OSError:
            pass
        finally:
            ws_hub.unregister(sock)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def run_server(host: str | None = None, port: int | None = None) -> None:
    bind_host = host or settings.app_host
    start_port = port or settings.app_port
    server: ReusableThreadingHTTPServer | None = None
    bound_port = start_port

    for candidate_port in range(start_port, start_port + 20):
        try:
            server = ReusableThreadingHTTPServer(
                (bind_host, candidate_port), BioPulseHTTPRequestHandler
            )
            bound_port = candidate_port
            break
        except OSError:
            logger.warning("Port %d sedang digunakan aplikasi lain, mencoba port %d...", candidate_port, candidate_port + 1)

    if server is None:
        server = ReusableThreadingHTTPServer((bind_host, 0), BioPulseHTTPRequestHandler)
        bound_port = server.server_address[1]

    mqtt_service.start()
    watchdog_service.start()
    logger.info(
        "BioPulse Care Server aktif! Buka di browser: http://%s:%d (WebSocket: ws://%s:%d/ws/dashboard)",
        bind_host,
        bound_port,
        bind_host,
        bound_port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down BioPulse Care Server...")
    finally:
        mqtt_service.stop()
        watchdog_service.stop()
        server.server_close()


if __name__ == "__main__":
    run_server()
