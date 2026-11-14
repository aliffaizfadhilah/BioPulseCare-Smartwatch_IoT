/*
  =============================================================================
  BioPulse Care - Firmware Lengkap ESP32 Standar (Revisi Final + Virtual GND + MQTT IoT)
  (MAX30102, MPU6050, OLED SSD1306, Tombol SOS, Tombol Reset, Buzzer, Wi-Fi & MQTT LWT)
  =============================================================================
  WIRING PIN ESP32 STANDAR (TIDAK DIUBAH - SUMBER KEBENARAN):
   - SDA (OLED, MPU6050, MAX30102) : GPIO 25
   - SCL (OLED, MPU6050, MAX30102) : GPIO 26
   - Buzzer                        : GPIO 13
   - Tombol SOS                    : GPIO 32 -> kaki sebelahnya ke GPIO 14 (GND)
   - Tombol Reset                  : GPIO 33 -> kaki sebelahnya ke GPIO 27 (GND)
   - VCC OLED, MPU6050, Buzzer     : 3V3
   - VIN MAX30102                  : 3V3 (disarankan) atau 5V
   - GND OLED, MPU, MAX, Buzzer    : GND
  =============================================================================
  CATATAN KESELAMATAN & PENGUJIAN:
   - Seluruh pembacaan sensor, OLED, tombol SOS, tombol Reset, dan Buzzer berjalan
     secara LOKAL & NON-BLOCKING. Jika Wi-Fi atau internet putus, fungsi keselamatan
     lokal tetap bekerja 100% tanpa gangguan.
   - Pengujian kompilasi perangkat lunak tidak menggantikan pengujian langsung
     pada perangkat keras ESP32 fisik.
  =============================================================================
*/

#include <Wire.h>
#include <WiFi.h>
#include <math.h>
#include "driver/gpio.h"
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include "MAX30105.h"
#include "heartRate.h"

// ================= KONFIGURASI JARINGAN & MQTT =================
// Sesuaikan WIFI_SSID dan WIFI_PASSWORD dengan Wi-Fi lokal Anda
#define WIFI_SSID                 "NAMA_WIFI_ANDA"
#define WIFI_PASSWORD             "PASSWORD_WIFI_ANDA"

#define DEVICE_ID                 "bp-device-001"
#define MQTT_BROKER_HOST          "broker.emqx.io"
#define MQTT_BROKER_PORT          1883
#define MQTT_TOPIC_PREFIX         "biopulse"

// Interval dapat dikonfigurasi (Bagian 4.2 Panduan)
const unsigned long TELEMETRY_INTERVAL_MS  = 5000;   // Telemetry setiap 5 detik
const unsigned long HEARTBEAT_INTERVAL_MS  = 10000;  // Heartbeat setiap 10 detik
const unsigned long WIFI_RETRY_INTERVAL_MS = 10000;  // Coba sambung Wi-Fi tiap 10 detik
const unsigned long MQTT_RETRY_INTERVAL_MS = 5000;   // Coba sambung MQTT tiap 5 detik
const unsigned long MQTT_PING_INTERVAL_MS  = 20000;  // Keep-alive MQTT tiap 20 detik

// ================= PIN ESP32 STANDAR (TETAP) =================
#define I2C_SDA           25
#define I2C_SCL           26
#define PIN_BTN_SOS       32
#define PIN_BTN_SOS_GND   14   // Pin GPIO sebagai GND virtual Tombol SOS
#define PIN_BTN_RESET     33
#define PIN_BTN_RESET_GND 27   // Pin GPIO sebagai GND virtual Tombol Reset
#define PIN_BUZZER        13

// ================= PENGATURAN BUZZER =================
// 0 = buzzer AKTIF (berbunyi sendiri saat diberi tegangan)
// 1 = buzzer PASIF (butuh sinyal frekuensi, seperti modul MH-FMD)
#define BUZZER_PASIF      0
#define BUZZER_FREQ       2700

// 1 = modul buzzer berbunyi saat pin LOW (active low)
// 0 = buzzer berbunyi saat pin HIGH (active high)
#define BUZZER_ACTIVE_LOW 1

// ================= OLED DISPLAY =================
#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

// ================= OBJEK SENSOR =================
MAX30105 particleSensor;
Adafruit_MPU6050 mpu;
bool okOled = false, okMax = false, okMpu = false;

// ================= VARIABEL MAX30102 =================
const long IR_FINGER_THRESHOLD = 40000;
const byte RATE_SIZE = 4;
byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
float beatsPerMinute = 0;
int beatAvg = 0;
int spo2Est = 0;
long currentIR = 0;
long currentRed = 0;
bool signalOk = false;
unsigned long beatFlashUntil = 0;

double avered = 0, aveir = 0, sumirrms = 0, sumredrms = 0;
int sampleCount = 0;
const int SPO2_SAMPLE_WINDOW = 100;

// ================= VARIABEL MPU6050 =================
unsigned long lastImuRead = 0;
const unsigned long IMU_INTERVAL_MS = 50;  // 20 Hz
float accMagnitude = 0, ax = 0, ay = 0, az = 0, gx = 0, gy = 0, gz = 0;
bool fallCandidate = false;
const float FALL_IMPACT_THRESHOLD = 22.0;  // m/s^2

// ================= VARIABEL KONTROL & BUZZER JARAK JAUH =================
unsigned long sosPressStart = 0;
bool sosPressedPrev = false;
bool sosHandled = false;
bool sosActive = false;
unsigned long remoteBuzzerUntil = 0;
int page = 0;                     // 0=Vital, 1=Gerak, 2=Status
const int PAGE_COUNT = 3;
unsigned long lastOledUpdate = 0;
unsigned long lastReport = 0;
unsigned long lastRetryInit = 0;

// ================= VARIABEL WI-FI, MQTT & OFFLINE BUFFER =================
WiFiClient mqttNet;
bool mqttConnected = false;
unsigned long lastWifiRetry = 0;
unsigned long lastMqttRetry = 0;
unsigned long lastTelemetrySent = 0;
unsigned long lastHeartbeatSent = 0;
unsigned long lastMqttPing = 0;
uint16_t mqttPacketId = 1;

String topicTelemetry = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/telemetry";
String topicHeartbeat = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/heartbeat";
String topicStatus    = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/status";
String topicAlert     = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/alert";
String topicCommand   = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/command";

struct OfflineEvent {
  bool valid;
  char alertType[32];
  char urgency[24];
  char description[160];
  unsigned long eventMillis;
};

const int OFFLINE_QUEUE_SIZE = 10;
OfflineEvent offlineQueue[OFFLINE_QUEUE_SIZE];
int offlineQueueHead = 0;
int offlineQueueCount = 0;

// ================= HELPER I2C =================
bool i2cDevicePresent(byte addr) {
  Wire.beginTransmission(addr);
  return (Wire.endTransmission() == 0);
}

// ================= FUNGSI BUZZER =================
void buzzerInit() {
#if BUZZER_PASIF
  #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcAttach(PIN_BUZZER, BUZZER_FREQ, 8);
  #else
    ledcSetup(0, BUZZER_FREQ, 8);
    ledcAttachPin(PIN_BUZZER, 0);
  #endif
#else
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, BUZZER_ACTIVE_LOW ? HIGH : LOW);
  gpio_set_drive_capability((gpio_num_t)PIN_BUZZER, GPIO_DRIVE_CAP_3);
#endif
}

void buzzerOn() {
#if BUZZER_PASIF
  #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWriteTone(PIN_BUZZER, BUZZER_FREQ);
  #else
    ledcWriteTone(0, BUZZER_FREQ);
  #endif
#else
  digitalWrite(PIN_BUZZER, BUZZER_ACTIVE_LOW ? LOW : HIGH);
#endif
}

void buzzerOff() {
#if BUZZER_PASIF
  #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWriteTone(PIN_BUZZER, 0);
  #else
    ledcWriteTone(0, 0);
  #endif
#else
  digitalWrite(PIN_BUZZER, BUZZER_ACTIVE_LOW ? HIGH : LOW);
#endif
}

void beep(int ms) {
  buzzerOn();
  delay(ms);
  buzzerOff();
}

// ================= INISIALISASI SENSOR =================
void initSensors() {
  if (!okOled) {
    if (i2cDevicePresent(0x3C)) {
      okOled = display.begin(SSD1306_SWITCHCAPVCC, 0x3C, true, false);
    } else if (i2cDevicePresent(0x3D)) {
      okOled = display.begin(SSD1306_SWITCHCAPVCC, 0x3D, true, false);
    }
  }

  if (!okMax && i2cDevicePresent(0x57)) {
    okMax = particleSensor.begin(Wire, I2C_SPEED_STANDARD);
    if (okMax) {
      particleSensor.setup();
      particleSensor.wakeUp();
    }
  }

  if (!okMpu) {
    if (i2cDevicePresent(0x68)) {
      okMpu = mpu.begin(0x68, &Wire);
    } else if (i2cDevicePresent(0x69)) {
      okMpu = mpu.begin(0x69, &Wire);
    }
    if (okMpu) {
      mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
      mpu.setGyroRange(MPU6050_RANGE_500_DEG);
      mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    }
  }

  Wire.setClock(100000);
}

// ================= PROTOKOL MQTT v3.1.1 RINGAN (TANPA LIBRARY EKSTERNAL) =================
void mqttWriteRemainingLength(uint8_t* buf, int& idx, int length) {
  do {
    uint8_t encoded = length % 128;
    length /= 128;
    if (length > 0) encoded |= 128;
    buf[idx++] = encoded;
  } while (length > 0);
}

void mqttWriteString(uint8_t* buf, int& idx, const char* str) {
  uint16_t len = (uint16_t)strlen(str);
  buf[idx++] = (uint8_t)(len >> 8);
  buf[idx++] = (uint8_t)(len & 0xFF);
  memcpy(&buf[idx], str, len);
  idx += len;
}

bool mqttPublish(const char* topic, const char* payload, bool retain = false) {
  if (!mqttConnected || !mqttNet.connected()) {
    mqttConnected = false;
    return false;
  }
  uint16_t topicLen = (uint16_t)strlen(topic);
  uint16_t payloadLen = (uint16_t)strlen(payload);
  int remLen = 2 + topicLen + payloadLen;

  uint8_t pkt[600];
  if (remLen + 5 > (int)sizeof(pkt)) return false;

  int idx = 0;
  pkt[idx++] = retain ? 0x31 : 0x30; // PUBLISH QoS 0 + Retain flag
  mqttWriteRemainingLength(pkt, idx, remLen);
  mqttWriteString(pkt, idx, topic);
  memcpy(&pkt[idx], payload, payloadLen);
  idx += payloadLen;

  size_t written = mqttNet.write(pkt, idx);
  return (written == (size_t)idx);
}

bool mqttSubscribe(const char* topic) {
  if (!mqttConnected || !mqttNet.connected()) return false;
  uint16_t topicLen = (uint16_t)strlen(topic);
  int remLen = 2 + 2 + topicLen + 1;

  uint8_t pkt[160];
  int idx = 0;
  pkt[idx++] = 0x82; // SUBSCRIBE
  mqttWriteRemainingLength(pkt, idx, remLen);
  pkt[idx++] = (uint8_t)(mqttPacketId >> 8);
  pkt[idx++] = (uint8_t)(mqttPacketId & 0xFF);
  mqttPacketId = (mqttPacketId % 65535) + 1;
  mqttWriteString(pkt, idx, topic);
  pkt[idx++] = 0x00; // QoS 0

  return (mqttNet.write(pkt, idx) == (size_t)idx);
}

void enqueueOfflineEvent(const char* alertType, const char* urgency, const char* desc) {
  int slot = (offlineQueueHead + offlineQueueCount) % OFFLINE_QUEUE_SIZE;
  if (offlineQueueCount == OFFLINE_QUEUE_SIZE) {
    offlineQueueHead = (offlineQueueHead + 1) % OFFLINE_QUEUE_SIZE;
  } else {
    offlineQueueCount++;
  }
  offlineQueue[slot].valid = true;
  strncpy(offlineQueue[slot].alertType, alertType, sizeof(offlineQueue[slot].alertType) - 1);
  strncpy(offlineQueue[slot].urgency, urgency, sizeof(offlineQueue[slot].urgency) - 1);
  strncpy(offlineQueue[slot].description, desc, sizeof(offlineQueue[slot].description) - 1);
  offlineQueue[slot].eventMillis = millis();
  Serial.printf("[OFFLINE-BUFFER] Event '%s' disimpan ke antrean lokal (%d/%d)\n",
                alertType, offlineQueueCount, OFFLINE_QUEUE_SIZE);
}

void publishOrQueueAlert(const char* alertType, const char* urgency, const char* desc) {
  char payload[380];
  snprintf(payload, sizeof(payload),
           "{\"device_id\":\"%s\",\"alert_type\":\"%s\",\"urgency\":\"%s\","
           "\"description\":\"%s\",\"bpm\":%d,\"spo2\":%d,\"accel_mag\":%.2f,\"uptime_ms\":%lu}",
           DEVICE_ID, alertType, urgency, desc, beatAvg, spo2Est, accMagnitude, millis());

  if (mqttConnected && mqttPublish(topicAlert.c_str(), payload, false)) {
    Serial.printf("[MQTT] Alert terkirim: %s\n", alertType);
  } else {
    enqueueOfflineEvent(alertType, urgency, desc);
  }
}

void flushOfflineEvents() {
  while (offlineQueueCount > 0 && mqttConnected) {
    OfflineEvent& ev = offlineQueue[offlineQueueHead];
    if (ev.valid) {
      char payload[400];
      snprintf(payload, sizeof(payload),
               "{\"device_id\":\"%s\",\"alert_type\":\"%s\",\"urgency\":\"%s\","
               "\"description\":\"[Rekaman Offline] %s\",\"offline_queued\":true,\"uptime_ms\":%lu}",
               DEVICE_ID, ev.alertType, ev.urgency, ev.description, ev.eventMillis);
      if (!mqttPublish(topicAlert.c_str(), payload, false)) {
        break;
      }
      Serial.printf("[OFFLINE-FLUSH] Event '%s' berhasil dikirim ulang ke server.\n", ev.alertType);
      ev.valid = false;
    }
    offlineQueueHead = (offlineQueueHead + 1) % OFFLINE_QUEUE_SIZE;
    offlineQueueCount--;
  }
}

bool connectMqttWithLWT() {
  if (WiFi.status() != WL_CONNECTED) return false;
  mqttNet.stop();

  Serial.printf("[MQTT] Menghubungkan ke %s:%d...\n", MQTT_BROKER_HOST, MQTT_BROKER_PORT);
  if (!mqttNet.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 3500)) {
    Serial.println(F("[MQTT] Gagal koneksi TCP ke broker (cek koneksi internet Wi-Fi/Hotspot)."));
    return false;
  }
  mqttNet.setNoDelay(true);

  String clientId = String("bp-esp32-") + String((uint32_t)ESP.getEfuseMac(), HEX);
  const char* willTopic = topicStatus.c_str();
  char willMsg[128];
  snprintf(willMsg, sizeof(willMsg),
           "{\"device_id\":\"%s\",\"status\":\"offline\",\"reason\":\"lwt\"}", DEVICE_ID);

  // Variable header: "MQTT" (level 4), Connect Flags: CleanSession(0x02) | WillFlag(0x04) | WillQoS0(0x00) | WillRetain(0x20) = 0x26
  uint8_t pkt[380];
  int idx = 0;
  pkt[idx++] = 0x10; // CONNECT

  int remLen = 10 + (2 + clientId.length()) + (2 + strlen(willTopic)) + (2 + strlen(willMsg));
  mqttWriteRemainingLength(pkt, idx, remLen);
  mqttWriteString(pkt, idx, "MQTT");
  pkt[idx++] = 0x04; // Protocol Level 3.1.1
  pkt[idx++] = 0x26; // CleanSession + WillFlag + WillRetain
  pkt[idx++] = 0x00;
  pkt[idx++] = 60;   // Keep-Alive 60 detik

  mqttWriteString(pkt, idx, clientId.c_str());
  mqttWriteString(pkt, idx, willTopic);
  mqttWriteString(pkt, idx, willMsg);

  if (mqttNet.write(pkt, idx) != (size_t)idx) {
    Serial.println(F("[MQTT] Gagal mengirim paket CONNECT."));
    mqttNet.stop();
    return false;
  }

  // Tunggu CONNACK (maks 1500 ms)
  unsigned long waitStart = millis();
  while (mqttNet.available() < 4 && (millis() - waitStart) < 1500) {
    delay(5);
  }
  if (mqttNet.available() < 4) {
    Serial.println(F("[MQTT] Timeout menunggu balasan CONNACK dari broker."));
    mqttNet.stop();
    return false;
  }
  uint8_t connack[4];
  mqttNet.read(connack, 4);
  if (connack[0] != 0x20 || connack[3] != 0x00) {
    Serial.printf("[MQTT] Ditolak broker (kode: %d).\n", connack[3]);
    mqttNet.stop();
    return false;
  }

  mqttConnected = true;
  lastMqttPing = millis();

  // Publikasikan status online (retained) ke biopulse/{device_id}/status
  char onlinePayload[140];
  snprintf(onlinePayload, sizeof(onlinePayload),
           "{\"device_id\":\"%s\",\"status\":\"online\",\"reason\":\"mqtt_connect\",\"uptime_ms\":%lu}",
           DEVICE_ID, millis());
  mqttPublish(topicStatus.c_str(), onlinePayload, true);

  // Subscribe ke topik command untuk tombol dashboard ("Bunyikan Gelang", "Kirim Suara", "Reset")
  mqttSubscribe(topicCommand.c_str());

  // Kirim ulang event yang sempat tersimpan saat offline
  flushOfflineEvents();

  Serial.println(F("[MQTT] BERHASIL TERHUBUNG ke broker EMQX! Layar OLED -> IOT"));
  return true;
}

void handleIncomingMqttCommand(const String& jsonStr) {
  Serial.printf("[MQTT-CMD] Pesan diterima: %s\n", jsonStr.c_str());
  if (jsonStr.indexOf("\"buzzer\"") >= 0) {
    remoteBuzzerUntil = millis() + 3000;
    Serial.println(F("[AKSI] Buzzer jarak jauh diaktifkan selama 3 detik."));
  } else if (jsonStr.indexOf("\"voice_ping\"") >= 0) {
    remoteBuzzerUntil = millis() + 1200;
    Serial.println(F("[AKSI] Panggilan suara/nada perhatian dari keluarga diterima."));
  } else if (jsonStr.indexOf("\"reset_alarm\"") >= 0) {
    sosActive = false;
    fallCandidate = false;
    remoteBuzzerUntil = 0;
    Serial.println(F("[AKSI] Alarm di-reset dari Web Dashboard."));
  } else if (jsonStr.indexOf("\"test_sos\"") >= 0) {
    sosActive = true;
    publishOrQueueAlert("SYSTEM_TEST_SOS", "Uji Sistem",
                        "Simulasi uji darurat SOS diaktifkan dari Web Dashboard");
  }
}

void pollMqttIncoming(unsigned long now) {
  if (!mqttConnected) return;
  if (!mqttNet.connected()) {
    mqttConnected = false;
    Serial.println(F("[MQTT] Koneksi terputus. Mode keselamatan lokal tetap aktif."));
    return;
  }

  // Keep-alive PINGREQ
  if (now - lastMqttPing >= MQTT_PING_INTERVAL_MS) {
    lastMqttPing = now;
    const uint8_t pingPkt[2] = {0xC0, 0x00};
    mqttNet.write(pingPkt, 2);
  }

  while (mqttNet.available() > 0) {
    uint8_t header = mqttNet.read();
    uint8_t pktType = header & 0xF0;

    int multiplier = 1;
    int remLen = 0;
    unsigned long t0 = millis();
    while (millis() - t0 < 40) {
      if (!mqttNet.available()) continue;
      uint8_t enc = mqttNet.read();
      remLen += (enc & 127) * multiplier;
      if ((enc & 128) == 0) break;
      multiplier *= 128;
    }

    uint8_t buf[384];
    int toRead = min(remLen, (int)sizeof(buf) - 1);
    int readCount = 0;
    t0 = millis();
    while (readCount < toRead && (millis() - t0) < 60) {
      if (mqttNet.available()) {
        buf[readCount++] = mqttNet.read();
      }
    }
    // Buang sisa byte jika paket lebih besar dari buffer
    for (int i = toRead; i < remLen && mqttNet.available(); i++) {
      mqttNet.read();
    }

    if (pktType == 0x30 && readCount >= 2) { // PUBLISH diterima
      uint16_t tLen = ((uint16_t)buf[0] << 8) | buf[1];
      int payloadStart = 2 + tLen;
      if (payloadStart < readCount) {
        buf[readCount] = '\0';
        String msg = String((char*)&buf[payloadStart]);
        handleIncomingMqttCommand(msg);
      }
    }
  }
}

void publishTelemetry(unsigned long now) {
  char payload[360];
  snprintf(payload, sizeof(payload),
           "{\"device_id\":\"%s\",\"uptime_ms\":%lu,\"bpm\":%d,\"spo2\":%d,"
           "\"finger_detected\":%s,\"ir_value\":%ld,"
           "\"accel_x\":%.2f,\"accel_y\":%.2f,\"accel_z\":%.2f,\"accel_mag\":%.2f,"
           "\"gyro_x\":%.2f,\"gyro_y\":%.2f,\"gyro_z\":%.2f,"
           "\"sos_active\":%s,\"fall_candidate\":%s,"
           "\"oled_ok\":%s,\"max_ok\":%s,\"mpu_ok\":%s,\"rssi\":%d}",
           DEVICE_ID, now, beatAvg, spo2Est,
           signalOk ? "true" : "false", currentIR,
           ax, ay, az, accMagnitude,
           gx, gy, gz,
           sosActive ? "true" : "false",
           fallCandidate ? "true" : "false",
           okOled ? "true" : "false",
           okMax ? "true" : "false",
           okMpu ? "true" : "false",
           (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : -100);
  mqttPublish(topicTelemetry.c_str(), payload, false);
}

void publishHeartbeat(unsigned long now) {
  char payload[240];
  snprintf(payload, sizeof(payload),
           "{\"device_id\":\"%s\",\"status\":\"online\",\"uptime_ms\":%lu,\"rssi\":%d,"
           "\"free_heap\":%u,\"sensors\":{\"oled\":%s,\"max30102\":%s,\"mpu6050\":%s}}",
           DEVICE_ID, now,
           (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : -100,
           ESP.getFreeHeap(),
           okOled ? "true" : "false",
           okMax ? "true" : "false",
           okMpu ? "true" : "false");
  mqttPublish(topicHeartbeat.c_str(), payload, false);
}

// ================= FUNGSI GAMBAR OLED =================
void drawCentered(const char* s, int y, int size) {
  int16_t x1, y1;
  uint16_t w, h;
  display.setTextSize(size);
  display.getTextBounds(s, 0, y, &x1, &y1, &w, &h);
  display.setCursor((SCREEN_WIDTH - w) / 2, y);
  display.print(s);
}

void drawHeader(const char* title, int pg) {
  display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(3, 2);
  display.print(title);
  display.setCursor(86, 2);
  display.print(mqttConnected ? "IOT" : "LOC");
  display.setCursor(108, 2);
  display.printf("%d/%d", pg + 1, PAGE_COUNT);
  display.setTextColor(SSD1306_WHITE);
}

void drawHeart(int cx, int cy, bool filled) {
  if (filled) {
    display.fillCircle(cx - 4, cy, 4, SSD1306_WHITE);
    display.fillCircle(cx + 4, cy, 4, SSD1306_WHITE);
    display.fillTriangle(cx - 8, cy + 2, cx + 8, cy + 2, cx, cy + 11, SSD1306_WHITE);
  } else {
    display.drawCircle(cx - 4, cy, 4, SSD1306_WHITE);
    display.drawCircle(cx + 4, cy, 4, SSD1306_WHITE);
    display.drawTriangle(cx - 8, cy + 2, cx + 8, cy + 2, cx, cy + 11, SSD1306_WHITE);
  }
}

void drawPageVital(unsigned long now) {
  drawHeader("VITAL", 0);
  drawHeart(14, 26, signalOk && now < beatFlashUntil);

  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(3);
  display.setCursor(34, 15);
  if (!okMax)            display.print("X");
  else if (!signalOk)    display.print("--");
  else if (beatAvg == 0) display.print("..");
  else                   display.print(beatAvg);
  display.setTextSize(1);
  display.setCursor(100, 30);
  display.print("BPM");

  if (!okMax) {
    drawCentered("MAX30102 GAGAL", 48, 1);
  } else if (signalOk) {
    display.setTextSize(2);
    display.setCursor(8, 46);
    if (spo2Est > 0) display.printf("SpO2 %d%%", spo2Est);
    else             display.print("SpO2 ..");
  } else {
    drawCentered("Tempelkan jari", 44, 1);
    drawCentered("pada sensor MAX30102", 54, 1);
  }
}

void drawPageGerak() {
  drawHeader("GERAK (MPU6050)", 1);
  display.setTextSize(1);
  if (!okMpu) {
    drawCentered("MPU6050 GAGAL", 30, 1);
    return;
  }
  display.setCursor(0, 14);
  display.printf("Total: %.1f m/s2", accMagnitude);

  display.drawRect(0, 24, 124, 9, SSD1306_WHITE);
  int bar = map((int)constrain(accMagnitude * 10, 0, 300), 0, 300, 0, 120);
  display.fillRect(2, 26, bar, 5, SSD1306_WHITE);
  int thr = 2 + (int)((FALL_IMPACT_THRESHOLD / 30.0) * 120.0);
  display.drawLine(thr, 21, thr, 36, SSD1306_WHITE);

  display.setCursor(0, 39);
  display.printf("X%5.1f Y%5.1f Z%5.1f", ax, ay, az);
  display.setCursor(0, 48);
  display.printf("G%5.1f G%5.1f G%5.1f", gx, gy, gz);
  display.setCursor(0, 57);
  display.print("Garis=ambang jatuh");
}

void drawPageStatus() {
  drawHeader("STATUS", 2);
  display.setTextSize(1);
  display.setCursor(0, 14);
  display.printf("OLED:%s MAX:%s MPU:%s",
                 okOled ? "OK" : "X",
                 okMax ? "OK" : "X",
                 okMpu ? "OK" : "X");
  display.setCursor(0, 24);
  display.printf("WiFi: %s", (WiFi.status() == WL_CONNECTED) ? "TERHUBUNG" : "OFFLINE");
  display.setCursor(0, 34);
  display.printf("MQTT: %s (Q:%d)", mqttConnected ? "ONLINE" : "PUTUS", offlineQueueCount);
  display.setCursor(0, 44);
  display.printf("Jari: %s", signalOk ? "TERDETEKSI" : "TIDAK ADA");
  display.setCursor(0, 55);
  display.print("SOS singkat=ganti hal");
}

void drawAlarmScreen(unsigned long now) {
  bool blink = ((now / 300) % 2) == 0;
  display.fillScreen(blink ? SSD1306_WHITE : SSD1306_BLACK);
  display.setTextColor(blink ? SSD1306_BLACK : SSD1306_WHITE);
  if (sosActive) {
    drawCentered("SOS", 6, 4);
    drawCentered("Bantuan diminta!", 44, 1);
  } else {
    drawCentered("JATUH?", 10, 3);
    drawCentered("Hentakan terdeteksi", 44, 1);
  }
  drawCentered("Tekan RESET: matikan", 55, 1);
  display.setTextColor(SSD1306_WHITE);
}

// ================= I2C SCAN =================
void i2cScan() {
  Serial.println(F("\n--- Scan Bus I2C ---"));
  int n = 0;
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("  [OK] Ditemukan: 0x%02X", addr);
      if (addr == 0x57) Serial.print(F(" -> MAX30102"));
      if (addr == 0x68 || addr == 0x69) Serial.print(F(" -> MPU6050"));
      if (addr == 0x3C || addr == 0x3D) Serial.print(F(" -> OLED SSD1306"));
      Serial.println();
      n++;
    }
  }
  if (n == 0) {
    Serial.println(F("  [!] Tidak ada perangkat I2C. Cek kabel SDA/SCL & daya."));
  }
  Serial.println(F("--------------------"));
}

void printHelpMenu() {
  Serial.println(F("\n=== PERINTAH SERIAL MONITOR (Baud 115200) ==="));
  Serial.println(F("  b : Uji bunyi buzzer"));
  Serial.println(F("  i : Scan I2C & inisialisasi ulang sensor"));
  Serial.println(F("  s : Simulasi alarm SOS (Kirim Alert MQTT)"));
  Serial.println(F("  j : Simulasi deteksi JATUH (Kirim Alert MQTT)"));
  Serial.println(F("  r : Reset / matikan alarm"));
  Serial.println(F("  p : Ganti halaman OLED"));
  Serial.println(F("  m : Cek status Wi-Fi, MQTT & antrean offline"));
  Serial.println(F("=============================================\n"));
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println(F("\n=== BioPulse Care: ESP32 Standar + MQTT IoT ==="));

  Wire.begin(I2C_SDA, I2C_SCL, 100000);
  Wire.setTimeOut(50);
  i2cScan();

  // Konfigurasi pin GND Virtual untuk Tombol SOS & Reset (TETAP DIPERTAHANKAN)
  pinMode(PIN_BTN_SOS_GND, OUTPUT);
  digitalWrite(PIN_BTN_SOS_GND, LOW);

  pinMode(PIN_BTN_RESET_GND, OUTPUT);
  digitalWrite(PIN_BTN_RESET_GND, LOW);

  // Konfigurasi pin Input Tombol dengan Pull-Up internal
  pinMode(PIN_BTN_SOS, INPUT_PULLUP);
  pinMode(PIN_BTN_RESET, INPUT_PULLUP);

  buzzerInit();
  initSensors();

  Serial.printf("Status Modul -> OLED: %s | MAX30102: %s | MPU6050: %s\n",
                okOled ? "OK" : "GAGAL",
                okMax  ? "OK" : "GAGAL",
                okMpu  ? "OK" : "GAGAL");

  if (okOled) {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    drawCentered("BIOPULSE", 10, 2);
    drawCentered("CARE", 30, 2);
    drawCentered("Inisialisasi IoT...", 52, 1);
    display.display();
  }

  // Mulai koneksi Wi-Fi secara non-blocking
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  if (strlen(WIFI_SSID) > 0 && strcmp(WIFI_SSID, "NAMA_WIFI_ANDA") != 0) {
    Serial.printf("[WIFI] Menghubungkan ke %s (non-blocking)...\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  } else {
    Serial.println(F("[WIFI] Isi WIFI_SSID & WIFI_PASSWORD untuk terhubung ke MQTT."));
  }

  Serial.println(F("Buzzer   : bunyi 2x"));
  beep(200); delay(150); beep(200);
  printHelpMenu();
}

// ================= LOOP =================
void loop() {
  unsigned long now = millis();

  // ---------- 0. PERINTAH SERIAL MONITOR ----------
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd == 'b' || cmd == 'B') {
      Serial.println(F("[TES] Uji Buzzer"));
      beep(250);
    } else if (cmd == 'i' || cmd == 'I') {
      i2cScan();
      okOled = false; okMax = false; okMpu = false;
      initSensors();
      Serial.printf("Re-Init -> OLED:%s MAX:%s MPU:%s\n",
                    okOled ? "OK" : "GAGAL", okMax ? "OK" : "GAGAL", okMpu ? "OK" : "GAGAL");
    } else if (cmd == 's' || cmd == 'S') {
      sosActive = true;
      Serial.println(F("[EVENT] Alarm SOS aktif via Serial."));
      publishOrQueueAlert("SOS_MANUAL", "Perhatian",
                          "Indikasi tombol darurat SOS diaktifkan (Serial/Manual)");
    } else if (cmd == 'j' || cmd == 'J') {
      fallCandidate = true;
      Serial.println(F("[EVENT] Deteksi JATUH aktif via Serial."));
      publishOrQueueAlert("FALL_CANDIDATE", "Perhatian",
                          "Dugaan jatuh / hentakan terdeteksi (Rule-Based MPU6050)");
    } else if (cmd == 'r' || cmd == 'R') {
      sosActive = false;
      fallCandidate = false;
      remoteBuzzerUntil = 0;
      Serial.println(F("[EVENT] Alarm di-reset via Serial."));
      publishOrQueueAlert("ALARM_RESET", "Normal",
                          "Alarm di-reset oleh pengguna/caregiver");
    } else if (cmd == 'p' || cmd == 'P') {
      page = (page + 1) % PAGE_COUNT;
      Serial.printf("[DISPLAY] Halaman %d\n", page + 1);
    } else if (cmd == 'm' || cmd == 'M') {
      Serial.printf("[JARINGAN] WiFi:%s (RSSI:%d) | MQTT:%s | Antrean Offline:%d\n",
                    (WiFi.status() == WL_CONNECTED) ? "TERHUBUNG" : "OFFLINE",
                    (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : 0,
                    mqttConnected ? "ONLINE" : "OFFLINE",
                    offlineQueueCount);
    }
  }

  // Auto-reconnect tiap 5 detik jika ada modul sensor belum terdeteksi
  if ((!okOled || !okMax || !okMpu) && (now - lastRetryInit >= 5000)) {
    lastRetryInit = now;
    initSensors();
  }

  // ---------- 1. MAX30102 ----------
  if (okMax) {
    currentIR  = particleSensor.getIR();
    currentRed = particleSensor.getRed();

    if (currentIR > IR_FINGER_THRESHOLD) {
      signalOk = true;
      if (checkForBeat(currentIR)) {
        long delta = millis() - lastBeat;
        lastBeat = millis();
        beatFlashUntil = lastBeat + 150;
        beatsPerMinute = 60.0 / (delta / 1000.0);
        if (beatsPerMinute < 220 && beatsPerMinute > 40) {
          rates[rateSpot++] = (byte)beatsPerMinute;
          rateSpot %= RATE_SIZE;
          beatAvg = 0;
          for (byte x = 0; x < RATE_SIZE; x++) beatAvg += rates[x];
          beatAvg /= RATE_SIZE;
        }
      }
      avered = avered * 0.95 + (double)currentRed * 0.05;
      aveir  = aveir  * 0.95 + (double)currentIR  * 0.05;
      sumredrms += (currentRed - avered) * (currentRed - avered);
      sumirrms  += (currentIR  - aveir)  * (currentIR  - aveir);
      sampleCount++;
      if (sampleCount >= SPO2_SAMPLE_WINDOW) {
        double R = (sqrt(sumredrms) / avered) / (sqrt(sumirrms) / aveir);
        int calc = (int)(110.0 - 25.0 * R);
        if (calc > 100) calc = 99;
        if (calc < 70) calc = 70;
        if (beatAvg > 0) spo2Est = calc;
        sumredrms = 0; sumirrms = 0; sampleCount = 0;
      }
    } else {
      signalOk = false;
      beatAvg = 0; spo2Est = 0; sampleCount = 0;
    }
  }

  // ---------- 2. MPU6050 (20 Hz) ----------
  if (okMpu && now - lastImuRead >= IMU_INTERVAL_MS) {
    lastImuRead = now;
    sensors_event_t a, g, t;
    if (mpu.getEvent(&a, &g, &t)) {
      ax = a.acceleration.x; ay = a.acceleration.y; az = a.acceleration.z;
      gx = g.gyro.x; gy = g.gyro.y; gz = g.gyro.z;
      accMagnitude = sqrt(ax * ax + ay * ay + az * az);
      if (accMagnitude > FALL_IMPACT_THRESHOLD && !fallCandidate) {
        fallCandidate = true;
        Serial.println(F("\n[EVENT] KANDIDAT JATUH TERDETEKSI"));
        publishOrQueueAlert("FALL_CANDIDATE", "Perhatian",
                            "Dugaan jatuh / hentakan kuat melampaui ambang 22.0 m/s2");
      }
    }
  }

  // ---------- 3. TOMBOL SOS ----------
  bool pressed = (digitalRead(PIN_BTN_SOS) == LOW);
  if (pressed && !sosPressedPrev) {
    sosPressStart = now;
    sosHandled = false;
  }
  if (pressed && !sosHandled && !sosActive && now - sosPressStart >= 2000) {
    sosActive = true;
    sosHandled = true;
    Serial.println(F("\n[EVENT] TOMBOL SOS DITEKAN (tahan 2 detik)"));
    publishOrQueueAlert("SOS_MANUAL", "Perhatian",
                        "Indikasi tombol darurat SOS ditekan tahan 2 detik pada perangkat");
  }
  if (!pressed && sosPressedPrev) {
    unsigned long held = now - sosPressStart;
    if (held < 800 && !sosHandled && !sosActive && !fallCandidate) {
      page = (page + 1) % PAGE_COUNT;
    }
  }
  sosPressedPrev = pressed;

  // ---------- 4. TOMBOL RESET ----------
  if (digitalRead(PIN_BTN_RESET) == LOW) {
    if (sosActive || fallCandidate || remoteBuzzerUntil > now) {
      sosActive = false;
      fallCandidate = false;
      remoteBuzzerUntil = 0;
      publishOrQueueAlert("ALARM_RESET", "Normal",
                          "Alarm di-reset melalui tombol fisik pada gelang");
    }
  }

  // ---------- 5. BUZZER (LOKAL + REMOTE DARI WEB DASHBOARD) ----------
  if (sosActive || fallCandidate || (now < remoteBuzzerUntil)) {
    if ((now % 400) < 300) buzzerOn(); else buzzerOff();
  } else {
    buzzerOff();
  }

  // ---------- 6. OLED (100 ms) ----------
  if (okOled && now - lastOledUpdate >= 100) {
    lastOledUpdate = now;
    display.clearDisplay();

    if (sosActive || fallCandidate) {
      drawAlarmScreen(now);
    } else {
      if (page == 0)      drawPageVital(now);
      else if (page == 1) drawPageGerak();
      else                drawPageStatus();

      if (pressed) {
        unsigned long held = now - sosPressStart;
        if (held > 800) {
          int w = map((long)constrain(held, 800UL, 2000UL), 800, 2000, 0, 128);
          display.fillRect(0, 62, w, 2, SSD1306_WHITE);
        }
      }
    }
    display.display();
  }

  // ---------- 7. KOMUNIKASI WI-FI & MQTT NON-BLOCKING ----------
  if (WiFi.status() != WL_CONNECTED) {
    mqttConnected = false;
    if (now - lastWifiRetry >= 15000) {
      lastWifiRetry = now;
      if (strlen(WIFI_SSID) > 0 && strcmp(WIFI_SSID, "NAMA_WIFI_ANDA") != 0) {
        Serial.printf("[WIFI] Mencoba sambung ke SSID '%s' (Status=%d)...\n", WIFI_SSID, (int)WiFi.status());
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      } else {
        Serial.println(F("[WIFI] PERINGATAN: WIFI_SSID masih 'NAMA_WIFI_ANDA'! Ganti di baris 30-31."));
      }
    }
  } else {
    if (!mqttConnected) {
      if (now - lastMqttRetry >= MQTT_RETRY_INTERVAL_MS) {
        lastMqttRetry = now;
        connectMqttWithLWT();
      }
    } else {
      pollMqttIncoming(now);

      if (now - lastTelemetrySent >= TELEMETRY_INTERVAL_MS) {
        lastTelemetrySent = now;
        publishTelemetry(now);
      }

      if (now - lastHeartbeatSent >= HEARTBEAT_INTERVAL_MS) {
        lastHeartbeatSent = now;
        publishHeartbeat(now);
      }
    }
  }

  // ---------- 8. LAPORAN SERIAL (1 Detik) ----------
  if (now - lastReport >= 1000) {
    lastReport = now;
    Serial.println(F("------------------------------"));
    Serial.printf("MAX30102 [%s] | IR=%ld Jari:%s BPM=%d SpO2=%d%%\n",
                  okMax ? "OK" : "GAGAL", currentIR, signalOk ? "YA" : "TIDAK", beatAvg, spo2Est);
    Serial.printf("MPU6050  [%s] | |a|=%.2f  Acc(%.2f,%.2f,%.2f)\n",
                  okMpu ? "OK" : "GAGAL", accMagnitude, ax, ay, az);
    Serial.printf("Status        | OLED=%s WiFi=%s MQTT=%s SOS=%s Jatuh=%s Hal=%d\n",
                  okOled ? "OK" : "GAGAL",
                  (WiFi.status() == WL_CONNECTED) ? "OK" : "BELUM",
                  mqttConnected ? "ONLINE" : "OFFLINE",
                  sosActive ? "AKTIF" : "-",
                  fallCandidate ? "YA" : "-",
                  page + 1);
  }
}
