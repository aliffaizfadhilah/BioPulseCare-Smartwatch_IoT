import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  acknowledgeAlert,
  fetchAlerts,
  fetchDashboardSummary,
  sendDeviceCommand,
  sendTelegramTest,
  simulateHardwareEvent,
} from "./services/api";
import { useDashboardSocket } from "./hooks/useDashboardSocket";

export default function App() {
  const [deviceId] = useState("bp-device-001");
  const [summary, setSummary] = useState(null);
  const [activeTab, setActiveTab] = useState("events"); // "events" | "vitals"
  const [category, setCategory] = useState("Semua Event");
  const [searchQ, setSearchQ] = useState("");
  const [toastMsg, setToastMsg] = useState("");
  const [selectedAlert, setSelectedAlert] = useState(null);

  const showToast = useCallback((msg) => {
    setToastMsg(msg);
    window.setTimeout(() => setToastMsg(""), 4000);
  }, []);

  const loadData = useCallback(async () => {
    try {
      const data = await fetchDashboardSummary(deviceId, category, searchQ);
      setSummary(data);
    } catch {
      showToast("Gagal memuat ringkasan dari backend lokal.");
    }
  }, [deviceId, category, searchQ, showToast]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleWsEvent = useCallback(
    (msg) => {
      if (!msg || !msg.event) return;
      loadData();
      if (msg.event === "alert" && msg.data?.alert) {
        showToast(`Event baru: ${msg.data.alert.title}`);
      }
    },
    [loadData, showToast]
  );

  const wsConnected = useDashboardSocket(handleWsEvent);

  const handleFilterChange = async (newCat, newQ) => {
    setCategory(newCat);
    setSearchQ(newQ);
    try {
      const alertsResp = await fetchAlerts(deviceId, newCat, newQ);
      setSummary((prev) => (prev ? { ...prev, alerts: alertsResp } : prev));
    } catch {
      // Handled by next refresh
    }
  };

  const handleCommand = async (cmd) => {
    try {
      const res = await sendDeviceCommand(deviceId, cmd, 3000);
      showToast(`Perintah '${res.command}' dikirim ke topik ${res.topic}`);
      loadData();
    } catch {
      showToast("Gagal mengirim perintah ke perangkat.");
    }
  };

  const handleTelegramTest = async () => {
    try {
      const res = await sendTelegramTest(deviceId);
      showToast(`Uji Telegram: ${res.notification.status_label}`);
      loadData();
    } catch {
      showToast("Gagal mengirim uji notifikasi Telegram.");
    }
  };

  const handleAcknowledge = async (alertId) => {
    try {
      await acknowledgeAlert(deviceId, alertId);
      showToast("Event ditandai selesai ditinjau.");
      setSelectedAlert(null);
      loadData();
    } catch {
      showToast("Gagal memperbarui status event.");
    }
  };

  const handleSimulate = async (type) => {
    try {
      await simulateHardwareEvent(deviceId, type);
      showToast(`Simulasi hardware '${type.toUpperCase()}' berhasil dijalankan.`);
      loadData();
    } catch {
      showToast("Gagal menjalankan simulasi.");
    }
  };

  const device = summary?.device || {
    device_id: "bp-device-001",
    patient_name: "Bpk. Soedirman",
    patient_relation: "Ayah",
    status: "online",
    battery_pct: 88,
    last_bpm: 78,
    last_spo2: 98,
    last_accel_mag: 9.8,
    sos_active: false,
    fall_candidate: false,
  };

  const isOffline = device.status !== "online";
  const hasEmergency = Boolean(device.sos_active || device.fall_candidate);

  const chartPoints = useMemo(() => {
    const series = summary?.telemetry_series || [];
    if (isOffline || !series.length) {
      return {
        isReset: true,
        poly: "0,92 800,92",
        area: "0,100 0,92 800,92 800,100",
      };
    }
    const ptsList = series.length === 1 ? [series[0], series[0]] : series;
    const step = 800 / Math.max(1, ptsList.length - 1);
    const pts = ptsList.map((pt, i) => {
      const x = Math.round(i * step);
      const bpm = Number(pt.bpm || 78);
      const y = Math.max(15, Math.min(88, Math.round(100 - ((bpm - 50) / 80) * 70)));
      return `${x},${y}`;
    });
    const poly = pts.join(" ");
    return { isReset: false, poly, area: `0,100 ${poly} 800,100` };
  }, [summary, isOffline]);

  const alertsList = summary?.alerts?.items || [];
  const vitalsList = summary?.telemetry_history?.items || [];

  return (
    <div className="bg-surface font-body-md text-on-surface min-h-screen">
      {/* Header (Tanpa duplikasi badge status yang sudah ada di Hero Card) */}
      <header className="fixed top-0 right-0 left-0 h-16 bg-surface-container-lowest/90 backdrop-blur-xl shadow-[0_1px_8px_rgba(0,0,0,0.04)] z-40 px-space-md flex items-center justify-between">
        <div className="flex items-center gap-space-md">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[28px]">vital_signs</span>
            <span className="text-headline-md text-primary font-bold tracking-tight">BioPulse</span>
          </div>
          <div className="hidden sm:flex items-center gap-2 px-3 py-1 bg-surface-container rounded-full text-on-surface text-label-md">
            <span className="material-symbols-outlined text-primary text-[18px]">person</span>
            <span>
              {device.patient_relation}: <strong>{device.patient_name}</strong>
            </span>
          </div>
        </div>

        <div className="flex items-center gap-space-md">
          <span className="hidden lg:inline-flex items-center gap-1.5 text-label-sm px-2.5 py-1 rounded-full bg-surface-container-low text-on-surface-variant">
            <span
              className={`w-2 h-2 rounded-full ${wsConnected ? "bg-secondary" : "bg-tertiary"}`}
            />
            {wsConnected ? "Sinkronisasi Real-time Aktif" : "Menyambung..."}
          </span>
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-full bg-primary text-white flex items-center justify-center font-bold text-label-md">
              SR
            </div>
            <div className="hidden md:flex flex-col text-left">
              <span className="text-label-md text-on-surface font-semibold leading-tight">
                Ibu Siti Rahayu
              </span>
              <span className="text-[11px] text-on-surface-variant leading-tight">
                Keluarga / Anak
              </span>
            </div>
          </div>
        </div>
      </header>

      {toastMsg ? (
        <div className="fixed bottom-5 right-5 z-50 bg-inverse-surface text-inverse-on-surface px-4 py-3 rounded-xl shadow-lg text-body-sm flex items-center gap-2">
          <span className="material-symbols-outlined text-[18px] text-primary-fixed">info</span>
          <span>{toastMsg}</span>
        </div>
      ) : null}

      <main className="w-full pt-20 bg-surface min-h-screen p-space-md lg:p-space-lg">
        <div className="flex flex-col w-full gap-space-lg max-w-7xl mx-auto">
          {/* 1. Hero Card (Tanpa tombol Kirim Suara) */}
          <section className="w-full bg-surface-container-lowest rounded-2xl shadow-sm p-space-lg flex flex-col md:flex-row md:items-center justify-between gap-space-md border border-secondary-fixed/50">
            <div className="flex flex-col gap-2 max-w-2xl">
              <div className="flex flex-wrap items-center gap-2">
                <div
                  className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full ${
                    isOffline
                      ? "bg-surface-container-high text-on-surface-variant"
                      : hasEmergency
                      ? "bg-[#fee2e2] text-[#b91a24]"
                      : "bg-secondary-fixed/50 text-on-secondary-container"
                  }`}
                >
                  <span
                    className={`w-2 h-2 rounded-full ${
                      isOffline ? "bg-outline" : hasEmergency ? "bg-tertiary" : "bg-secondary"
                    }`}
                  />
                  <span className="text-label-sm font-semibold">
                    {isOffline
                      ? "Perangkat Offline"
                      : hasEmergency
                      ? "Peringatan Awal Aktif"
                      : "Kondisi Sehat & Aman"}
                  </span>
                </div>
                <span className="inline-flex items-center gap-1 text-[12px] text-on-surface-variant/80 bg-surface-container-low px-2.5 py-0.5 rounded-full">
                  <span className="material-symbols-outlined text-[14px] text-primary">info</span>
                  <span>Indikasi & Peringatan Awal (Bukan Diagnosis Medis)</span>
                </span>
              </div>

              <h1 className="text-headline-lg text-on-surface tracking-tight font-bold">
                {isOffline
                  ? "Perangkat sedang offline. Silakan periksa daya gelang dan lakukan pengecekan langsung."
                  : device.sos_active
                  ? "Peringatan Awal: Tombol Darurat SOS ditekan pada gelang Ayah!"
                  : device.fall_candidate
                  ? "Peringatan Awal: Terdeteksi indikasi / dugaan jatuh dari sensor gerak!"
                  : "Alhamdulillah, kondisi Ayah hari ini terpantau sehat dan beristirahat nyaman."}
              </h1>
              <div className="flex flex-wrap items-center gap-4 text-on-surface-variant text-label-md pt-1">
                <span className="inline-flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[18px] text-secondary">
                    battery_charging_full
                  </span>
                  Baterai Gelang {device.battery_pct}%
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[18px] text-primary">wifi</span>
                  {isOffline ? "Gelang Terputus (Offline)" : "Gelang Terhubung"}
                </span>
              </div>
            </div>

            <div className="flex flex-row sm:flex-col gap-space-xs min-w-[210px]">
              <button
                type="button"
                onClick={() => handleCommand("buzzer")}
                className="inline-flex items-center justify-center gap-2 px-5 py-3.5 rounded-xl bg-primary text-on-primary text-label-md shadow-sm hover:opacity-90 transition-all"
              >
                <span className="material-symbols-outlined text-[20px]">ring_volume</span>
                <span>Bunyikan Gelang</span>
              </button>
              {hasEmergency ? (
                <button
                  type="button"
                  onClick={() => handleCommand("reset_alarm")}
                  className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-[#fee2e2] text-[#b91a24] text-label-md font-semibold"
                >
                  <span className="material-symbols-outlined text-[18px]">restart_alt</span>
                  <span>Matikan Alarm</span>
                </button>
              ) : null}
            </div>
          </section>

          {/* 2. Three Metric Cards */}
          <section className="grid grid-cols-1 md:grid-cols-3 gap-space-md">
            <div className="bg-surface-container-lowest rounded-2xl p-space-lg shadow-sm flex flex-col justify-between border border-surface-container-high/40">
              <div className="flex items-center justify-between">
                <span className="text-label-md text-on-surface-variant font-medium">
                  Detak Jantung
                </span>
                <div className="w-10 h-10 rounded-full bg-tertiary-fixed flex items-center justify-center text-tertiary">
                  <span className="material-symbols-outlined text-[22px]">favorite</span>
                </div>
              </div>
              <div className="my-space-md">
                <div className="flex items-baseline gap-2">
                  <span className="text-[2.75rem] leading-[3rem] text-on-surface font-bold">
                    {isOffline ? "--" : device.last_bpm}
                  </span>
                  <span className="text-label-md text-on-surface-variant font-semibold">BPM</span>
                </div>
              </div>
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-secondary-fixed/50 text-on-secondary-container text-label-sm font-semibold self-start">
                <span className="material-symbols-outlined text-[16px]">check</span>
                <span>{isOffline ? "Menunggu Koneksi" : "Normal & Tenang"}</span>
              </div>
            </div>

            <div className="bg-surface-container-lowest rounded-2xl p-space-lg shadow-sm flex flex-col justify-between border border-surface-container-high/40">
              <div className="flex items-center justify-between">
                <span className="text-label-md text-on-surface-variant font-medium">
                  Kadar Oksigen (SpO2)
                </span>
                <div className="w-10 h-10 rounded-full bg-primary-fixed flex items-center justify-center text-primary">
                  <span className="material-symbols-outlined text-[22px]">air</span>
                </div>
              </div>
              <div className="my-space-md">
                <div className="flex items-baseline gap-1">
                  <span className="text-[2.75rem] leading-[3rem] text-on-surface font-bold">
                    {isOffline ? "--" : device.last_spo2}
                  </span>
                  <span className="text-headline-md text-on-surface-variant font-semibold">%</span>
                </div>
              </div>
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-secondary-fixed/50 text-on-secondary-container text-label-sm font-semibold self-start">
                <span className="material-symbols-outlined text-[16px]">done_all</span>
                <span>{isOffline ? "Menunggu Koneksi" : "Saturasi Optimal"}</span>
              </div>
            </div>

            <div className="bg-surface-container-lowest rounded-2xl p-space-lg shadow-sm flex flex-col justify-between border border-secondary-fixed/50 bg-secondary-fixed/10">
              <div className="flex items-center justify-between">
                <span className="text-label-md text-on-surface-variant font-medium">
                  Status Gerak & Postur
                </span>
                <div className="w-10 h-10 rounded-full bg-secondary-fixed flex items-center justify-center text-secondary">
                  <span className="material-symbols-outlined text-[22px]">shield</span>
                </div>
              </div>
              <div className="my-space-md">
                <span className="text-[2rem] leading-tight text-secondary font-bold block">
                  {isOffline
                    ? "--"
                    : device.fall_candidate
                    ? "Dugaan Jatuh"
                    : device.sos_active
                    ? "SOS Aktif"
                    : "Aman"}
                </span>
                <span className="text-body-sm text-on-surface-variant">
                  {isOffline
                    ? "Menunggu Sinyal Sensor"
                    : device.fall_candidate
                    ? `Lonjakan |a|=${device.last_accel_mag} m/s²`
                    : "Tidak Terdeteksi Jatuh"}
                </span>
              </div>
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-secondary text-on-secondary text-label-sm font-semibold self-start">
                <span className="material-symbols-outlined text-[16px]">sensors</span>
                <span>MPU6050 Aktif</span>
              </div>
            </div>
          </section>

          {/* 3. Trend Chart Section (Ke-reset Setelah Offline) */}
          <section className="bg-surface-container-lowest rounded-2xl p-space-lg shadow-sm flex flex-col gap-space-md border border-surface-container-high/40">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[22px]">
                  show_chart
                </span>
                <h2 className="text-headline-md text-on-surface font-semibold">
                  Grafik Tren Hari Ini
                </h2>
                <span className="text-label-sm text-secondary font-medium ml-2 px-2.5 py-0.5 rounded-full bg-secondary-fixed/30">
                  {chartPoints.isReset ? "Di-reset (Setelah Offline)" : "Stabil & Normal"}
                </span>
              </div>
              <div className="flex items-center gap-2 text-label-sm">
                <button
                  type="button"
                  onClick={() => handleSimulate("telemetry")}
                  className="px-2.5 py-1 rounded-lg bg-surface-container text-primary font-semibold"
                >
                  + Simulasi Data
                </button>
                <button
                  type="button"
                  onClick={() => handleSimulate("fall")}
                  className="px-2.5 py-1 rounded-lg bg-[#fee2e2] text-[#b91a24] font-semibold"
                >
                  Uji Jatuh
                </button>
                <button
                  type="button"
                  onClick={() => handleSimulate(isOffline ? "online" : "offline")}
                  className="px-2.5 py-1 rounded-lg bg-surface-container-high text-on-surface font-semibold"
                >
                  {isOffline ? "Pulihkan Online" : "Uji Offline LWT"}
                </button>
              </div>
            </div>

            <div className="w-full h-32 relative bg-surface-container-low/40 rounded-xl p-2 overflow-hidden">
              {chartPoints.isReset ? (
                <div className="absolute inset-0 z-10 flex items-center justify-center bg-surface-container-low/75">
                  <span className="text-body-sm text-on-surface-variant font-medium px-3 py-1.5 rounded-full bg-white shadow-sm">
                    Grafik tren telah di-reset setelah perangkat offline. Menunggu data baru...
                  </span>
                </div>
              ) : null}
              <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 800 100">
                <defs>
                  <linearGradient id="calmTrendFill" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="#0ea5e9" stopOpacity="0.18" />
                    <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0.0" />
                  </linearGradient>
                </defs>
                <polygon fill="url(#calmTrendFill)" points={chartPoints.area} />
                <polyline
                  fill="none"
                  points={chartPoints.poly}
                  stroke="#006591"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="3"
                />
              </svg>
            </div>
          </section>

          {/* 4. Two-Tab Section: Log Event & Riwayat Detak Jantung + SpO2 */}
          <section className="w-full bg-surface-container-lowest rounded-2xl p-space-lg shadow-sm flex flex-col gap-5 border border-surface-container-high/40">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-start gap-3">
                <div className="p-2 rounded-xl bg-surface-container-low text-primary flex items-center justify-center mt-0.5">
                  <span className="material-symbols-outlined text-[24px]">move_to_inbox</span>
                </div>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-headline-md text-on-surface font-bold tracking-tight">
                      Log Notifikasi Telegram & Riwayat Sensor
                    </h2>
                    <span className="px-2.5 py-0.5 rounded-full bg-surface-container text-primary text-[11px] font-semibold">
                      Auto-Reset Tampilan 3 Hari (Tersimpan di Database)
                    </span>
                  </div>
                  <p className="text-body-sm text-on-surface-variant mt-0.5">
                    Sinkronisasi otomatis bot{" "}
                    <span className="font-semibold text-primary">@BioPulseCare_smartwach_bot</span>{" "}
                    ke kanal darurat keluarga.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={handleTelegramTest}
                className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-[#004c6e] text-white text-label-md font-medium hover:bg-opacity-95 shadow-sm transition-all self-start sm:self-auto"
              >
                <span className="material-symbols-outlined text-[18px]">send</span>
                <span>Kirim Test Telegram</span>
              </button>
            </div>

            {/* 2-Tab Navigation */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-container-high/60 pb-3">
              <div className="inline-flex p-1 rounded-xl bg-surface-container-low border border-surface-container-high/50">
                <button
                  type="button"
                  onClick={() => setActiveTab("events")}
                  className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-label-sm font-semibold transition-all ${
                    activeTab === "events"
                      ? "bg-primary text-white shadow-sm"
                      : "text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  <span className="material-symbols-outlined text-[18px]">notifications</span>
                  <span>Log Event</span>
                  <span className="px-2 py-0.5 rounded-full bg-black/10 text-[11px]">
                    {summary?.alerts?.total || 0}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("vitals")}
                  className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-label-sm font-semibold transition-all ${
                    activeTab === "vitals"
                      ? "bg-primary text-white shadow-sm"
                      : "text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  <span className="material-symbols-outlined text-[18px]">monitor_heart</span>
                  <span>Riwayat Detak Jantung & Kadar Oksigen</span>
                  <span className="px-2 py-0.5 rounded-full bg-black/10 text-[11px]">
                    {summary?.telemetry_history?.total || 0}
                  </span>
                </button>
              </div>
              <span className="text-[12px] text-on-surface-variant">
                Menampilkan maks. 3 hari terakhir di dashboard (data lengkap tersimpan di database).
              </span>
            </div>

            {activeTab === "events" ? (
              <>
                <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4">
                  <div className="relative flex-1 max-w-lg">
                    <span className="material-symbols-outlined absolute left-3.5 top-1/2 -translate-y-1/2 text-on-surface-variant text-[20px]">
                      search
                    </span>
                    <input
                      type="text"
                      value={searchQ}
                      onChange={(e) => handleFilterChange(category, e.target.value)}
                      placeholder="Cari event, kata kunci, atau metrik..."
                      className="w-full pl-11 pr-4 py-2 bg-surface-container-low/50 hover:bg-surface-container-low focus:bg-white text-on-surface placeholder:text-on-surface-variant/70 border border-surface-container-high/60 rounded-xl text-body-sm outline-none transition-all focus:border-primary focus:ring-1 focus:ring-primary"
                    />
                  </div>
                  <div className="flex items-center gap-2 self-end md:self-auto">
                    <span className="text-body-sm text-on-surface-variant font-medium">
                      Kategori:
                    </span>
                    <select
                      value={category}
                      onChange={(e) => handleFilterChange(e.target.value, searchQ)}
                      className="bg-surface-container-low/50 border border-surface-container-high/60 text-on-surface text-body-sm rounded-xl px-3 py-2 outline-none cursor-pointer focus:border-primary transition-all"
                    >
                      <option value="Semua Event">
                        Semua Event ({summary?.alerts?.total || 0})
                      </option>
                      <option value="Urgensi Normal">Urgensi Normal</option>
                      <option value="Perhatian & Peringatan">Perhatian & Peringatan</option>
                      <option value="Status Daya">Status Daya</option>
                      <option value="Uji Sistem">Uji Sistem</option>
                    </select>
                  </div>
                </div>

                <div className="w-full overflow-x-auto">
                  <table className="w-full text-left border-collapse min-w-[760px]">
                    <thead>
                      <tr className="border-b border-surface-container-high/40 text-on-surface-variant text-label-sm uppercase tracking-wider">
                        <th className="py-3 px-3 font-semibold w-[120px]">Waktu (WIB)</th>
                        <th className="py-3 px-3 font-semibold w-[130px]">Tingkat Urgensi</th>
                        <th className="py-3 px-4 font-semibold">Deskripsi Telemetri Sensor</th>
                        <th className="py-3 px-4 font-semibold w-[220px]">
                          Status Pengiriman Telegram
                        </th>
                        <th className="py-3 px-3 text-right font-semibold w-[90px]">Aksi</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-container-high/40 text-on-surface text-body-sm">
                      {alertsList.map((item) => (
                        <tr
                          key={item.id}
                          className="hover:bg-surface-container-low/30 transition-colors"
                        >
                          <td className="py-3.5 px-3 align-top whitespace-nowrap">
                            <div className="font-semibold text-on-surface">{item.time_wib}</div>
                            <div className="text-[11px] text-on-surface-variant">
                              {item.day_label}
                            </div>
                          </td>
                          <td className="py-3.5 px-3 align-top">
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-container text-on-surface text-label-sm font-semibold">
                              {item.urgency}
                            </span>
                          </td>
                          <td className="py-3.5 px-4 align-top">
                            <div className="font-semibold text-on-surface">{item.title}</div>
                            <div className="text-on-surface-variant text-body-sm mt-0.5">
                              {item.description}
                            </div>
                          </td>
                          <td className="py-3.5 px-4 align-top">
                            <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-[#dcfce7] text-[#15803d] text-[12px] font-medium">
                              <span className="material-symbols-outlined text-[15px]">
                                done_all
                              </span>
                              <span>{item.telegram_status_label || "Terkirim ke Telegram"}</span>
                            </div>
                            <div className="text-on-surface-variant text-[11px] mt-1">
                              {item.recipients_label}
                            </div>
                          </td>
                          <td className="py-3.5 px-3 align-top text-right">
                            {item.acknowledged ? (
                              <span className="inline-flex items-center gap-1 text-secondary text-label-sm font-semibold">
                                <span className="material-symbols-outlined text-[16px]">
                                  check_circle
                                </span>
                                <span>Selesai</span>
                              </span>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setSelectedAlert(item)}
                                className="px-3 py-1 rounded-lg bg-surface-container hover:bg-surface-container-high text-primary text-label-sm font-medium transition-colors"
                              >
                                {item.action_type || "Detail"}
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div className="w-full overflow-x-auto">
                <table className="w-full text-left border-collapse min-w-[700px]">
                  <thead>
                    <tr className="border-b border-surface-container-high/40 text-on-surface-variant text-label-sm uppercase tracking-wider">
                      <th className="py-3 px-3 font-semibold w-[140px]">Waktu (WIB)</th>
                      <th className="py-3 px-4 font-semibold">Detak Jantung (BPM)</th>
                      <th className="py-3 px-4 font-semibold">Kadar Oksigen (SpO2)</th>
                      <th className="py-3 px-4 font-semibold">Kontak Jari (MAX30102)</th>
                      <th className="py-3 px-4 font-semibold">Akselerasi Gerak</th>
                      <th className="py-3 px-3 text-right font-semibold">Status Indikasi</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-container-high/40 text-on-surface text-body-sm">
                    {vitalsList.map((row) => (
                      <tr
                        key={row.id}
                        className="hover:bg-surface-container-low/30 transition-colors"
                      >
                        <td className="py-3 px-3 whitespace-nowrap">
                          <div className="font-semibold text-on-surface">{row.time_wib}</div>
                          <div className="text-[11px] text-on-surface-variant">{row.day_label}</div>
                        </td>
                        <td className="py-3 px-4 font-bold">
                          {row.bpm > 0 ? `${row.bpm} BPM` : "-- BPM"}
                        </td>
                        <td className="py-3 px-4 font-bold text-primary">
                          {row.spo2 > 0 ? `${row.spo2} %` : "-- %"}
                        </td>
                        <td className="py-3 px-4">
                          {row.finger_detected ? "Terdeteksi" : "Jari Tidak Ada"}
                        </td>
                        <td className="py-3 px-4 text-on-surface-variant">
                          {Number(row.accel_mag || 9.8).toFixed(2)} m/s²
                        </td>
                        <td className="py-3 px-3 text-right">
                          {row.sos_active
                            ? "Darurat SOS"
                            : row.fall_candidate
                            ? "Dugaan Jatuh"
                            : "Stabil & Normal"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </main>

      {selectedAlert ? (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl flex flex-col gap-4">
            <h3 className="text-headline-md font-bold text-on-surface">{selectedAlert.title}</h3>
            <p className="text-body-sm text-on-surface-variant">{selectedAlert.description}</p>
            <div className="text-label-sm text-on-surface-variant bg-surface-container-low p-3 rounded-xl">
              <div>
                Waktu: {selectedAlert.time_wib} ({selectedAlert.day_label})
              </div>
              <div>Metode Deteksi: {selectedAlert.detection_method}</div>
              <div>Telegram: {selectedAlert.telegram_status_label}</div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setSelectedAlert(null)}
                className="px-4 py-2 rounded-xl bg-surface-container text-on-surface text-label-md"
              >
                Tutup
              </button>
              <button
                type="button"
                onClick={() => handleAcknowledge(selectedAlert.id)}
                className="px-4 py-2 rounded-xl bg-primary text-white text-label-md"
              >
                Tandai Selesai Ditinjau
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
