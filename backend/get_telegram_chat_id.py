"""Helper script untuk memverifikasi Bot Token, mencari Chat ID, dan mengirim pesan tes ke Telegram."""

import re
from pathlib import Path
import requests

from app.core.config import _load_dotenv_file, Settings


def main() -> None:
    _load_dotenv_file()
    cfg = Settings()
    token = cfg.telegram_bot_token.strip()
    chat_id = cfg.telegram_chat_id.strip()

    if not token:
        print("\n[!] TELEGRAM_BOT_TOKEN belum diisi di backend/.env!")
        return

    print("\n1. Memeriksa validitas Token Bot ke server Telegram (getMe)...")
    try:
        me_resp = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=8.0,
        )
    except requests.RequestException as exc:
        print(f"[!] Gagal menghubungi api.telegram.org: {type(exc).__name__}")
        return

    if me_resp.status_code != 200:
        err_desc = ""
        try:
            err_desc = me_resp.json().get("description", "")
        except ValueError:
            pass
        print(f"[!] Token ditolak oleh Telegram (HTTP {me_resp.status_code}: {err_desc}).")
        print("    Penyebab umum HTTP 401:")
        print("    - Ada 1 huruf/angka pada TELEGRAM_BOT_TOKEN yang terpotong atau salah ketik saat copy-paste.")
        print("    - Token pernah di-revoke / diganti baru di @BotFather.")
        print("    Solusi:")
        print("    1. Buka @BotFather di Telegram -> ketik /mybots -> pilih bot Anda -> klik 'API Token'.")
        print("    2. Copy ulang seluruh token (format: 10_digit_angka:35_karakter_kode) ke backend/.env lalu simpan (Ctrl+S).\n")
        return

    bot_info = me_resp.json().get("result", {})
    print(f"[OK] Token VALID! Terhubung ke Bot: @{bot_info.get('username')} ({bot_info.get('first_name')})")

    print("\n2. Memeriksa TELEGRAM_CHAT_ID...")
    if chat_id:
        print(f"[OK] TELEGRAM_CHAT_ID sudah terisi di .env: {chat_id}")
    else:
        print("   Mencari Chat ID dari pesan yang masuk ke bot (getUpdates)...")
        upd_resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"limit": 20},
            timeout=8.0,
        )
        results = upd_resp.json().get("result") or [] if upd_resp.status_code == 200 else []
        for item in reversed(results):
            msg = item.get("message") or item.get("edited_message") or {}
            cid = (msg.get("chat") or {}).get("id")
            if cid is not None:
                chat_id = str(cid)
                break

        if not chat_id:
            print("[!] Belum ada pesan masuk ke bot. Buka bot Anda di Telegram lalu klik START.")
            return

        env_path = Path(__file__).resolve().parent / ".env"
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
            updated = re.sub(
                r"^TELEGRAM_CHAT_ID=.*$",
                f"TELEGRAM_CHAT_ID={chat_id}",
                content,
                flags=re.MULTILINE,
            )
            env_path.write_text(updated, encoding="utf-8")
            print(f"[OK] TELEGRAM_CHAT_ID={chat_id} berhasil disimpan ke backend/.env!")

    print(f"\n3. Mengirim pesan tes ke Chat ID {chat_id}...")
    send_resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": (
                "✅ *BioPulse Care — Koneksi Telegram Berhasil!*\n"
                "Bot darurat keluarga sudah terhubung dengan Dashboard Web & perangkat ESP32."
            ),
            "parse_mode": "Markdown",
        },
        timeout=8.0,
    )
    if send_resp.status_code == 200:
        msg_id = send_resp.json().get("result", {}).get("message_id")
        print(f"[SUKSES] Pesan tes berhasil terkirim ke Telegram Anda! (Message ID: #{msg_id})\n")
    else:
        err_desc = ""
        try:
            err_desc = send_resp.json().get("description", "")
        except ValueError:
            pass
        print(f"[!] Gagal mengirim pesan ke Chat ID {chat_id} (HTTP {send_resp.status_code}: {err_desc}).")
        print("    Pastikan Anda sudah membuka bot @{bot_info.get('username')} di Telegram dan menekan tombol START!\n")


if __name__ == "__main__":
    main()
