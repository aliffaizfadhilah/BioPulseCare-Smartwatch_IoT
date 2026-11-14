# BioPulse Care — Spesifikasi Desain UI/UX (Google Stitch)

Dokumen ini mendokumentasikan sistem desain dari **Google Stitch MCP** untuk proyek **BioPulse Care Monitoring Dashboard** (`projects/1443498673834917997`), dengan acuan utama pada screen:
- **Judul Screen:** `BioPulse Care - Dashboard dengan Log Notifikasi & Riwayat Event`
- **Resource ID:** `projects/1443498673834917997/screens/24d7fead204a471b94161244d0508be0`
- **Resolusi Referensi:** `2560 × 3294` (`DESKTOP`, `LIGHT` mode)

---

## 1. Filosofi & Prinsip Desain

1. **Ketenangan & Kejelasan untuk Keluarga (*Calm & Reassuring Caregiver UI*):**
   - Menggunakan latar belakang biru-putih lembut (`#f8f9ff`) dan kartu putih bersih (`#ffffff`) agar informasi tanda vital dan status keselamatan lansia mudah dipindai dalam satu pandangan tanpa menimbulkan kepanikan visual.
2. **Hierarki Status Berbasis Warna Semantik:**
   - **Biru Medis (`#006591` / `#0ea5e9`):** Identitas merek, navigasi, oksigen (SpO₂), grafik tren, dan aksi utama (*Bunyikan Gelang*, *Kirim Test Telegram*).
   - **Hijau Keselamatan (`#006e2f` / `#6bff8f`):** Status normal, kondisi aman, sensor aktif, dan notifikasi Telegram terkirim sukses.
   - **Merah / Koral Peringatan (`#b91a24` / `#ffdad7`):** Ikon detak jantung, status perhatian/dugaan jatuh, dan kondisi darurat SOS.
3. **Transparansi Non-Medis:**
   - Seluruh metrik ditampilkan sebagai **indikasi / estimasi sensor** dan **peringatan awal (dugaan jatuh)**, bukan alat diagnosis medis.

---

## 2. Design Tokens

### 2.1 Palet Warna (`namedColors`)

| Token | Hex | Penggunaan Utama |
| :--- | :--- | :--- |
| `surface` / `background` | `#f8f9ff` | Latar belakang halaman utama |
| `surface-container-lowest` | `#ffffff` | Latar belakang kartu utama & header |
| `surface-container-low` | `#eff4ff` | Latar belakang input pencarian, filter, & area grafik |
| `surface-container` | `#e5eeff` | Tombol sekunder (*Kirim Suara*, *Detail*), badge profil |
| `surface-container-high` | `#dce9ff` | Border kartu (`40%` opacity), hover tombol sekunder |
| `primary` | `#006591` | Warna aksen utama, tombol *Bunyikan Gelang*, garis grafik |
| `primary-container` | `#0ea5e9` | Titik aksen grafik, gradasi area grafik |
| `primary-fixed` | `#c9e6ff` | Latar ikon SpO₂ & badge *Info Daya* |
| `on-primary-fixed-variant` | `#004c6e` | Tombol *Kirim Test Telegram* |
| `secondary` | `#006e2f` | Teks & indikator kondisi sehat/aman |
| `secondary-fixed` | `#6bff8f` | Latar badge *Kondisi Sehat & Aman*, *Normal & Tenang*, *Sangat Baik* |
| `on-secondary-container` | `#007432` | Teks di atas badge hijau |
| `tertiary` | `#b91a24` | Ikon detak jantung & badge *Perhatian* / darurat |
| `tertiary-fixed` | `#ffdad7` | Latar lingkaran ikon detak jantung |
| `on-surface` | `#0b1c30` | Teks utama (judul, angka metrik, isi tabel) |
| `on-surface-variant` | `#3e4850` | Teks sekunder (label, subjudul, waktu) |
| `outline-variant` | `#bec8d2` | Garis pembatas halus |

### 2.2 Tipografi (`Inter`)

Seluruh teks menggunakan keluarga font **Inter** dan ikon **Material Symbols Outlined**:

| Token | Ukuran (`fontSize`) | Tinggi Baris (`lineHeight`) | Ketebalan (`fontWeight`) | Letter Spacing | Penggunaan |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `display-hero` | `3.5rem` (56px) | `4rem` | `700` | `-0.03em` | Angka utama berukuran ekstra besar |
| `metric-numeral` | `2.75rem` (44px) | `3rem` | `700` | `-0.03em` | Angka metrik kartu (`78` BPM, `98` %) |
| `headline-lg` | `2rem` (32px) | `2.5rem` | `600`/`700` | `-0.02em` | Headline banner kondisi harian & status `Aman` |
| `headline-md` | `1.25rem` (20px) | `1.75rem` | `600`/`700` | `-0.01em` | Nama brand `BioPulse`, judul seksi grafik & tabel |
| `body-lg` | `1.125rem` (18px) | `1.75rem` | `400` | `0` | Paragraf utama |
| `body-md` | `0.9375rem` (15px) | `1.5rem` | `400`/`600` | `0` | Judul aktivitas terakhir & teks umum |
| `body-sm` | `0.8125rem` (13px) | `1.25rem` | `400` | `0` | Deskripsi tabel telemetri, input pencarian |
| `label-md` | `0.875rem` (14px) | `1.25rem` | `600` | `0.01em` | Tombol aksi, label kartu metrik |
| `label-sm` | `0.75rem` (12px) | `1rem` | `600` | `0.04em` | Badge status, header kolom tabel |

### 2.3 Spacing & Radius
- **Spacing Scale:** `space-xs` (`0.25rem`), `space-sm` (`0.5rem`), `space-md` (`1rem`), `space-lg` (`1.5rem`), `space-xl` (`2.5rem`).
- **Border Radius:** Kartu utama menggunakan `rounded-2xl` (`1rem`), tombol dan input menggunakan `rounded-xl` (`0.75rem`), serta badge menggunakan `rounded-full`.

---

## 3. Struktur Komponen Screen `24d7fead204a471b94161244d0508be0`

1. **Top Navigation Header (`fixed top-0 h-16`):**
   - Kiri: Logo + teks `BioPulse`, pill identitas pengguna (`Ayah: Bpk. Soedirman`), pill status perangkat/kondisi (`Kondisi Sehat & Aman` / `Perangkat Offline` / `Peringatan Darurat`).
   - Kanan: Indikator koneksi WebSocket/MQTT, pemilih perangkat (`device_id`), dan profil caregiver (`Ibu Siti Rahayu — Keluarga / Anak`).
2. **Hero Status & Quick Action Banner:**
   - Kiri: Label `Pantauan Terkini`, headline dinamis sesuai kondisi sensor & status online/offline, indikator `Baterai Gelang` dan status koneksi (`Gelang Terhubung` / `Terputus`), serta badge disclaimer non-medis.
   - Kanan: Tombol **`Bunyikan Gelang`** (mengirim command MQTT `buzzer` ke ESP32 `GPIO13`) dan tombol **`Kirim Suara`** (mengirim command pola nada panggil/simulasi pesan suara). Jika alarm SOS/Jatuh sedang aktif, tersedia tombol **`Matikan / Reset Alarm`**.
3. **Grid 3 Kartu Metrik Vital (`grid-cols-1 md:grid-cols-3`):**
   - **Kartu 1 — Detak Jantung:** Menampilkan nilai `BPM` (`beatAvg` dari MAX30102), status deteksi jari (`signalOk`), dan badge indikasi (`Normal & Tenang` / `Perlu Perhatian` / `Jari Tidak Terdeteksi`).
   - **Kartu 2 — Kadar Oksigen (SpO2):** Menampilkan nilai `%` (`spo2Est` dari MAX30102) dan badge indikasi (`Sangat Baik` / `Perlu Perhatian`).
   - **Kartu 3 — Status Gerak & Postur:** Menampilkan status dari MPU6050 (`Aman` / `Dugaan Jatuh` / `SOS Aktif`), magnitudo akselerasi (`m/s²`), dan badge `Sensor Aktif`.
4. **Grafik Tren Hari Ini:**
   - Grafik SVG area + polyline interaktif yang merender riwayat telemetri BPM/SpO₂ dari database secara dinamis beserta titik waktu (`Pagi`, `Siang`, `Sore`, `Sekarang`) dan tombol `Lihat Riwayat Lengkap`.
5. **Panel Aktivitas Terakhir:**
   - Daftar ringkas kejadian terbaru (pemeriksaan rutin, aktivitas gerak, atau peringatan terakhir) dengan stempel waktu WIB.
6. **Panel Log Notifikasi Telegram & Riwayat Event:**
   - Header: Ikon `move_to_inbox`, judul seksi, informasi sinkronisasi `@BioPulseCare_bot`, dan tombol **`Kirim Test Telegram`**.
   - Kontrol Filter: Input pencarian real-time (`Cari event, kata kunci, atau metrik...`) dan dropdown `Kategori` (`Semua Event`, `Urgensi Normal`, `Perhatian & Peringatan`, `Status Daya`, `Uji Sistem`).
   - Tabel 5 Kolom:
     1. `WAKTU (WIB)` (Jam `HH:MM:SS` & keterangan `Hari Ini`/`Kemarin`)
     2. `TINGKAT URGENSI` (`Normal`, `Info Daya`, `Perhatian`, `Darurat SOS`, `Daya Rendah`, `Uji Sistem`)
     3. `DESKRIPSI TELEMETRI SENSOR` (Judul kejadian & rincian metrik BPM, SpO₂, akselerasi, metode deteksi `Rule-Based`)
     4. `STATUS PENGIRIMAN TELEGRAM` (Badge status pengiriman, penerima/kanal, ID pesan Telegram)
     5. `AKSI` (`Detail`, `Tinjau`, `Selesai`, `Log Uji` — membuka modal rincian atau menandai alert telah ditinjau).
