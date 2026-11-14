import logging
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import requests

from app.core.config import settings

logger = logging.getLogger("biopulse.telegram")


class TelegramService:
    """Telegram Bot notification sender with deduplication, cooldown, and safe non-medical phrasing."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._last_sent: dict[tuple[str, str], float] = {}
        self._discovered_chat_id: str = ""

    def _next_msg_tag(self) -> str:
        seq = int(datetime.now(timezone.utc).timestamp()) % 10000
        return f"ID Msg: #TG-{seq:04d}"

    def resolve_chat_id(self, token: str) -> str:
        """Return configured TELEGRAM_CHAT_ID or auto-discover it via getUpdates if user sent /start."""
        if settings.telegram_chat_id:
            return settings.telegram_chat_id
        if self._discovered_chat_id:
            return self._discovered_chat_id
        if not token:
            return ""
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"limit": 10},
                timeout=5.0,
            )
            if resp.status_code == 200:
                data: dict[str, Any] = resp.json()
                results = data.get("result") or []
                for item in reversed(results):
                    msg = (
                        item.get("message")
                        or item.get("edited_message")
                        or item.get("channel_post")
                        or {}
                    )
                    chat = msg.get("chat") or {}
                    cid = chat.get("id")
                    if cid is not None:
                        self._discovered_chat_id = str(cid)
                        logger.info(
                            "Auto-discovered Telegram Chat ID: %s (Tambahkan ke TELEGRAM_CHAT_ID di .env)",
                            self._discovered_chat_id,
                        )
                        return self._discovered_chat_id
        except requests.RequestException:
            pass
        return ""

    def send_alert_notification(
        self,
        device_id: str,
        alert_type: str,
        title: str,
        description: str,
        urgency: str = "Perhatian",
        bypass_cooldown: bool = False,
    ) -> dict[str, str]:
        """Send Telegram message with deduplication and rate limiting.

        Returns notification metadata dictionary ready to store in notification_logs.
        """
        now_mono = time.monotonic()
        dedup_key = (device_id, alert_type)

        with self._lock:
            last_time = self._last_sent.get(dedup_key, 0.0)
            if not bypass_cooldown and (now_mono - last_time) < settings.telegram_cooldown_sec:
                return {
                    "recipients_label": "Deduplikasi Aktif (Cooldown)",
                    "message_id_label": "Rate-Limited",
                    "status": "throttled",
                    "status_label": "Ditahan (Cegah Spam)",
                    "badge_tone": "amber",
                    "error_detail": "Within cooldown window",
                }
            self._last_sent[dedup_key] = now_mono

        # Compose non-medical warning text (Sections 1 & 8 of Guide)
        text = (
            f"🔔 *BioPulse Care — Peringatan Awal ({urgency})*\n"
            f"Perangkat: `{device_id}`\n"
            f"Kejadian: *{title}*\n"
            f"Rincian: {description}\n\n"
            f"_Catatan: Informasi ini merupakan indikasi/estimasi sensor awal, bukan diagnosis medis. "
            f"Silakan lakukan pengecekan langsung terhadap pengguna._"
        )

        token = settings.telegram_bot_token
        chat_id = self.resolve_chat_id(token)

        if not token or not chat_id:
            # Local simulation mode when token is not configured in .env yet
            tone = "green" if urgency in ("Normal", "Uji Sistem", "Darurat SOS") else "blue"
            if urgency == "Perhatian":
                tone = "amber"
            return {
                "recipients_label": "Anak, Menantu, dr. Bambang (Mode Simulasi Lokal)",
                "message_id_label": self._next_msg_tag(),
                "status": "simulated",
                "status_label": (
                    "Terkirim (Uji Lokal)"
                    if alert_type == "TELEGRAM_TEST"
                    else "Terkirim ke 3 Penerima"
                ),
                "badge_tone": tone,
                "error_detail": None,
            }

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
                timeout=6.0,
            )
            if resp.status_code == 200:
                data: dict[str, Any] = resp.json()
                msg_id = data.get("result", {}).get("message_id", "OK")
                return {
                    "recipients_label": f"Kanal Keluarga ({settings.telegram_bot_handle})",
                    "message_id_label": f"ID Msg: #TG-{msg_id}",
                    "status": "sent",
                    "status_label": "Terkirim ke Telegram",
                    "badge_tone": "green",
                    "error_detail": None,
                }
            logger.warning("Telegram API returned non-200 status: %s", resp.status_code)
            return {
                "recipients_label": f"Kanal Keluarga ({settings.telegram_bot_handle})",
                "message_id_label": "Gagal Kirim",
                "status": "failed",
                "status_label": f"Gagal HTTP {resp.status_code}",
                "badge_tone": "red",
                "error_detail": f"HTTP {resp.status_code}",
            }
        except requests.RequestException as exc:
            logger.warning("Telegram delivery error: %s", type(exc).__name__)
            return {
                "recipients_label": "Jaringan / Internet Terputus",
                "message_id_label": "Tertunda",
                "status": "failed",
                "status_label": "Gagal (Offline)",
                "badge_tone": "red",
                "error_detail": type(exc).__name__,
            }


telegram_service = TelegramService()
