# =============================================================================
# SEL TAMBAHAN NOTEBOOK - Perbaikan recall deteksi jatuh (tempel SETELAH sel evaluasi test, "CELL 40")
# Aturan: hyperparameter & ambang keputusan dipilih HANYA dengan data VALIDATION.
# Data TEST dipakai sekali di akhir untuk melaporkan hasil.
# Variabel yang dipakai berasal dari notebook Anda: X_train, y_train, X_val, y_val, X_test, y_test,
# fall_val, fall_test, fall_fall_metrics (fall_metrics), FALL_FEATURE_COLS, fall_medians, rf_model, dll.
# =============================================================================

# ---------- SEL A: model lebih kuat + pemilihan model pada validation ----------
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.metrics import precision_recall_curve

candidates = {
    "RF-100 (baseline)": rf_model,
    "RF-300 leaf2": RandomForestClassifier(
        n_estimators=300, min_samples_leaf=2, max_features="sqrt",
        class_weight="balanced_subsample", random_state=RANDOM_STATE, n_jobs=-1),
    "HistGB": HistGradientBoostingClassifier(
        max_depth=6, learning_rate=0.08, max_iter=300,
        class_weight="balanced", random_state=RANDOM_STATE),
}
for name, m in candidates.items():
    if name != "RF-100 (baseline)":
        m.fit(X_train, y_train)

def proba_fall(m, X):
    return m.predict_proba(X)[:, list(m.classes_).index("fall")]

yv = (y_val == "fall").to_numpy()
rows = []
for name, m in candidates.items():
    p = proba_fall(m, X_val)
    prec, rec, thr = precision_recall_curve(yv, p)
    # ambang terbesar yang masih mencapai recall >= 0.80 (precision setinggi mungkin)
    ok = np.where(rec[:-1] >= 0.80)[0]
    best_thr = float(thr[ok[-1]]) if len(ok) else 0.0
    pred = p >= best_thr
    tp = int((pred & yv).sum()); fp = int((pred & ~yv).sum())
    rows.append({"model": name, "thr_val": best_thr,
                 "precision_val@recall0.8": tp / max(tp + fp, 1)})
cmp_df = pd.DataFrame(rows).sort_values("precision_val@recall0.8", ascending=False)
display(cmp_df)
best_name = cmp_df.iloc[0]["model"]
best_model = candidates[best_name]
best_threshold = float(cmp_df.iloc[0]["thr_val"])
print("Model terpilih (berdasarkan validation):", best_name, "| ambang:", round(best_threshold, 3))

# ---------- SEL B: evaluasi akhir pada TEST dengan ambang dari validation ----------
p_test = proba_fall(best_model, X_test)
test_pred = np.where(p_test >= best_threshold, "fall", "adl")
final_metrics, final_cm = fall_metrics(y_test, test_pred, fall_test, f"{best_name} @thr={best_threshold:.2f}")
display(pd.DataFrame([final_metrics]).T.rename(columns={0: "nilai"}))
if final_metrics["recall_fall"] >= 0.80:
    print("Target recall >= 80% tercapai pada test. Cek juga precision & alarm palsu per jam.")
else:
    print("Recall test belum >= 80%. Jangan klaim target tercapai; tambah data/fitur atau data MPU6050 sendiri.")

# ---------- SEL C: simpan artefak untuk backend (memuat decision_threshold) ----------
fall_artifact = {
    "model": best_model,
    "feature_columns": FALL_FEATURE_COLS,
    "medians": fall_medians.to_dict(),
    "imu_fs_hz": IMU_FS_HZ,
    "window_seconds": IMU_WINDOW_SECONDS,
    "window_samples": IMU_WINDOW_SAMPLES,
    "overlap": IMU_OVERLAP,
    "accel_to_g": ACCEL_TO_G,
    "gyro_to_dps": GYRO_TO_DPS,
    # Faktor konversi data PERANGKAT -> satuan data latih (dipakai backend). 1.0 jika sama-sama m/s2 & rad/s.
    "device_accel_factor": 1.0,
    "device_gyro_factor": 1.0,
    "class_names": list(best_model.classes_),
    "decision_threshold": best_threshold,   # dipakai backend: p(fall) >= ambang -> dugaan jatuh
    "random_state": RANDOM_STATE,
    "test_metrics": final_metrics,
    "note": "Prototype fall/ADL classifier; bukan alat medis / penjamin deteksi jatuh.",
}
joblib.dump(fall_artifact, ARTIFACT_DIR / "biopulse_random_forest_fall.joblib")
print("Tersimpan:", ARTIFACT_DIR / "biopulse_random_forest_fall.joblib")

# CATATAN VERIFIKASI SATUAN (wajib sebelum dipakai di perangkat):
#   print(fall_raw[["ax","ay","az"]].describe())       -> saat diam, rata-rata |a| ~9.8 (m/s2) atau ~1.0 (g)
#   print(fall_raw[["gx","gy","gz"]].abs().describe())  -> rad/s: umumnya < ~10; deg/s: bisa ratusan
# MPU6050 (library Adafruit) mengirim m/s2 dan rad/s. Atur di artefak:
#   - data latih sudah m/s2 -> device_accel_factor = 1.0
#   - data latih dalam g    -> device_accel_factor = 1/9.80665 (ACCEL_TO_G tetap None di notebook)
#   - gyro latih deg/s      -> device_gyro_factor = 57.2958
