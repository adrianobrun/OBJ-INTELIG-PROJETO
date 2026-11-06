// PMS5003 -> UART1 -> ESP32-S3 -> OLED e buzzer.
// Limite de 50 ug/m3 exclusivamente experimental; nao e um padrao de seguranca.
#include <Arduino.h>
#include <string.h>
#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <esp_random.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#if __has_include(<esp_arduino_version.h>)
#include <esp_arduino_version.h>
#endif

constexpr uint8_t PMS_RX = 17;
constexpr uint8_t PMS_TX = 18;  // Reservado; sem fio externo nesta montagem.
constexpr uint8_t BUZZER_PIN = 21;
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

uint16_t readU16(const uint8_t *data) {
  return (uint16_t(data[0]) << 8) | data[1];
}

bool sampleIsCurrent() {
  return hasSample && uint32_t(millis() - lastSampleMs) < SAMPLE_TIMEOUT_MS;
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
    display.print("STATUS: "); display.print(pm25 > PM25_LIMIT ? "ALERTA" : "NORMAL");
  }
  display.display();
}

void updateAlarm() {
  // A perda de dados e mostrada como erro de sensor, sem reutilizar uma
  // concentracao antiga indefinidamente. O alerta sonoro desliga apos 5 s.
  bool current = sampleIsCurrent();
  bool shouldSound = current && pm25 > PM25_LIMIT;
  if (shouldSound == buzzerOn) return;
  buzzerOn = shouldSound;
  if (buzzerOn) {
    tone(BUZZER_PIN, BUZZER_HZ);
  } else {
    noTone(BUZZER_PIN);
    digitalWrite(BUZZER_PIN, LOW);
  }
  Serial0.printf("BUZZER=%s PM2.5=%u freq=%u Hz t=%lu ms%s\n",
                 buzzerOn ? "ON" : "OFF", pm25, buzzerOn ? BUZZER_HZ : 0,
                 (unsigned long)millis(), current ? "" : " (SEM DADOS)");
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

void networkTask(void *) {
  constexpr char BROKER[] = "broker.emqx.io";
  constexpr uint16_t PORT = 1883;
  constexpr char PROBE_TOPIC[] = "obj-intelig-projeto/pm/47db91f2/probe";

  WiFiClient tcp;
  PubSubClient mqtt(tcp);
  mqtt.setSocketTimeout(2);
  char clientId[24];
  snprintf(clientId, sizeof(clientId), "pm-47db91f2-%08lx", (unsigned long)esp_random());

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin("Wokwi-GUEST", "", 6);
  Serial0.println("WIFI conectando a Wokwi-GUEST");

  bool wifiOnline = false;
  bool probeSent = false;
  uint32_t nextAttemptMs = 0;
  for (;;) {
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

    if (wifiOnline && mqtt.connected()) {
      mqtt.loop();
      if (!probeSent) {
        char payload[112];
        snprintf(payload, sizeof(payload),
                 "{\"version\":\"pm-diagnostico-mqtt\",\"client_id\":\"%s\",\"uptime_ms\":%lu}",
                 clientId, (unsigned long)millis());
        probeSent = mqtt.publish(PROBE_TOPIC, payload);
        if (probeSent) Serial0.printf("MQTT PROBE %s %s\n", PROBE_TOPIC, payload);
      }
    } else if (wifiOnline && int32_t(millis() - nextAttemptMs) >= 0) {
      IPAddress address;
      if (!WiFi.hostByName(BROKER, address)) {
        Serial0.printf("DNS FALHOU %s\n", BROKER);
      } else {
        Serial0.printf("DNS OK %s ip=%s\n", BROKER, address.toString().c_str());
        if (!tcp.connect(address, PORT, 1500)) {
          Serial0.printf("TCP FALHOU %s:%u\n", BROKER, PORT);
        } else {
          Serial0.printf("TCP OK %s:%u\n", BROKER, PORT);
          if (mqtt.setServer(address, PORT).connect(clientId)) {
            probeSent = false;
            Serial0.printf("MQTT CONNACK OK client_id=%s\n", clientId);
          } else {
            Serial0.printf("MQTT FALHOU state=%d\n", mqtt.state());
            tcp.stop();
          }
        }
      }
      nextAttemptMs = millis() + 5000;
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

void setup() {
  Serial0.begin(115200);
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
  if (xTaskCreate(networkTask, "mqtt", 6144, nullptr, 1, nullptr) != pdPASS) {
    Serial0.println("ERRO ao iniciar tarefa MQTT");
  }
}

void loop() {
  readSensor();
  updateAlarm();
  if (hasSample && !sampleIsCurrent() && !timeoutReported) {
    timeoutReported = true;
    Serial0.println("TIMEOUT: sem pacote valido ha 5 s");
  }
  if (uint32_t(millis() - lastDisplayMs) >= 200) {
    lastDisplayMs = millis();
    drawDisplay();
  }
  delay(1);
}
