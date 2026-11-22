/*
 * MrCodeTastic HUB75 receiver (v1 & v2 WebSocket protocol).
 *
 * Wire protocol: row-major RGB565 pixels (0,0)..(W-1,H-1), big-endian:
 *   0x81 0x81 | W*H RGB565 pixels (full frame, v1 & v2)
 *   0x81 0x82 | u16 n_rects, [u16 x, u16 y, u16 w, u16 h, w*h RGB565 pixels]... (delta, v2)
 *   0x81 0x83 | (u8 run_minus_1, u16 rgb565)... (RLE, v2)
 * Text JSON: hello, ack, brightness.
 * Discovery: UDP broadcast "CODETASTIC {...}" on port 20586.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESPmDNS.h>
#include <cstring>

#if __has_include("config.h")
#include "config.h"
#else
#include "config.example.h"
#endif

#define MATRIX_WIDTH (PANEL_WIDTH * PANEL_CHAIN)
#define MATRIX_HEIGHT PANEL_HEIGHT

#ifndef WEBSOCKETS_MAX_DATA_SIZE
#define WEBSOCKETS_MAX_DATA_SIZE (MATRIX_WIDTH * MATRIX_HEIGHT * 2 + 16)
#endif

#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>
#include <WebSocketsServer.h>
#include <array>

constexpr uint8_t FRAME_MAGIC = 0x81;
constexpr uint8_t TYPE_FULL = 0x81;
constexpr uint8_t TYPE_DELTA = 0x82;
constexpr uint8_t TYPE_RLE = 0x83;

constexpr size_t FRAME_PIXELS = MATRIX_WIDTH * MATRIX_HEIGHT;
constexpr size_t FULL_MESSAGE_BYTES = FRAME_PIXELS * sizeof(uint16_t) + 2;

MatrixPanel_I2S_DMA *display = nullptr;
WebSocketsServer webSocket(WEBSOCKET_PORT);
WiFiUDP discoveryUdp;

std::array<uint16_t, FRAME_PIXELS> workingFrame{};
std::array<uint16_t, FRAME_PIXELS> stagingFrames[2]{};
std::array<uint16_t, FRAME_PIXELS> drawBuffer{};
volatile uint8_t readyBufferIdx = 0;
volatile bool framePending = false;
volatile int16_t lastFrameClient = -1;
portMUX_TYPE frameMux = portMUX_INITIALIZER_UNLOCKED;

uint32_t bootMillis = 0;
uint32_t lastFrameRxMs = 0;
uint32_t lastDiscoveryMs = 0;
uint32_t lastStatsMs = 0;
uint32_t lastFlipUs = 0;
uint32_t receivedFrameCount = 0;
uint32_t displayedFrameCount = 0;
uint32_t rejectedFrameCount = 0;
bool showingNoSignal = false;

static inline uint16_t readU16BE(const uint8_t *ptr) {
  return (static_cast<uint16_t>(ptr[0]) << 8) | static_cast<uint16_t>(ptr[1]);
}

static void publishWorkingFrame(uint8_t clientId) {
  const uint8_t writeIdx = readyBufferIdx ^ 1;
  stagingFrames[writeIdx] = workingFrame;
  portENTER_CRITICAL(&frameMux);
  readyBufferIdx = writeIdx;
  framePending = true;
  lastFrameClient = clientId;
  portEXIT_CRITICAL(&frameMux);
  ++receivedFrameCount;
  lastFrameRxMs = millis();
  showingNoSignal = false;
}

static bool handleDeltaFrame(const uint8_t *payload, size_t length) {
  if (length < 4) return false;
  const uint16_t nRects = readU16BE(payload + 2);
  size_t pos = 4;
  for (uint16_t r = 0; r < nRects; ++r) {
    if (pos + 8 > length) return false;
    const uint16_t rx = readU16BE(payload + pos);
    const uint16_t ry = readU16BE(payload + pos + 2);
    const uint16_t rw = readU16BE(payload + pos + 4);
    const uint16_t rh = readU16BE(payload + pos + 6);
    pos += 8;
    if (rx + rw > MATRIX_WIDTH || ry + rh > MATRIX_HEIGHT) return false;
    const size_t rectBytes = static_cast<size_t>(rw) * static_cast<size_t>(rh) * 2;
    if (pos + rectBytes > length) return false;
    for (uint16_t row = 0; row < rh; ++row) {
      const size_t dstRow = static_cast<size_t>(ry + row) * MATRIX_WIDTH + rx;
      for (uint16_t col = 0; col < rw; ++col) {
        workingFrame[dstRow + col] = readU16BE(payload + pos);
        pos += 2;
      }
    }
  }
  return pos == length;
}

static bool handleRleFrame(const uint8_t *payload, size_t length) {
  size_t pos = 2;
  size_t outIdx = 0;
  while (pos + 3 <= length && outIdx < FRAME_PIXELS) {
    const size_t run = static_cast<size_t>(payload[pos]) + 1;
    const uint16_t color = readU16BE(payload + pos + 1);
    pos += 3;
    if (outIdx + run > FRAME_PIXELS) return false;
    for (size_t k = 0; k < run; ++k) {
      workingFrame[outIdx++] = color;
    }
  }
  return pos == length && outIdx == FRAME_PIXELS;
}

static void handleTextCommand(const uint8_t *payload, size_t length) {
  if (display == nullptr || length == 0 || length > 256) return;
  char buf[257];
  std::memcpy(buf, payload, length);
  buf[length] = '\0';
  if (std::strstr(buf, "\"brightness\"") != nullptr) {
    const char *valKey = std::strstr(buf, "\"value\"");
    if (valKey != nullptr) {
      const char *colon = std::strchr(valKey, ':');
      if (colon != nullptr) {
        int val = std::atoi(colon + 1);
        if (val < 0) val = 0;
        if (val > 255) val = 255;
        display->setBrightness8(static_cast<uint8_t>(val));
      }
    }
  }
}

static void reportWebSocketEvent(uint8_t clientId, WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED: {
      IPAddress ip = webSocket.remoteIP(clientId);
      Serial.printf("WebSocket client connected: %s\n", ip.toString().c_str());
      char hello[200];
      std::snprintf(
          hello, sizeof(hello),
          "{\"type\":\"hello\",\"v\":2,\"name\":\"%s\",\"w\":%u,\"h\":%u,"
          "\"caps\":[\"delta\",\"ack\",\"rle\",\"brightness\"]}",
          MDNS_HOST, static_cast<unsigned>(MATRIX_WIDTH), static_cast<unsigned>(MATRIX_HEIGHT));
      webSocket.sendTXT(clientId, hello);
      break;
    }
    case WStype_DISCONNECTED:
      Serial.printf("WebSocket client disconnected: %u\n", clientId);
      break;
    case WStype_TEXT:
      handleTextCommand(payload, length);
      break;
    case WStype_BIN: {
      if (length < 2 || payload[0] != FRAME_MAGIC) {
        ++rejectedFrameCount;
        return;
      }
      bool ok = false;
      if (payload[1] == TYPE_FULL && length == FULL_MESSAGE_BYTES) {
        for (size_t i = 0; i < FRAME_PIXELS; ++i) {
          workingFrame[i] = readU16BE(payload + 2 + i * 2);
        }
        ok = true;
      } else if (payload[1] == TYPE_DELTA) {
        ok = handleDeltaFrame(payload, length);
      } else if (payload[1] == TYPE_RLE) {
        ok = handleRleFrame(payload, length);
      }
      if (!ok) {
        ++rejectedFrameCount;
        if ((rejectedFrameCount % 30) == 1) {
          Serial.printf("Rejected frame type=0x%02X len=%u\n", payload[1], static_cast<unsigned>(length));
        }
        return;
      }
      publishWorkingFrame(clientId);
      break;
    }
    default:
      break;
  }
}

static void displayPendingFrame() {
  if (display == nullptr) return;
  int16_t ackClient = -1;
  portENTER_CRITICAL(&frameMux);
  const bool hasFrame = framePending;
  if (hasFrame) {
    drawBuffer = stagingFrames[readyBufferIdx];
    framePending = false;
    ackClient = lastFrameClient;
  }
  portEXIT_CRITICAL(&frameMux);
  if (!hasFrame) return;

  for (size_t i = 0; i < FRAME_PIXELS; ++i) {
    const int16_t x = static_cast<int16_t>(i % MATRIX_WIDTH);
    const int16_t y = static_cast<int16_t>(i / MATRIX_WIDTH);
    display->drawPixel(x, y, drawBuffer[i]);
  }

  uint32_t refreshHz = display->calculated_refresh_rate;
  if (refreshHz == 0) refreshHz = 60;
  const uint32_t minimumFrameUs = 1000000UL / refreshHz;
  if (lastFlipUs != 0) {
    const uint32_t elapsedUs = micros() - lastFlipUs;
    if (elapsedUs < minimumFrameUs) delayMicroseconds(minimumFrameUs - elapsedUs);
  }

  display->flipDMABuffer();
  lastFlipUs = micros();
  ++displayedFrameCount;

  if (ackClient >= 0) {
    char ack[64];
    std::snprintf(ack, sizeof(ack), "{\"type\":\"ack\",\"n\":%lu}", static_cast<unsigned long>(displayedFrameCount));
    webSocket.sendTXT(static_cast<uint8_t>(ackClient), ack);
  }
}

static void showBootBanner() {
  if (display == nullptr) return;
  display->fillScreen(0);
  display->setTextSize(1);
  display->setTextColor(display->color565(60, 180, 255));
  display->setCursor(2, 4);
  display->print("GLEDIATOR");
  display->setTextColor(display->color565(220, 220, 220));
  display->setCursor(2, 16);
  display->print(WiFi.localIP().toString());
  display->flipDMABuffer();
}

static void checkIdleStatus() {
  if (display == nullptr) return;
  const uint32_t now = millis();
  if (now - bootMillis < 5000) return;
  if (!showingNoSignal && (now - lastFrameRxMs) >= 5000) {
    showingNoSignal = true;
    display->fillScreen(0);
    display->setTextSize(1);
    display->setTextColor(display->color565(255, 160, 40));
    display->setCursor(2, 6);
    display->print("NO SIGNAL");
    display->setTextColor(display->color565(140, 160, 180));
    display->setCursor(2, 18);
    display->print(WiFi.localIP().toString());
    display->flipDMABuffer();
  }
}

static void broadcastDiscoveryBeacon() {
  if (WiFi.status() != WL_CONNECTED) return;
  char beacon[180];
  std::snprintf(
      beacon, sizeof(beacon),
      "CODETASTIC {\"v\":2,\"name\":\"%s\",\"w\":%u,\"h\":%u,\"port\":%u}",
      MDNS_HOST, static_cast<unsigned>(MATRIX_WIDTH), static_cast<unsigned>(MATRIX_HEIGHT),
      static_cast<unsigned>(WEBSOCKET_PORT));
  const IPAddress broadcastAddress(255, 255, 255, 255);
  discoveryUdp.beginPacket(broadcastAddress, DISCOVERY_PORT);
  discoveryUdp.write(reinterpret_cast<const uint8_t *>(beacon), std::strlen(beacon));
  discoveryUdp.endPacket();
}

static void startNetworkServices() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Connecting to Wi-Fi %s", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print('.');
  }
  Serial.printf("\nWi-Fi connected: %s\n", WiFi.localIP().toString().c_str());

  if (MDNS.begin(MDNS_HOST)) {
    MDNS.addService("ws", "tcp", WEBSOCKET_PORT);
    MDNS.addServiceTxt("ws", "tcp", "device", "MrCodeTastic HUB75");
    Serial.printf("mDNS: %s.local\n", MDNS_HOST);
  } else {
    Serial.println("mDNS startup failed; UDP discovery remains enabled");
  }

  discoveryUdp.begin(DISCOVERY_PORT);
  webSocket.begin();
  webSocket.onEvent(reportWebSocketEvent);
  Serial.printf("WebSocket listening on port %u; UDP CODETASTIC beacon on %u\n",
                WEBSOCKET_PORT, DISCOVERY_PORT);
}

static void startDisplay() {
  HUB75_I2S_CFG config(PANEL_WIDTH, PANEL_HEIGHT, PANEL_CHAIN);
  config.double_buff = true;

  display = new MatrixPanel_I2S_DMA(config);
  if (!display->begin()) {
    Serial.println("HUB75 display initialization failed");
    while (true) delay(1000);
  }
  display->clearScreen();
  Serial.printf("HUB75 ready: %ux%u, refresh %u Hz, double buffering on\n",
                MATRIX_WIDTH, MATRIX_HEIGHT, display->calculated_refresh_rate);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  startDisplay();
  startNetworkServices();
  showBootBanner();
  bootMillis = millis();
  lastFrameRxMs = bootMillis;
  lastDiscoveryMs = bootMillis - 2000;
  lastStatsMs = bootMillis;
}

void loop() {
  webSocket.loop();
  const uint32_t now = millis();
  if (now - lastDiscoveryMs >= 2000) {
    broadcastDiscoveryBeacon();
    lastDiscoveryMs = now;
  }
  displayPendingFrame();
  checkIdleStatus();
  if (now - lastStatsMs >= 5000) {
    Serial.printf("Stats: rx=%lu disp=%lu rej=%lu heap=%u\n",
                  static_cast<unsigned long>(receivedFrameCount),
                  static_cast<unsigned long>(displayedFrameCount),
                  static_cast<unsigned long>(rejectedFrameCount),
                  static_cast<unsigned>(ESP.getFreeHeap()));
    lastStatsMs = now;
  }
  delay(1);
}
