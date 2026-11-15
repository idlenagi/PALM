#include <WiFi.h>
#include <ArduinoMqttClient.h>
#include <ArduinoJson.h>
#include "esp_timer.h"
#include "secrets.h"            // WIFI_SSID / WIFI_PASS (git-ignored)

// ---------------- CONFIG ----------------
const char broker[]      = "***.***.***";   // Mosquitto on the laptop
const int  port          = 1883;
const char CLIENT_ID[]   = "smg-esp32";
const char BROKER_TAG[]  = "mosquitto-local"; // logged at boot

// BENCHMARK_MODE = true  -> pure echo node for Phase 1/2 measurements:
//   no telemetry publishing, no LED/buzzer handling, no button publishing.
// BENCHMARK_MODE = false -> demo mode (LEDs, buzzer, button, telemetry on).
const bool BENCHMARK_MODE = false;

const bool    BEEP_ON_SELECT = true;  // only used when BENCHMARK_MODE = false
const uint8_t BUTTON_QOS     = 1;
uint8_t       echoQos        = 0;      // change at runtime: cmd qos0 / qos1

const unsigned long SERIAL_BAUD = 921600;   // match PySerial

const int BUTTON_PIN = 4;
const int BUZZER_PIN = 27;
const int LED1_PIN   = 25;  // 1 star
const int LED2_PIN   = 26;  // 2 stars
const int LED3_PIN   = 32;  // 3 stars

// ---------------- Topics ----------------
const char T_EVENT[]  = "smg/phone/event";
const char T_CMD[]    = "smg/esp32/cmd";
const char T_ECHO[]   = "smg/esp32/echo";
const char T_BUTTON[] = "smg/esp32/button";
const char T_STATUS[] = "smg/esp32/status";
const char T_TELEM[]  = "smg/esp32/telemetry";
const char T_RSSI[]   = "smg/esp32/rssi";
const char T_LOST[]   = "smg/esp32/lost";
const char T_JITTER[] = "smg/esp32/jitter_ms";
const char T_RX[]     = "smg/esp32/rx";

WiFiClient wifiClient;
MqttClient mqttClient(wifiClient);

// 64-bit microsecond clock (never wraps in practice)
static inline uint64_t nowUs() { return (uint64_t)esp_timer_get_time(); }

// ---------------- Incoming message queue ----------------
struct Msg {
  char     topic[32];
  char     data[256];
  uint16_t len;
  uint32_t arrivalUs;
};
const int QCAP = 8;
Msg queueBuf[QCAP];
int qHead = 0, qTail = 0, qCount = 0;

// Explicit prototype prevents Arduino auto-prototype generator error
void handleEvent(Msg& m);

// ---------------- Measurement state ----------------
bool     haveSeq = false;
uint32_t expectedSeq = 0;
uint32_t rxCnt = 0, lostCnt = 0, dupCnt = 0, oooCnt = 0, parseErr = 0, qDrops = 0;
uint32_t lastArrivalUs = 0, lastInterUs = 0, prevInterUs = 0;
float    jitterUs = 0;
uint32_t wifiDrops = 0, mqttDrops = 0;
uint32_t loopMaxUs = 0;
bool     wasWifi = false, wasMqtt = false;
uint32_t wifiDownSince = 0, mqttDownSince = 0;
char     runLabel[32] = "unlabeled";

// ---------------- Button ----------------
int buttonState = HIGH, lastReading = HIGH;
unsigned long lastDebounceTime = 0;
const unsigned long debounceDelay = 50;
uint32_t btnSeq = 0;

// ---------------- Buzzer (non-blocking) ----------------
int      beepsLeft = 0;
bool     beepOn = false;
uint32_t beepOnMs = 100, beepOffMs = 100, nextBeepAt = 0;

void startBeeps(int n, uint32_t onMs, uint32_t offMs, bool force) {
  if (!force && (beepsLeft > 0 || beepOn)) return;
  beepsLeft = n; beepOnMs = onMs; beepOffMs = offMs;
  beepOn = false; nextBeepAt = millis();
}

void updateBeeper() {
  if (!beepOn && beepsLeft <= 0) return;
  if ((int32_t)(millis() - nextBeepAt) < 0) return;
  if (!beepOn) {
    digitalWrite(BUZZER_PIN, HIGH);
    beepOn = true;
    nextBeepAt = millis() + beepOnMs;
  } else {
    digitalWrite(BUZZER_PIN, LOW);
    beepOn = false;
    beepsLeft--;
    nextBeepAt = millis() + beepOffMs;
  }
}

// ---------------- LEDs ----------------
void resetLEDs() {
  digitalWrite(LED1_PIN, LOW);
  digitalWrite(LED2_PIN, LOW);
  digitalWrite(LED3_PIN, LOW);
}

void setStarLeds(int stars) {
  digitalWrite(LED1_PIN, stars >= 1 ? HIGH : LOW);
  digitalWrite(LED2_PIN, stars >= 2 ? HIGH : LOW);
  digitalWrite(LED3_PIN, stars >= 3 ? HIGH : LOW);
}

// ---------------- Helpers ----------------
// All timestamps are microseconds since boot (64-bit).
void logSys(const char* ev, long value) {
  Serial.printf("sys,%llu,%s,%ld\n", (unsigned long long)nowUs(), ev, value);
}

void publishMsg(const char* topic, const char* payload, uint8_t qos = 0, bool retain = false) {
  mqttClient.beginMessage(topic, retain, qos);
  mqttClient.print(payload);
  mqttClient.endMessage();
}

// Copy a numeric field out of raw JSON text WITHOUT converting it, so the
// 13-digit t_phone is echoed back exactly.
bool extractNumber(const char* json, const char* key, char* out, size_t outSize) {
  char pat[24];
  snprintf(pat, sizeof(pat), "\"%s\"", key);
  const char* p = strstr(json, pat);
  if (!p) return false;
  p += strlen(pat);
  while (*p == ' ' || *p == ':') p++;
  size_t i = 0;
  while ((isdigit((unsigned char)*p) || *p == '-') && i < outSize - 1) out[i++] = *p++;
  out[i] = 0;
  return i > 0;
}

void resetStats() {
  haveSeq = false; expectedSeq = 0;
  rxCnt = lostCnt = dupCnt = oooCnt = parseErr = qDrops = 0;
  lastArrivalUs = lastInterUs = prevInterUs = 0;
  jitterUs = 0; loopMaxUs = 0;
  logSys("stats_reset", 0);
}

// ---------------- MQTT receive callback (keep it tiny) ----------------
void onMqttMessage(int messageSize) {
  uint32_t arrivalUs = micros();   // timestamp as early as possible

  if (qCount >= QCAP) {
    qDrops++;
    while (mqttClient.available()) mqttClient.read();
    return;
  }
  Msg& m = queueBuf[qHead];
  strlcpy(m.topic, mqttClient.messageTopic().c_str(), sizeof(m.topic));
  uint16_t n = 0;
  while (mqttClient.available()) {
    int c = mqttClient.read();
    if (n < sizeof(m.data) - 1) m.data[n++] = (char)c;
  }
  m.data[n] = 0;
  m.len = n;
  m.arrivalUs = arrivalUs;
  qHead = (qHead + 1) % QCAP;
  qCount++;
}

// ---------------- Message processing (runs from loop) ----------------
void handleEvent(Msg& m) {
  // 1) ECHO FIRST
  char seqStr[16], tPhoneStr[24] = "0";
  if (!extractNumber(m.data, "seq", seqStr, sizeof(seqStr))) { parseErr++; return; }
  extractNumber(m.data, "t_phone", tPhoneStr, sizeof(tPhoneStr));
  uint32_t seq = strtoul(seqStr, nullptr, 10);

  uint32_t procUs = micros() - m.arrivalUs;   // arrival -> just before echo publish (goes in payload)
  char echo[96];
  snprintf(echo, sizeof(echo), "{\"seq\":%s,\"t_phone\":%s,\"proc_us\":%lu}",
           seqStr, tPhoneStr, (unsigned long)procUs);
  publishMsg(T_ECHO, echo, echoQos);
  uint32_t procFullUs = micros() - m.arrivalUs;   // arrival -> after publish call returns (serial log only)

  // 2) Sequence accounting (seq 0 = new run)
  if (seq == 0) { resetStats(); resetLEDs(); }
  if (!haveSeq)                    { haveSeq = true; expectedSeq = seq + 1; }
  else if (seq == expectedSeq)     { expectedSeq++; }
  else if (seq > expectedSeq)      { lostCnt += seq - expectedSeq; expectedSeq = seq + 1; }
  else if (seq == expectedSeq - 1) { dupCnt++; }
  else                             { oooCnt++; if (lostCnt > 0) lostCnt--; }
  rxCnt++;

  // 3) Inter-arrival and jitter
  uint32_t interUs = 0;
  if (lastArrivalUs) {
    interUs = m.arrivalUs - lastArrivalUs;
    if (prevInterUs) {
      int32_t d = (int32_t)interUs - (int32_t)prevInterUs;
      if (d < 0) d = -d;
      jitterUs += ((float)d - jitterUs) / 16.0f;
    }
    prevInterUs = interUs;
    lastInterUs = interUs;
  }
  lastArrivalUs = m.arrivalUs;

  // 4) LEDs / buzzer: skipped entirely in benchmark mode
  if (!BENCHMARK_MODE) {
    StaticJsonDocument<256> doc;
    if (!deserializeJson(doc, m.data, m.len)) {
      if (!doc["stars"].isNull()) {
        int stars = doc["stars"];
        setStarLeds(stars);
        startBeeps(stars > 0 ? stars : 1, 100, 100, true);
        Serial.printf("sys,%llu,win_stars,%d\n", (unsigned long long)nowUs(), stars);
      } else if (BEEP_ON_SELECT) {
        const char* ev = doc["event"] | "";
        if (strcmp(ev, "select") == 0) startBeeps(1, 30, 0, false);
      }
    } else {
      parseErr++;
    }
  }

  // 5) Log last (after echo is already out)
  Serial.printf("rx,%llu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%d\n",
                (unsigned long long)nowUs(), (unsigned long)seq,
                (unsigned long)interUs, (unsigned long)procUs,
                (unsigned long)procFullUs, (unsigned long)lostCnt,
                (unsigned long)dupCnt, (unsigned long)oooCnt,
                (unsigned long)qDrops, WiFi.RSSI());
}

// Commands (topic smg/esp32/cmd):
//   reset | qos0 | qos1 | test | run:<label>
void handleCmd(const char* c) {
  if (strcmp(c, "reset") == 0)      { resetStats(); resetLEDs(); }
  else if (strcmp(c, "qos0") == 0)  { echoQos = 0; logSys("echo_qos", 0); }
  else if (strcmp(c, "qos1") == 0)  { echoQos = 1; logSys("echo_qos", 1); }
  else if (strcmp(c, "test") == 0 && !BENCHMARK_MODE) { setStarLeds(3); startBeeps(3, 100, 100, true); }
  else if (strncmp(c, "run:", 4) == 0) {
    strlcpy(runLabel, c + 4, sizeof(runLabel));
    resetStats(); resetLEDs();
    Serial.printf("sys,%llu,run_label,%s\n", (unsigned long long)nowUs(), runLabel);
  }
}

void processQueue() {
  while (qCount > 0) {
    Msg& m = queueBuf[qTail];
    if (strcmp(m.topic, T_EVENT) == 0)    handleEvent(m);
    else if (strcmp(m.topic, T_CMD) == 0) handleCmd(m.data);
    qTail = (qTail + 1) % QCAP;
    qCount--;
  }
}

// ---------------- Connectivity ----------------
void tryConnectMqtt() {
  static uint32_t last = 0;
  if (millis() - last < 2000) return;
  last = millis();

  mqttClient.setId(CLIENT_ID);
  mqttClient.setKeepAliveInterval(15UL * 1000UL);
  mqttClient.beginWill(T_STATUS, true, 1);
  mqttClient.print("offline");
  mqttClient.endWill();

  if (!mqttClient.connect(broker, port)) {
    logSys("mqtt_connect_fail", mqttClient.connectError());
    return;
  }
  mqttClient.onMessage(onMqttMessage);
  mqttClient.subscribe(T_EVENT, 1);
  mqttClient.subscribe(T_CMD, 0);
  publishMsg(T_STATUS, "online", 1, true);
}

void trackConnectionState() {
  bool wifiUp = (WiFi.status() == WL_CONNECTED);
  if (wifiUp && !wasWifi) {
    if (wifiDownSince) logSys("wifi_reconnect_ms", millis() - wifiDownSince);
    else logSys("wifi_up", WiFi.RSSI());
    wifiDownSince = 0;
  } else if (!wifiUp && wasWifi) {
    wifiDrops++; wifiDownSince = millis(); logSys("wifi_down", 0);
  }
  wasWifi = wifiUp;

  bool mqttUp = wifiUp && mqttClient.connected();
  if (mqttUp && !wasMqtt) {
    if (mqttDownSince) logSys("mqtt_reconnect_ms", millis() - mqttDownSince);
    else logSys("mqtt_up", 0);
    mqttDownSince = 0;
  } else if (!mqttUp && wasMqtt) {
    mqttDrops++; mqttDownSince = millis(); logSys("mqtt_down", 0);
  }
  wasMqtt = mqttUp;
}

// ---------------- Telemetry (1 Hz, QoS 0) - demo mode only ----------------
void publishTelemetry() {
  static uint32_t last = 0;
  if (millis() - last < 1000) return;
  last = millis();

  char buf[224];
  snprintf(buf, sizeof(buf),
    "{\"rx\":%lu,\"lost\":%lu,\"dup\":%lu,\"ooo\":%lu,\"inter_ms\":%lu,\"jitter_ms\":%.2f,"
    "\"rssi\":%d,\"heap\":%lu,\"loop_max_us\":%lu,\"wifi_drops\":%lu,\"mqtt_drops\":%lu,\"q_drops\":%lu}",
    (unsigned long)rxCnt, (unsigned long)lostCnt, (unsigned long)dupCnt, (unsigned long)oooCnt,
    (unsigned long)(lastInterUs / 1000), jitterUs / 1000.0f, WiFi.RSSI(),
    (unsigned long)ESP.getFreeHeap(), (unsigned long)loopMaxUs,
    (unsigned long)wifiDrops, (unsigned long)mqttDrops, (unsigned long)qDrops);
  publishMsg(T_TELEM, buf, 0);

  char v[16];
  snprintf(v, sizeof(v), "%d", WiFi.RSSI());                      publishMsg(T_RSSI, v, 0);
  snprintf(v, sizeof(v), "%lu", (unsigned long)lostCnt);          publishMsg(T_LOST, v, 0);
  snprintf(v, sizeof(v), "%.1f", jitterUs / 1000.0f);             publishMsg(T_JITTER, v, 0);
  snprintf(v, sizeof(v), "%lu", (unsigned long)rxCnt);            publishMsg(T_RX, v, 0);

  loopMaxUs = 0;
}

// ---------------- Button - demo mode only ----------------
void handleButton() {
  int reading = digitalRead(BUTTON_PIN);
  if (reading != lastReading) lastDebounceTime = millis();

  if ((millis() - lastDebounceTime) > debounceDelay && reading != buttonState) {
    buttonState = reading;
    if (buttonState == LOW) {
      if (mqttClient.connected()) {
        char buf[80];
        snprintf(buf, sizeof(buf), "{\"btn\":\"hint\",\"seq\":%lu,\"t_esp_ms\":%lu}",
                 (unsigned long)btnSeq++, millis());
        publishMsg(T_BUTTON, buf, BUTTON_QOS);
      }
      logSys("button", btnSeq);
      resetLEDs();
      startBeeps(1, 50, 0, true);
    }
  }
  lastReading = reading;
}

// ---------------- Arduino entry points ----------------
void setup() {
  Serial.begin(SERIAL_BAUD);

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED1_PIN, OUTPUT);
  pinMode(LED2_PIN, OUTPUT);
  pinMode(LED3_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  resetLEDs();

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);          // modem sleep adds latency and jitter
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.printf("sys,0,broker,%s\n", BROKER_TAG);
  Serial.printf("sys,0,mode,%s\n", BENCHMARK_MODE ? "benchmark" : "demo");
  Serial.println("sys,0,csv,rx=t_us/seq/interarrival_us/proc_us/proc_full_us/lost/dup/ooo/qdrops/rssi");
}

void loop() {
  uint32_t t0 = micros();

  trackConnectionState();

  if (WiFi.status() == WL_CONNECTED) {
    if (!mqttClient.connected()) {
      tryConnectMqtt();
    } else {
      mqttClient.poll();
      processQueue();
    }
  }

  if (!BENCHMARK_MODE) {
    handleButton();
    updateBeeper();
    if (mqttClient.connected()) publishTelemetry();
  }

  uint32_t dt = micros() - t0;
  if (dt > loopMaxUs) loopMaxUs = dt;
}

