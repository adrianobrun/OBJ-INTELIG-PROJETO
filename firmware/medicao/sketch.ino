// PMS5003 -> UART1 -> ESP32-S3 -> OLED e buzzer.
// Limite de 50 ug/m3 exclusivamente experimental; nao e um padrao de seguranca.
#include <Arduino.h>
#include <atomic>
#include <string.h>
#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <esp_random.h>
#include <esp_timer.h>
#include <freertos/queue.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#if __has_include(<esp_arduino_version.h>)
#include <esp_arduino_version.h>
#endif

constexpr uint8_t PMS_RX = 17;
constexpr uint8_t PMS_TX = 18;  // Reservado; sem fio externo nesta montagem.
constexpr uint8_t BUZZER_PIN = 21;
constexpr uint8_t ACT_MARK_PIN = 4;
constexpr uint8_t SYNC_MARK_PIN = 5;
constexpr uint16_t PM25_LIMIT = 50;
constexpr uint16_t BUZZER_HZ = 4000;
constexpr uint32_t SAMPLE_TIMEOUT_MS = 5000;
constexpr uint32_t BYTE_TIMEOUT_MS = 200;
HardwareSerial pmsUart(1);
Adafruit_SSD1306 display(128, 64, &Wire, -1);
bool oledReady = false;
uint32_t lastDisplayMs = 0;

uint8_t frame[32];
uint8_t frameSize = 0;
uint16_t pm1 = 0, pm25 = 0, pm10 = 0;
uint32_t validFrames = 0, rejectedFrames = 0;
uint32_t lastByteMs = 0, lastSampleMs = 0;
bool hasSample = false, timeoutReported = false;
bool buzzerOn = false;

struct Sample {
  uint32_t seq;
  uint32_t capturedMs;
  uint16_t pm1;
  uint16_t pm25;
  uint16_t pm10;
};
QueueHandle_t latestSample = nullptr;

struct BuzzerCommand {
  uint32_t session;
  uint32_t id;
  uint32_t durationMs;
};

struct BuzzerEvent {
  BuzzerCommand command;
  const char *state;
  uint32_t uptimeMs;
  bool buzzerOn;
  bool alert;
};

QueueHandle_t buzzerCommands = nullptr;
QueueHandle_t buzzerEvents = nullptr;
std::atomic<uint32_t> commandSession{0};
std::atomic<uint8_t> outputFlags{0};
BuzzerCommand activeTest{};
bool actLevel = false;
uint32_t testEndsMs = 0;

uint16_t readU16(const uint8_t *data) {
  return (uint16_t(data[0]) << 8) | data[1];
}

bool sampleIsCurrent() {
  return hasSample && uint32_t(millis() - lastSampleMs) < SAMPLE_TIMEOUT_MS;
}

bool exceedsLimit(uint16_t concentration) {
  return concentration > PM25_LIMIT;
}

void drawDisplay() {
  if (!oledReady) return;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("AIR QUALITY MONITOR");
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);
  if (!sampleIsCurrent()) {
    display.setCursor(0, 24);
    display.println(hasSample ? "SENSOR: SEM DADOS" : "AGUARDANDO PMS5003");
    display.setCursor(0, 42);
    display.println("UART1 RX17 9600 8N1");
  } else {
    display.setCursor(0, 18);
    display.print("PM1.0 : "); display.print(pm1); display.println(" ug/m3");
    display.setCursor(0, 30);
    display.print("PM2.5 : "); display.print(pm25); display.println(" ug/m3");
    display.setCursor(0, 42);
    display.print("PM10  : "); display.print(pm10); display.println(" ug/m3");
    display.setCursor(0, 55);
    display.print("STATUS: ");
    display.print(exceedsLimit(pm25) ? "ALERTA" : (activeTest.id ? "TESTE" : "NORMAL"));
  }
  display.display();
}

void updateAlarm() {
  // A perda de dados e mostrada como erro de sensor, sem reutilizar uma
  // concentracao antiga indefinidamente. O alerta sonoro desliga apos 5 s.
  bool current = sampleIsCurrent();
  const bool testing = activeTest.id != 0;
  bool shouldSound = testing || (current && exceedsLimit(pm25));
  outputFlags.store((testing ? 1 : 0) | (shouldSound ? 2 : 0));
  if (shouldSound == buzzerOn) return;
  buzzerOn = shouldSound;
  if (buzzerOn) {
    int64_t markBefore = 0;
    int64_t markAfter = 0;
    if (testing) {
      actLevel = !actLevel;
      markBefore = esp_timer_get_time();
      digitalWrite(ACT_MARK_PIN, actLevel);
      markAfter = esp_timer_get_time();
    }
    tone(BUZZER_PIN, BUZZER_HZ);
    if (testing) {
      Serial0.printf("PILOT ACT id=%lu session=%lu level=%u before_us=%lld after_us=%lld\n",
                     (unsigned long)activeTest.id, (unsigned long)activeTest.session,
                     unsigned(actLevel), (long long)markBefore, (long long)markAfter);
    }
  } else {
    noTone(BUZZER_PIN);
    digitalWrite(BUZZER_PIN, LOW);
  }
  Serial0.printf("BUZZER=%s PM2.5=%u freq=%u Hz t=%lu ms%s\n",
                 buzzerOn ? "ON" : "OFF", pm25, buzzerOn ? BUZZER_HZ : 0,
                 (unsigned long)millis(), current ? "" : " (SEM DADOS)");
}

void recordBuzzerEvent(const BuzzerCommand &command, const char *state) {
  const BuzzerEvent event{command, state, millis(), buzzerOn,
                          sampleIsCurrent() && exceedsLimit(pm25)};
  Serial0.printf("BUZZER TEST id=%lu state=%s duration_ms=%lu t=%lu buzzer_on=%u alert=%u\n",
                 (unsigned long)command.id, state, (unsigned long)command.durationMs,
                 (unsigned long)event.uptimeMs, unsigned(event.buzzerOn), unsigned(event.alert));
  if (xQueueSend(buzzerEvents, &event, 0) != pdTRUE) {
    Serial0.println("MQTT fila de eventos cheia");
  }
}

void serviceBuzzerTest() {
  const uint32_t now = millis();
  if (activeTest.id && int32_t(now - testEndsMs) >= 0) {
    const BuzzerCommand finished = activeTest;
    activeTest = {};
    updateAlarm();
    recordBuzzerEvent(finished, "finished");
  }
  BuzzerCommand pending;
  if (!buzzerCommands || xQueueReceive(buzzerCommands, &pending, 0) != pdTRUE
      || pending.session != commandSession.load()) return;
  if (activeTest.id) {
    recordBuzzerEvent(pending, "busy");
    return;
  }
  activeTest = pending;
  testEndsMs = millis() + pending.durationMs;
  updateAlarm();
  recordBuzzerEvent(pending, "started");
}

void acceptFrame() {
  // Campos atmosfericos (bytes 10..15), em ug/m3.
  pm1 = readU16(frame + 10);
  pm25 = readU16(frame + 12);
  pm10 = readU16(frame + 14);
  lastSampleMs = millis();
  hasSample = true;
  timeoutReported = false;
  ++validFrames;
  updateAlarm();
  if (latestSample) {
    const Sample sample{validFrames, lastSampleMs, pm1, pm25, pm10};
    xQueueOverwrite(latestSample, &sample);
  }
  Serial0.printf("FRAME OK n=%lu len=28 PM1.0=%u PM2.5=%u PM10=%u ug/m3\n",
                 (unsigned long)validFrames, pm1, pm25, pm10);
  if (validFrames == 1) {
    Serial0.print("RAW32:");
    for (uint8_t byte : frame) Serial0.printf(" %02X", byte);
    Serial0.println();
  }
}

void dropFirstByte() {
  --frameSize;
  memmove(frame, frame + 1, frameSize);
}

void readSensor() {
  while (pmsUart.available()) {
    uint32_t now = millis();
    if (frameSize && uint32_t(now - lastByteMs) > BYTE_TIMEOUT_MS) frameSize = 0;
    lastByteMs = now;
    frame[frameSize++] = uint8_t(pmsUart.read());

    // Busca deslizante: recupera cabecalhos dentro de dados corrompidos.
    while (frameSize) {
      if (frame[0] != 0x42 || (frameSize >= 2 && frame[1] != 0x4D)) {
        dropFirstByte();
        continue;
      }
      if (frameSize < 4) break;
      if (readU16(frame + 2) != 28) {
        ++rejectedFrames;
        Serial0.println("REJECT comprimento (esperado 28)");
        dropFirstByte();
        continue;
      }
      if (frameSize < sizeof(frame)) break;
      uint16_t checksum = 0;
      for (uint8_t i = 0; i < 30; ++i) checksum += frame[i];
      if (checksum != readU16(frame + 30)) {
        ++rejectedFrames;
        Serial0.printf("REJECT checksum esperado=%04X recebido=%04X rejeitados=%lu\n",
                       checksum, readU16(frame + 30), (unsigned long)rejectedFrames);
        dropFirstByte();
        continue;
      }
      acceptFrame();
      frameSize = 0;
    }
  }
}

void publishTelemetry(PubSubClient &mqtt, const char *topic, const char *clientId,
                      uint32_t seq) {
  Sample sample{};
  const bool hasReading = xQueuePeek(latestSample, &sample, 0) == pdTRUE;
  const uint32_t now = millis();
  const bool valid = hasReading && uint32_t(now - sample.capturedMs) < SAMPLE_TIMEOUT_MS;
  const bool alert = valid && exceedsLimit(sample.pm25);

  char reading[76] = "\"sample_seq\":null,\"pm1\":null,\"pm25\":null,\"pm10\":null";
  if (valid) {
    snprintf(reading, sizeof(reading), "\"sample_seq\":%lu,\"pm1\":%u,\"pm25\":%u,\"pm10\":%u",
             (unsigned long)sample.seq, sample.pm1, sample.pm25, sample.pm10);
  }
  char payload[256];
  const uint8_t flags = outputFlags.load();
  const int length = snprintf(
      payload, sizeof(payload),
      "{\"version\":\"a4-2a-autoteste\",\"client_id\":\"%s\",\"seq\":%lu,\"uptime_ms\":%lu,"
      "\"unit\":\"ug/m3\",%s,\"sample_valid\":%s,\"alert\":%s,\"test_active\":%s,\"buzzer_on\":%s}",
      clientId, (unsigned long)seq, (unsigned long)now, reading,
      valid ? "true" : "false", alert ? "true" : "false",
      (flags & 1) ? "true" : "false", (flags & 2) ? "true" : "false");
  if (length < 0 || size_t(length) >= sizeof(payload) || !mqtt.publish(topic, payload, false)) {
    Serial0.printf("MQTT TELEMETRY FALHOU seq=%lu\n", (unsigned long)seq);
    return;
  }
  Serial0.printf("MQTT TELEMETRY %s %s\n", topic, payload);
}

bool readDecimal(const uint8_t *&cursor, const uint8_t *end, uint32_t &value) {
  const uint8_t *start = cursor;
  value = 0;
  while (cursor != end && *cursor >= '0' && *cursor <= '9') {
    const uint32_t digit = *cursor++ - '0';
    if (value > (UINT32_MAX - digit) / 10) return false;
    value = value * 10 + digit;
  }
  return cursor != start;
}

bool parseBuzzerCommand(const uint8_t *data, unsigned length, BuzzerCommand &command) {
  constexpr char PREFIX[] = "test,";
  constexpr size_t PREFIX_LENGTH = sizeof(PREFIX) - 1;
  if (length <= PREFIX_LENGTH || length > 20 || memcmp(data, PREFIX, PREFIX_LENGTH)) return false;
  const uint8_t *cursor = data + PREFIX_LENGTH;
  const uint8_t *end = data + length;
  return readDecimal(cursor, end, command.id) && command.id > 0
      && cursor != end && *cursor++ == ','
      && readDecimal(cursor, end, command.durationMs) && cursor == end
      && command.durationMs >= 100 && command.durationMs <= 1500;
}

void publishBuzzerEvents(PubSubClient &mqtt, const char *topic, const char *clientId) {
  BuzzerEvent event;
  while (xQueueReceive(buzzerEvents, &event, 0) == pdTRUE) {
    if (event.command.session != commandSession.load()) continue;
    char payload[200];
    snprintf(payload, sizeof(payload),
             "{\"client_id\":\"%s\",\"session\":%lu,\"id\":%lu,\"state\":\"%s\","
             "\"duration_ms\":%lu,\"uptime_ms\":%lu,\"buzzer_on\":%s,\"alert\":%s}",
             clientId, (unsigned long)event.command.session, (unsigned long)event.command.id,
             event.state, (unsigned long)event.command.durationMs, (unsigned long)event.uptimeMs,
             event.buzzerOn ? "true" : "false", event.alert ? "true" : "false");
    if (!mqtt.publish(topic, payload, false)) Serial0.println("MQTT evento de buzzer falhou");
  }
}

void networkTask(void *) {
  constexpr char BROKER[] = "broker.emqx.io";
  constexpr uint16_t PORT = 1883;
  constexpr char TELEMETRY_TOPIC[] = "obj-intelig-projeto/a4/47db91f2/telemetry";
  constexpr char STATUS_TOPIC[] = "obj-intelig-projeto/a4/47db91f2/status";
  constexpr char COMMAND_PREFIX[] = "obj-intelig-projeto/a4/47db91f2/command";
  constexpr char EVENT_TOPIC[] = "obj-intelig-projeto/a4/47db91f2/command-event";
  constexpr uint32_t TELEMETRY_INTERVAL_MS = 5000;
  constexpr uint32_t RETRY_INTERVAL_MS = 5000;
  constexpr int32_t TCP_TIMEOUT_MS = 1500;

  WiFiClient tcp;
  PubSubClient mqtt(tcp);
  if (!mqtt.setBufferSize(384)) {
    Serial0.println("ERRO ao alocar buffer MQTT");
    vTaskDelete(nullptr);
    return;
  }
  mqtt.setSocketTimeout(2);
  mqtt.setKeepAlive(8);

  char clientId[24];
  snprintf(clientId, sizeof(clientId), "a4-47db91f2-%08lx", (unsigned long)esp_random());
  char online[200];
  char offline[72];
  char commandTopic[96] = "";
  snprintf(offline, sizeof(offline), "{\"client_id\":\"%s\",\"online\":false}", clientId);

  uint32_t connectionNumber = 0;
  uint32_t lastCommandId = 0;
  bool syncLevel = false;
  uint32_t syncId = 0;
  int64_t syncBefore = 0, syncAfter = 0;
  mqtt.setCallback([&](char *topic, uint8_t *payload, unsigned length) {
    BuzzerCommand request{};
    request.session = commandSession.load();
    if (!request.session || strcmp(topic, commandTopic)) return;
    constexpr char SYNC[] = "sync,";
    if (length > sizeof(SYNC) - 1 && !memcmp(payload, SYNC, sizeof(SYNC) - 1)) {
      const uint8_t *pos = payload + sizeof(SYNC) - 1;
      const uint8_t *end = payload + length;
      uint32_t id = 0;
      if (readDecimal(pos, end, id) && pos == end && id) {
        syncLevel = !syncLevel;
        syncBefore = esp_timer_get_time();
        digitalWrite(SYNC_MARK_PIN, syncLevel);
        syncAfter = esp_timer_get_time();
        syncId = id;
      }
      return;
    }
    if (!parseBuzzerCommand(payload, length, request)) {
      Serial0.println("MQTT COMANDO INVALIDO");
      return;
    }
    if (request.id <= lastCommandId) {
      Serial0.printf("MQTT COMANDO REPETIDO id=%lu\n", (unsigned long)request.id);
      return;
    }
    lastCommandId = request.id;
    if (xQueueSend(buzzerCommands, &request, 0) != pdTRUE) {
      Serial0.printf("MQTT COMANDO FILA CHEIA id=%lu\n", (unsigned long)request.id);
    }
  });

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin("Wokwi-GUEST", "", 6);
  Serial0.println("WIFI conectando a Wokwi-GUEST");

  bool wifiOnline = false;
  bool mqttOnline = false;
  uint32_t nextPublishMs = 0;
  uint32_t telemetrySeq = 0;
  uint32_t nextAttemptMs = 0;
#ifdef A4_TEST_NETWORK
  // Instrumentacao local do Wokwi. X corta o TCP; R restaura o destino.
  bool blockBroker = true;
  Serial0.println("TEST MQTT bloqueado no inicio; X=cortar, R=restaurar");
#endif
  for (;;) {
#ifdef A4_TEST_NETWORK
    const int command = Serial0.read();
    if (command == 'X' || command == 'R') {
      blockBroker = command == 'X';
      if (blockBroker) tcp.stop();
      nextAttemptMs = millis();
      Serial0.printf("TEST MQTT %s t=%lu ms\n",
                     blockBroker ? "bloqueado" : "liberado", (unsigned long)millis());
    }
#endif
    const bool wifiConnected = WiFi.status() == WL_CONNECTED;
    if (wifiConnected != wifiOnline) {
      wifiOnline = wifiConnected;
      if (wifiOnline) {
        Serial0.printf("WIFI OK ip=%s\n", WiFi.localIP().toString().c_str());
        nextAttemptMs = millis();
      } else {
        Serial0.println("WIFI desconectado");
        tcp.stop();
      }
    }

    const bool connected = wifiOnline && mqtt.loop();
    if (mqttOnline && !connected) {
      mqttOnline = false;
      commandSession.store(0);
      Serial0.printf("MQTT DESCONECTADO t=%lu ms\n", (unsigned long)millis());
    }
    if (connected) {
      if (syncId) {
        char response[184];
        snprintf(response, sizeof(response),
                 "{\"client_id\":\"%s\",\"session\":%lu,\"id\":%lu,\"level\":%u,"
                 "\"before_us\":%lld,\"after_us\":%lld}",
                 clientId, (unsigned long)commandSession.load(), (unsigned long)syncId,
                 unsigned(syncLevel), (long long)syncBefore, (long long)syncAfter);
        mqtt.publish("obj-intelig-projeto/a4/47db91f2/pilot-sync", response, false);
        syncId = 0;
      }
      publishBuzzerEvents(mqtt, EVENT_TOPIC, clientId);
      const uint32_t now = millis();
      if (int32_t(now - nextPublishMs) >= 0) {
        nextPublishMs = now + TELEMETRY_INTERVAL_MS;
        publishTelemetry(mqtt, TELEMETRY_TOPIC, clientId, ++telemetrySeq);
      }
    } else if (wifiOnline && int32_t(millis() - nextAttemptMs) >= 0) {
      IPAddress address;
      if (!WiFi.hostByName(BROKER, address)) {
        Serial0.printf("DNS FALHOU %s\n", BROKER);
      } else {
#ifdef A4_TEST_NETWORK
        // TEST-NET-1 representa um destino indisponivel sem alterar o broker.
        if (blockBroker) address = IPAddress(192, 0, 2, 1);
#endif
        if (!tcp.connect(address, PORT, TCP_TIMEOUT_MS)) {
          Serial0.printf("TCP FALHOU ip=%s porta=%u t=%lu ms\n",
                         address.toString().c_str(), PORT, (unsigned long)millis());
        } else {
          const uint32_t session = ++connectionNumber;
          snprintf(commandTopic, sizeof(commandTopic), "%s/%s-%lu", COMMAND_PREFIX,
                   clientId, (unsigned long)session);
          snprintf(online, sizeof(online),
                   "{\"client_id\":\"%s\",\"online\":true,\"session\":%lu,\"command_topic\":\"%s\"}",
                   clientId, (unsigned long)session, commandTopic);
          if (mqtt.setServer(address, PORT).connect(clientId, STATUS_TOPIC, 1, true, offline)
              && mqtt.subscribe(commandTopic, 0) && mqtt.publish(STATUS_TOPIC, online, true)) {
            lastCommandId = 0;
            commandSession.store(session);
            mqttOnline = true;
            nextPublishMs = millis();
            Serial0.printf("MQTT CONNACK OK client_id=%s t=%lu ms\n",
                           clientId, (unsigned long)nextPublishMs);
            Serial0.printf("MQTT COMANDO TOPICO %s\n", commandTopic);
          } else {
            Serial0.printf("MQTT FALHOU state=%d\n", mqtt.state());
            tcp.stop();
          }
        }
      }
      nextAttemptMs = millis() + RETRY_INTERVAL_MS;
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

void setup() {
  Serial0.begin(115200);
  pinMode(ACT_MARK_PIN, OUTPUT);
  digitalWrite(ACT_MARK_PIN, LOW);
  pinMode(SYNC_MARK_PIN, OUTPUT);
  digitalWrite(SYNC_MARK_PIN, LOW);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  pmsUart.setRxBufferSize(256);
  pmsUart.begin(9600, SERIAL_8N1, PMS_RX, PMS_TX);
  Serial0.println("PMS5003 | ESP32-S3 | UART1 RX=17 TX=18 | 9600 8N1");
#ifdef ESP_ARDUINO_VERSION_STR
  Serial0.printf("Arduino-ESP32 %s | ESP-IDF %s\n", ESP_ARDUINO_VERSION_STR, ESP.getSdkVersion());
#endif
  Serial0.println("BUZZER=OFF GPIO21 | experimental: PM2.5 > 50 ug/m3 | 4000 Hz");
  Wire.begin(8, 9);  // S3: SDA=8 e SCL=9; GPIO21 fica reservado ao buzzer.
  Wire.setClock(400000);
  oledReady = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  Serial0.println(oledReady ? "OLED OK SDA=8 SCL=9 addr=0x3C" : "ERRO OLED");
  drawDisplay();
  // DNS, TCP e CONNACK podem esperar sem bloquear o tratamento local da UART.
  latestSample = xQueueCreate(1, sizeof(Sample));
  buzzerCommands = xQueueCreate(1, sizeof(BuzzerCommand));
  buzzerEvents = xQueueCreate(4, sizeof(BuzzerEvent));
  if (!latestSample || !buzzerCommands || !buzzerEvents
      || xTaskCreate(networkTask, "mqtt", 6144, nullptr, 1, nullptr) != pdPASS) {
    Serial0.println("ERRO ao iniciar tarefa MQTT");
  }
}

void loop() {
  readSensor();
  serviceBuzzerTest();
  updateAlarm();
  if (hasSample && !sampleIsCurrent() && !timeoutReported) {
    timeoutReported = true;
    if (latestSample) xQueueReset(latestSample);
    Serial0.println("TIMEOUT: sem quadro valido ha 5 s");
  }
  if (uint32_t(millis() - lastDisplayMs) >= 200) {
    lastDisplayMs = millis();
    drawDisplay();
  }
  delay(1);
}
