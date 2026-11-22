# Folder model ML

Salin hasil notebook ke sini (nama file harus persis):

- `biopulse_random_forest_fall.joblib`      -> deteksi jatuh (jendela IMU 3 detik)
- `biopulse_isolation_forest_vitals.joblib` -> pola BPM/SpO2 jendela 5 menit (eksperimental)

Lalu `pip install -r ../requirements-ml.txt` (versi scikit-learn harus sama dengan di Colab) dan restart backend.
Cek status: `http://127.0.0.1:8080/api/ml/status`
