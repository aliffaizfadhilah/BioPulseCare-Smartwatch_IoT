-- =============================================================================
-- BioPulse Care — Skema PostgreSQL Multi-Device
-- Mendukung beberapa perangkat (device_id) dan beberapa pengguna/caregiver
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    full_name VARCHAR(120) NOT NULL,
    role_label VARCHAR(80) NOT NULL DEFAULT 'Keluarga / Caregiver',
    password_hash VARCHAR(255) NOT NULL,
    telegram_chat_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS devices (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(64) UNIQUE NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    patient_name VARCHAR(120) NOT NULL,
    patient_relation VARCHAR(64) NOT NULL DEFAULT 'Ayah',
    status VARCHAR(24) NOT NULL DEFAULT 'online',
    battery_pct INTEGER NOT NULL DEFAULT 88,
    rssi INTEGER DEFAULT -62,
    oled_ok BOOLEAN NOT NULL DEFAULT TRUE,
    max_ok BOOLEAN NOT NULL DEFAULT TRUE,
    mpu_ok BOOLEAN NOT NULL DEFAULT TRUE,
    finger_detected BOOLEAN NOT NULL DEFAULT TRUE,
    sos_active BOOLEAN NOT NULL DEFAULT FALSE,
    fall_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    last_bpm INTEGER NOT NULL DEFAULT 78,
    last_spo2 INTEGER NOT NULL DEFAULT 98,
    last_accel_mag REAL NOT NULL DEFAULT 9.8,
    last_seen_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_devices_device_id ON devices(device_id);

CREATE TABLE IF NOT EXISTS device_status_history (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    status VARCHAR(24) NOT NULL,
    reason VARCHAR(120) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_status_history_device_time
    ON device_status_history(device_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS telemetry (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    bpm INTEGER NOT NULL DEFAULT 0,
    spo2 INTEGER NOT NULL DEFAULT 0,
    finger_detected BOOLEAN NOT NULL DEFAULT FALSE,
    ir_value BIGINT NOT NULL DEFAULT 0,
    accel_x REAL NOT NULL DEFAULT 0.0,
    accel_y REAL NOT NULL DEFAULT 0.0,
    accel_z REAL NOT NULL DEFAULT 9.8,
    accel_mag REAL NOT NULL DEFAULT 9.8,
    gyro_x REAL NOT NULL DEFAULT 0.0,
    gyro_y REAL NOT NULL DEFAULT 0.0,
    gyro_z REAL NOT NULL DEFAULT 0.0,
    sos_active BOOLEAN NOT NULL DEFAULT FALSE,
    fall_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    device_timestamp VARCHAR(64),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_telemetry_device_time
    ON telemetry(device_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    alert_type VARCHAR(48) NOT NULL,
    category VARCHAR(48) NOT NULL,
    urgency VARCHAR(32) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    detection_method VARCHAR(64) NOT NULL DEFAULT 'Rule-Based',
    action_type VARCHAR(32) NOT NULL DEFAULT 'Detail',
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_by VARCHAR(120),
    acknowledged_at TIMESTAMPTZ,
    device_timestamp VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_device_time
    ON alerts(device_id, created_at DESC);

CREATE TABLE IF NOT EXISTS notification_logs (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id) ON DELETE CASCADE,
    device_id VARCHAR(64) NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    channel VARCHAR(64) NOT NULL DEFAULT 'Telegram',
    recipients_label VARCHAR(160) NOT NULL,
    message_id_label VARCHAR(80) NOT NULL,
    status VARCHAR(32) NOT NULL,
    status_label VARCHAR(80) NOT NULL,
    badge_tone VARCHAR(32) NOT NULL DEFAULT 'success',
    error_detail TEXT,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notification_logs_alert
    ON notification_logs(alert_id);

CREATE TABLE IF NOT EXISTS device_settings (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(64) UNIQUE NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    telemetry_interval_sec INTEGER NOT NULL DEFAULT 5,
    heartbeat_interval_sec INTEGER NOT NULL DEFAULT 10,
    offline_timeout_sec INTEGER NOT NULL DEFAULT 30,
    fall_threshold_ms2 REAL NOT NULL DEFAULT 22.0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
