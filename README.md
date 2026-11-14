# BioPulse Care — Sistem Pemantauan Lansia Berbasis ESP32, MQTT, & Web Dashboard

> **Catatan Penting (Non-Medis):** BioPulse Care adalah prototipe perangkat pemantauan kondisi pengguna dan peringatan awal (*early warning*), **bukan alat diagnosis medis**. Seluruh nilai BPM, SpO₂, dan deteksi gerakan merupakan **indikasi / estimasi sensor** (seperti *dugaan jatuh*).

---

## 1. Struktur Proyek

```text
Web BioPulse IoT/
├── firmware/
│   └── BioPulse/
│       └── BioPulse.ino           # Firmware aktual ESP32 (Arduino IDE) + Virtual GND + MQTT LWT
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── config.py          # Konfigurasi environment variables (.env)
│   │   │   └── security.py        # Validasi input, rate-limiter, scrypt hash, & HTTP security headers
│   │   ├── services/
│   │   │   ├── mqtt_service.py    # Subscriber & Publisher MQTT (EMQX) + LWT handler
│   │   │   ├── watchdog_service.py# Watchdog Heartbeat (Timeout 30 detik)
│   │   │   └── telegram_service.py# Pengiriman Bot Telegram (@BioPulseCare_bot) + deduplikasi
│   │   ├── database.py            # Repository PostgreSQL / SQLite (parameterized queries)
│   │   └── main.py                # Server REST API + WebSocket (/ws/dashboard) + Static UI
│   ├── tests/
│   │   └── test_api.py            # Unit & Integration Tests
│   ├── schema.sql                 # DDL Skema PostgreSQL Multi-Device
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html                 # UI Desain Google Stitch (24d7fead204a471b94161244d0508be0)
│   ├── app.js                     # Controller real-time WebSocket & REST API (DOM-safe)
│   ├── src/                       # Komponen modular React + Vite + Tailwind CSS
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.js
├── docs/
│   ├── ARCHITECTURE.md            # Dokumentasi arsitektur, topik MQTT, skema DB, & API
│   └── DESIGN.md                  # Dokumentasi Design Tokens Google Stitch
└── docker-compose.yml             # Orkestrasi PostgreSQL 16 & Backend
```

---

## 2. Wiring Aktual Perangkat Keras ESP32 (Tidak Diubah)

| Komponen | Pin ESP32 | Konfigurasi |
| :--- | :--- | :--- |
| **SDA** (OLED SSD1306, MPU6050, MAX30102) | `GPIO 25` | Bus I²C bersama (100 kHz) |
| **SCL** (OLED SSD1306, MPU6050, MAX30102) | `GPIO 26` | Bus I²C bersama (100 kHz) |
| **Buzzer** | `GPIO 13` | `BUZZER_PASIF = 0`, `BUZZER_ACTIVE_LOW = 1` |
| **Tombol SOS** | `GPIO 32` | `INPUT_PULLUP` (Kaki sebelahnya ke `GPIO 14` sebagai Virtual GND `LOW`) |
| **Tombol Reset** | `GPIO 33` | `INPUT_PULLUP` (Kaki sebelahnya ke `GPIO 27` sebagai Virtual GND `LOW`) |

---

## 3. Cara Menjalankan Website & Menghubungkan ke Perangkat ESP32

### Langkah 1 — Jalankan Server Backend & Dashboard Web
Server backend sudah menyediakan REST API, WebSocket (`/ws/dashboard`), subscriber MQTT (`broker.emqx.io:1883`), Watchdog Heartbeat 30 detik, serta langsung menyajikan antarmuka web Google Stitch:

```bash
cd "/home/alif/Web BioPulse IoT/backend"
python3 -m app.main
```

Buka browser ke:
- **Dashboard Web Utama:** `http://127.0.0.1:8000`
- **Health Check API:** `http://127.0.0.1:8000/api/health`
- **Summary API:** `http://127.0.0.1:8000/api/dashboard/summary`

*(Opsional)* Jika ingin menjalankan mode pengembangan Vite + React terpisah di port `5173`:
```bash
cd "/home/alif/Web BioPulse IoT/frontend"
npm install
npm run dev
```

### Langkah 2 — Unggah Firmware ke ESP32 melalui Arduino IDE
1. Buka file `firmware/BioPulse/BioPulse.ino` di **Arduino IDE**.
2. Pada baris **30–31**, isi nama Wi-Fi dan password Anda:
   ```cpp
   #define WIFI_SSID     "NAMA_WIFI_ANDA"
   #define WIFI_PASSWORD "PASSWORD_WIFI_ANDA"
   ```
3. Pastikan `DEVICE_ID` bernilai `"bp-device-001"` (sama dengan `DEFAULT_DEVICE_ID` di backend).
4. Pilih board **ESP32 Dev Module** dan port serial yang sesuai, lalu klik **Upload**.
5. Buka **Serial Monitor (115200 baud)**:
   - Ketik `m` untuk melihat status koneksi Wi-Fi, MQTT, dan antrean offline.
   - Ketik `s` untuk simulasi SOS, `j` untuk simulasi dugaan jatuh, `r` untuk reset alarm, `b` untuk uji buzzer.
   - Di halaman web (`http://127.0.0.1:8000`), klik tombol **"Bunyikan Gelang"** untuk membunyikan buzzer fisik pada ESP32 dari jarak jauh melalui MQTT (`biopulse/bp-device-001/command`).

---

## 4. Menjalankan Pengujian Otomatis

```bash
PYTHONPATH="/home/alif/Web BioPulse IoT/backend" python3 -m unittest discover -s "/home/alif/Web BioPulse IoT/backend/tests" -v
```
