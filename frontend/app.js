/**
 * BioPulse Care — Interactive Dashboard Controller (Stitch Screen 24d7fead204a471b94161244d0508be0)
 * Enforces strict DOM safety: uses only document.createElement() and textContent (no innerHTML / alert).
 */
(function () {
  "use strict";

  const DEVICE_ID = "bp-device-001";
  let currentCategory = "Semua Event";
  let currentSearch = "";
  let activeModalAlert = null;
  let toastTimeout = null;
  let currentDeviceStatus = "online";

  function el(id) {
    return document.getElementById(id);
  }

  function showToast(message) {
    const box = el("toast-box");
    const text = el("toast-text");
    if (!box || !text) return;
    text.textContent = message;
    box.classList.remove("hidden");
    box.classList.add("flex");
    if (toastTimeout) window.clearTimeout(toastTimeout);
    toastTimeout = window.setTimeout(() => {
      box.classList.add("hidden");
      box.classList.remove("flex");
    }, 4000);
  }

  function createIconSpan(iconName, extraClasses) {
    const span = document.createElement("span");
    span.className = "material-symbols-outlined " + (extraClasses || "");
    span.textContent = iconName;
    return span;
  }

  function renderUrgencyBadge(urgency) {
    const badge = document.createElement("span");
    if (urgency === "Normal") {
      badge.className =
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-secondary-fixed/50 text-on-secondary-container font-label-sm text-label-sm font-semibold";
      const dot = document.createElement("span");
      dot.className = "w-1.5 h-1.5 rounded-full bg-secondary";
      badge.appendChild(dot);
      badge.appendChild(document.createTextNode(" Normal"));
    } else if (urgency === "Info Daya") {
      badge.className =
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary-fixed text-on-primary-container font-label-sm text-label-sm font-semibold";
      badge.appendChild(createIconSpan("info", "text-[15px]"));
      badge.appendChild(document.createTextNode(" Info Daya"));
    } else if (urgency === "Perhatian") {
      badge.className =
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#fee2e2] text-[#b91a24] font-label-sm text-label-sm font-semibold";
      badge.appendChild(createIconSpan("warning", "text-[15px]"));
      badge.appendChild(document.createTextNode(" Perhatian"));
    } else if (urgency === "Daya Rendah") {
      badge.className =
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm font-semibold";
      badge.appendChild(createIconSpan("battery_alert", "text-[15px]"));
      badge.appendChild(document.createTextNode(" Daya Rendah"));
    } else {
      badge.className =
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-container-high text-primary font-label-sm text-label-sm font-semibold";
      badge.appendChild(createIconSpan("build", "text-[15px]"));
      badge.appendChild(document.createTextNode(" " + urgency));
    }
    return badge;
  }

  function renderTelegramStatusCell(item) {
    const wrapper = document.createElement("div");
    const pill = document.createElement("div");

    const tone = item.telegram_badge_tone || "green";
    let colorClass = "bg-[#dcfce7] text-[#15803d]";
    if (tone === "blue") colorClass = "bg-[#e0f2fe] text-[#0369a1]";
    else if (tone === "amber") colorClass = "bg-[#fef3c7] text-[#b45309]";
    else if (tone === "red") colorClass = "bg-[#fee2e2] text-[#b91a24]";

    pill.className =
      "inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full font-label-sm text-[12px] font-medium " +
      colorClass;
    pill.appendChild(createIconSpan("done_all", "text-[15px]"));

    const labelSpan = document.createElement("span");
    labelSpan.textContent = item.telegram_status_label || "Terkirim ke Telegram";
    pill.appendChild(labelSpan);

    const sub = document.createElement("div");
    sub.className = "text-on-surface-variant text-[11px] mt-1";
    sub.textContent = item.recipients_label || "Kanal Darurat Keluarga";

    wrapper.appendChild(pill);
    wrapper.appendChild(sub);
    return wrapper;
  }

  function renderEventTable(alertsData) {
    const tbody = el("event-table-body");
    if (!tbody) return;
    tbody.replaceChildren();

    const optAll = el("opt-all-events");
    if (optAll && typeof alertsData.total === "number") {
      optAll.textContent = "Semua Event (" + alertsData.total + ")";
    }

    const items = alertsData.items || [];
    if (items.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 5;
      td.className = "py-6 text-center text-on-surface-variant";
      td.textContent = "Tidak ada event yang sesuai dengan filter pencarian.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    items.forEach((item) => {
      const tr = document.createElement("tr");
      tr.className = "hover:bg-surface-container-low/30 transition-colors";

      // 1. Waktu (WIB)
      const tdTime = document.createElement("td");
      tdTime.className = "py-3.5 px-3 align-top whitespace-nowrap";
      const timeMain = document.createElement("div");
      timeMain.className = "font-semibold text-on-surface";
      timeMain.textContent = item.time_wib || "10:42:00";
      const timeSub = document.createElement("div");
      timeSub.className = "text-[11px] text-on-surface-variant";
      timeSub.textContent = item.day_label || "Hari Ini";
      tdTime.appendChild(timeMain);
      tdTime.appendChild(timeSub);

      // 2. Tingkat Urgensi
      const tdUrg = document.createElement("td");
      tdUrg.className = "py-3.5 px-3 align-top";
      tdUrg.appendChild(renderUrgencyBadge(item.urgency || "Normal"));

      // 3. Deskripsi Telemetri Sensor
      const tdDesc = document.createElement("td");
      tdDesc.className = "py-3.5 px-4 align-top";
      const titleDiv = document.createElement("div");
      titleDiv.className = "font-semibold text-on-surface";
      titleDiv.textContent = item.title || "";
      const bodyDiv = document.createElement("div");
      bodyDiv.className = "text-on-surface-variant text-body-sm mt-0.5";
      bodyDiv.textContent = item.description || "";
      tdDesc.appendChild(titleDiv);
      tdDesc.appendChild(bodyDiv);

      // 4. Status Pengiriman Telegram
      const tdTg = document.createElement("td");
      tdTg.className = "py-3.5 px-4 align-top";
      tdTg.appendChild(renderTelegramStatusCell(item));

      // 5. Aksi
      const tdAct = document.createElement("td");
      tdAct.className = "py-3.5 px-3 align-top text-right";
      if (item.acknowledged && item.action_type === "Selesai") {
        const doneSpan = document.createElement("span");
        doneSpan.className =
          "inline-flex items-center gap-1 text-secondary font-label-md text-label-sm font-semibold";
        doneSpan.appendChild(createIconSpan("check_circle", "text-[16px]"));
        const sText = document.createElement("span");
        sText.textContent = "Selesai";
        doneSpan.appendChild(sText);
        tdAct.appendChild(doneSpan);
      } else {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className =
          "px-3 py-1 rounded-lg bg-surface-container hover:bg-surface-container-high text-primary font-label-md text-label-sm font-medium transition-colors";
        btn.textContent = item.action_type || "Detail";
        btn.addEventListener("click", () => openEventModal(item));
        tdAct.appendChild(btn);
      }

      tr.appendChild(tdTime);
      tr.appendChild(tdUrg);
      tr.appendChild(tdDesc);
      tr.appendChild(tdTg);
      tr.appendChild(tdAct);
      tbody.appendChild(tr);
    });
  }

  function renderDeviceHeroAndCards(device, series) {
    if (!device) return;
    currentDeviceStatus = device.status || "online";
    const isOffline = currentDeviceStatus !== "online";
    const hasEmergency = Boolean(device.sos_active || device.fall_candidate);

    const patientEl = el("hdr-patient-name");
    if (patientEl) patientEl.textContent = device.patient_name || "Bpk. Soedirman";

    const statusPill = el("hdr-status-pill");
    const statusDot = el("hdr-status-dot");
    const statusText = el("hdr-status-text");
    if (statusPill && statusDot && statusText) {
      if (isOffline) {
        statusPill.className =
          "inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-surface-container-high text-on-surface-variant";
        statusDot.className = "w-2 h-2 rounded-full bg-outline";
        statusText.textContent = "Perangkat Offline";
      } else if (hasEmergency) {
        statusPill.className =
          "inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#fee2e2] text-[#b91a24]";
        statusDot.className = "w-2 h-2 rounded-full bg-tertiary";
        statusText.textContent = "Peringatan Awal Aktif";
      } else {
        statusPill.className =
          "inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-secondary-fixed/50 text-on-secondary-container";
        statusDot.className = "w-2 h-2 rounded-full bg-secondary";
        statusText.textContent = "Kondisi Sehat & Aman";
      }
    }

    const headline = el("hero-headline");
    if (headline) {
      if (isOffline) {
        headline.textContent =
          "Perangkat BioPulse Care terdeteksi offline. Silakan periksa koneksi gelang dan kondisi Ayah secara langsung.";
      } else if (device.sos_active) {
        headline.textContent =
          "Peringatan Awal: Tombol Darurat SOS ditekan pada gelang Ayah! Segera lakukan pengecekan.";
      } else if (device.fall_candidate) {
        headline.textContent =
          "Peringatan Awal: Terdeteksi indikasi / dugaan jatuh dari sensor gerak MPU6050!";
      } else {
        headline.textContent =
          "Alhamdulillah, kondisi Ayah hari ini terpantau sehat dan beristirahat nyaman.";
      }
    }

    const batEl = el("hero-battery");
    if (batEl) batEl.textContent = "Baterai Gelang " + (device.battery_pct ?? 88) + "%";

    const connEl = el("hero-conn-text");
    if (connEl) {
      connEl.textContent = isOffline ? "Gelang Terputus (Offline)" : "Gelang Terhubung";
    }

    const btnSimOffline = el("btn-sim-offline");
    if (btnSimOffline) {
      btnSimOffline.textContent = isOffline ? "Pulihkan Online" : "Uji Offline LWT";
    }

    const resetBtn = el("btn-reset-alarm");
    if (resetBtn) {
      if (hasEmergency) {
        resetBtn.classList.remove("hidden");
        resetBtn.classList.add("inline-flex");
      } else {
        resetBtn.classList.add("hidden");
        resetBtn.classList.remove("inline-flex");
      }
    }

    // Vital cards
    const valBpm = el("val-bpm");
    if (valBpm) valBpm.textContent = isOffline ? "--" : String(device.last_bpm ?? 78);
    const badgeBpmText = el("badge-bpm-text");
    if (badgeBpmText) {
      badgeBpmText.textContent = isOffline
        ? "Perangkat Offline"
        : !device.finger_detected
        ? "Tempelkan Jari (Estimasi Terakhir)"
        : "Normal & Tenang";
    }

    const valSpo2 = el("val-spo2");
    if (valSpo2) valSpo2.textContent = isOffline ? "--" : String(device.last_spo2 ?? 98);
    const badgeSpo2Text = el("badge-spo2-text");
    if (badgeSpo2Text) {
      badgeSpo2Text.textContent = isOffline ? "Perangkat Offline" : "Sangat Baik";
    }

    const valPosture = el("val-posture");
    const subPosture = el("sub-posture");
    if (valPosture && subPosture) {
      if (device.sos_active) {
        valPosture.textContent = "SOS Aktif";
        valPosture.className =
          "font-metric-numeral text-headline-lg text-tertiary font-bold block leading-tight";
        subPosture.textContent = "Tombol darurat ditekan >=2 detik";
      } else if (device.fall_candidate) {
        valPosture.textContent = "Dugaan Jatuh";
        valPosture.className =
          "font-metric-numeral text-headline-lg text-tertiary font-bold block leading-tight";
        subPosture.textContent = "Lonjakan percepatan " + (device.last_accel_mag ?? 22.5) + " m/s²";
      } else {
        valPosture.textContent = "Aman";
        valPosture.className =
          "font-metric-numeral text-headline-lg text-secondary font-bold block leading-tight";
        subPosture.textContent = "Tidak Terdeteksi Jatuh";
      }
    }

    // Update SVG Trend Chart
    if (Array.isArray(series) && series.length >= 2) {
      const step = 800 / Math.max(1, series.length - 1);
      const coords = series.map((pt, idx) => {
        const x = Math.round(idx * step);
        const bpm = Number(pt.bpm || 78);
        const y = Math.max(15, Math.min(88, Math.round(100 - ((bpm - 50) / 80) * 70)));
        return { x, y };
      });
      const polyStr = coords.map((c) => c.x + "," + c.y).join(" ");
      const areaStr = "0,100 " + polyStr + " 800,100";

      const polyEl = el("trend-polyline");
      const areaEl = el("trend-polygon");
      if (polyEl) polyEl.setAttribute("points", polyStr);
      if (areaEl) areaEl.setAttribute("points", areaStr);

      const mid = coords[Math.floor(coords.length / 2)];
      const last = coords[coords.length - 1];
      const dotMid = el("trend-dot-mid");
      const dotEnd = el("trend-dot-end");
      if (dotMid && mid) {
        dotMid.setAttribute("cx", String(mid.x));
        dotMid.setAttribute("cy", String(mid.y));
      }
      if (dotEnd && last) {
        dotEnd.setAttribute("cx", String(last.x));
        dotEnd.setAttribute("cy", String(last.y));
      }
    }

    const nowLabel = el("trend-now-label");
    if (nowLabel && device.last_seen_wib) {
      nowLabel.textContent = "Sekarang (" + device.last_seen_wib.replace(" WIB", "") + ")";
    }
  }

  function openEventModal(alertItem) {
    activeModalAlert = alertItem;
    const modal = el("event-modal");
    if (!modal) return;
    el("modal-title").textContent = alertItem.title || "Detail Event";
    el("modal-desc").textContent = alertItem.description || "";
    el("modal-meta-time").textContent =
      "Waktu Kejadian: " + (alertItem.time_wib || "") + " WIB (" + (alertItem.day_label || "") + ")";
    el("modal-meta-method").textContent =
      "Metode Evaluasi: " + (alertItem.detection_method || "Rule-Based");
    el("modal-meta-telegram").textContent =
      "Status Telegram: " +
      (alertItem.telegram_status_label || "Terkirim") +
      " — " +
      (alertItem.recipients_label || "");

    modal.classList.remove("hidden");
    modal.classList.add("flex");
  }

  function closeEventModal() {
    activeModalAlert = null;
    const modal = el("event-modal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }

  async function refreshDashboard() {
    try {
      const params = new URLSearchParams({
        device_id: DEVICE_ID,
        category: currentCategory,
        q: currentSearch,
      });
      const res = await fetch("/api/dashboard/summary?" + params.toString(), {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!res.ok) return;
      const data = await res.json();
      renderDeviceHeroAndCards(data.device, data.telemetry_series);
      renderEventTable(data.alerts || { items: [], total: 0 });
    } catch {
      // Silent retry on next cycle
    }
  }

  async function postCommand(command) {
    try {
      const res = await fetch("/api/devices/" + encodeURIComponent(DEVICE_ID) + "/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: command, duration_ms: 3000 }),
      });
      if (!res.ok) {
        showToast("Gagal mengirim perintah (Rate Limit / Koneksi).");
        return;
      }
      const data = await res.json();
      showToast("Perintah '" + data.command + "' dikirim ke topik " + data.topic);
      refreshDashboard();
    } catch {
      showToast("Gagal menghubungi backend BioPulse Care.");
    }
  }

  async function triggerSimulation(type) {
    try {
      const res = await fetch("/api/devices/" + encodeURIComponent(DEVICE_ID) + "/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: type }),
      });
      if (res.ok) {
        showToast("Simulasi '" + type.toUpperCase() + "' berhasil diproses.");
        refreshDashboard();
      }
    } catch {
      showToast("Gagal menjalankan simulasi.");
    }
  }

  function setupWebSocket() {
    const wsDot = el("ws-dot");
    const wsLabel = el("ws-label");
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(proto + "//" + window.location.host + "/ws/dashboard");

    ws.onopen = function () {
      if (wsDot) wsDot.className = "w-2 h-2 rounded-full bg-secondary";
      if (wsLabel) wsLabel.textContent = "Live WebSocket";
    };

    ws.onmessage = function (evt) {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.event === "alert" && msg.data && msg.data.alert) {
          showToast("Event Baru: " + msg.data.alert.title);
        }
        refreshDashboard();
      } catch {
        // Ignore malformed frame
      }
    };

    ws.onclose = function () {
      if (wsDot) wsDot.className = "w-2 h-2 rounded-full bg-tertiary";
      if (wsLabel) wsLabel.textContent = "Menyambung Ulang...";
      window.setTimeout(setupWebSocket, 4000);
    };
  }

  function bindEvents() {
    const btnBuzzer = el("btn-buzzer");
    if (btnBuzzer) btnBuzzer.addEventListener("click", () => postCommand("buzzer"));

    const btnVoice = el("btn-voice-msg");
    if (btnVoice) btnVoice.addEventListener("click", () => postCommand("voice_ping"));

    const btnReset = el("btn-reset-alarm");
    if (btnReset) btnReset.addEventListener("click", () => postCommand("reset_alarm"));

    const btnTgTest = el("btn-telegram-test");
    if (btnTgTest) {
      btnTgTest.addEventListener("click", async () => {
        try {
          const res = await fetch("/api/notifications/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device_id: DEVICE_ID }),
          });
          if (res.ok) {
            const data = await res.json();
            showToast("Bot @BioPulseCare_bot: " + data.notification.status_label);
            refreshDashboard();
          } else {
            showToast("Tunggu beberapa saat sebelum mengirim uji Telegram lagi.");
          }
        } catch {
          showToast("Gagal menghubungi endpoint uji Telegram.");
        }
      });
    }

    const searchInput = el("input-search-event");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        currentSearch = e.target.value || "";
        refreshDashboard();
      });
    }

    const catSelect = el("select-category-event");
    if (catSelect) {
      catSelect.addEventListener("change", (e) => {
        currentCategory = e.target.value || "Semua Event";
        refreshDashboard();
      });
    }

    const btnSimTel = el("btn-sim-telemetry");
    if (btnSimTel) btnSimTel.addEventListener("click", () => triggerSimulation("telemetry"));

    const btnSimFall = el("btn-sim-fall");
    if (btnSimFall) btnSimFall.addEventListener("click", () => triggerSimulation("fall"));

    const btnSimSos = el("btn-sim-sos");
    if (btnSimSos) btnSimSos.addEventListener("click", () => triggerSimulation("sos"));

    const btnSimOff = el("btn-sim-offline");
    if (btnSimOff) {
      btnSimOff.addEventListener("click", () => {
        triggerSimulation(currentDeviceStatus === "online" ? "offline" : "online");
      });
    }

    const modalCloseTop = el("modal-close-top");
    const modalCancel = el("modal-btn-cancel");
    if (modalCloseTop) modalCloseTop.addEventListener("click", closeEventModal);
    if (modalCancel) modalCancel.addEventListener("click", closeEventModal);

    const modalAck = el("modal-btn-ack");
    if (modalAck) {
      modalAck.addEventListener("click", async () => {
        if (!activeModalAlert) return;
        const alertId = activeModalAlert.id;
        closeEventModal();
        try {
          const res = await fetch(
            "/api/devices/" +
              encodeURIComponent(DEVICE_ID) +
              "/alerts/" +
              encodeURIComponent(alertId) +
              "/acknowledge",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ acknowledged_by: "Ibu Siti Rahayu" }),
            }
          );
          if (res.ok) {
            showToast("Event ditandai selesai ditinjau oleh Ibu Siti.");
            refreshDashboard();
          }
        } catch {
          showToast("Gagal memperbarui status event.");
        }
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    refreshDashboard();
    setupWebSocket();
  });
})();
