"""
BioPulse Care - Database Viewer & Export Tool
Memudahkan melihat dan mengekspor data SQLite biopulse.db
"""

import sys
import os
import sqlite3
import argparse
import csv

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "biopulse.db")

def print_banner():
    print("=" * 72)
    print("        🩺 BIOPULSE CARE - DATABASE INSPECTION TOOL 🩺        ")
    print("=" * 72)
    print(f"Lokasi Database : {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("[!] File biopulse.db belum ditemukan.")
        sys.exit(1)
    size_kb = os.path.getsize(DB_PATH) / 1024
    print(f"Ukuran File DB  : {size_kb:.2f} KB\n")

def get_counts(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [row[0] for row in cur.fetchall()]
    print("📊 JUMLAH DATA DALAM TABEL (STATUS PERSISTENSI):")
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = cur.fetchone()[0]
        print(f"  • {t:<22}: {cnt:>6} baris tersimpan")
    print("-" * 72)

def show_recent_telemetry(conn, limit=5):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT recorded_at, bpm, spo2, finger_detected, accel_mag, sos_active, fall_candidate
        FROM telemetry
        ORDER BY id DESC
        LIMIT {limit}
    """)
    rows = cur.fetchall()
    print(f"\n📈 {limit} DATA TELEMETRI SENSOR TERAKHIR:")
    print(f"{'Waktu':<20} | {'BPM':<6} | {'SpO2':<6} | {'Jari':<6} | {'Akselerasi':<10} | {'Status'}")
    print("-" * 72)
    for r in rows:
        ts, bpm, spo2, finger, mag, sos, fall = r
        ts_clean = ts[:19] if ts else "-"
        finger_str = "Ada" if finger else "Tidak"
        status_note = "Normal"
        if sos:
            status_note = "SOS AKTIF!"
        elif fall:
            status_note = "Indikasi Jatuh"
        elif not finger:
            status_note = "Lepas Jari"
        print(f"{ts_clean:<20} | {bpm:<6.1f} | {spo2:<5.1f}% | {finger_str:<6} | {mag:<10.2f} | {status_note}")
    print("-" * 72)

def show_recent_alerts(conn, limit=5):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT created_at, alert_type, urgency, title, description
        FROM alerts
        ORDER BY id DESC
        LIMIT {limit}
    """)
    rows = cur.fetchall()
    print(f"\n🚨 {limit} EVENT / ALARM TERAKHIR:")
    print(f"{'Waktu':<20} | {'Jenis Alert':<16} | {'Urgensi':<10} | {'Judul'}")
    print("-" * 72)
    for r in rows:
        ts, alert_type, urg, title, desc = r
        ts_clean = ts[:19] if ts else "-"
        print(f"{ts_clean:<20} | {alert_type:<16} | {urg:<10} | {title}")
    print("-" * 72)

def show_recent_notifications(conn, limit=5):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT sent_at, channel, status, recipients_label, message_id_label
        FROM notification_logs
        ORDER BY id DESC
        LIMIT {limit}
    """)
    rows = cur.fetchall()
    print(f"\n📲 {limit} LOG NOTIFIKASI TELEGRAM TERAKHIR:")
    print(f"{'Waktu':<20} | {'Kanal':<10} | {'Status':<10} | {'Penerima / Label'}")
    print("-" * 72)
    for r in rows:
        ts, ch, st, recip, msg_lbl = r
        ts_clean = ts[:19] if ts else "-"
        detail = f"{recip or '-'} ({msg_lbl or '-'})"
        print(f"{ts_clean:<20} | {ch:<10} | {st:<10} | {detail}")
    print("-" * 72)

def export_to_csv(conn, filename="telemetry_export.csv"):
    cur = conn.cursor()
    cur.execute("SELECT * FROM telemetry ORDER BY id ASC")
    rows = cur.fetchall()
    col_names = [description[0] for description in cur.description]
    
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    with open(out_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(col_names)
        writer.writerows(rows)
    print(f"\n[✓] Berhasil mengekspor {len(rows)} baris data telemetri ke file CSV:")
    print(f"    -> {out_path}")
    print("    File ini bisa langsung dibuka di Microsoft Excel, Google Sheets, atau LibreOffice Calc!")

def main():
    parser = argparse.ArgumentParser(description="BioPulse Care SQLite Database Viewer")
    parser.add_argument("--export", action="store_true", help="Ekspor seluruh data telemetri ke file CSV")
    parser.add_argument("--limit", type=int, default=5, help="Jumlah baris data terakhir yang ingin ditampilkan (default: 5)")
    args = parser.parse_args()

    print_banner()
    conn = sqlite3.connect(DB_PATH)
    try:
        get_counts(conn)
        show_recent_telemetry(conn, limit=args.limit)
        show_recent_alerts(conn, limit=args.limit)
        show_recent_notifications(conn, limit=args.limit)
        if args.export:
            export_to_csv(conn)
        else:
            print("\n💡 Tips:")
            print("  • Tampilkan 15 data terakhir : python3 view_database.py --limit 15")
            print("  • Ekspor semua data ke Excel : python3 view_database.py --export")
            print("  • Buka interaktif via SQLite : sqlite3 biopulse.db")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
