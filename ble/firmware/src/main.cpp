// Isolated hardware probe: simulated BLE payloads only. Never prints PIN/data.
// Uses the existing board display driver but does not modify the dashboard.
#include <Arduino.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <lvgl.h>
#define XPOWERS_CHIP_AXP2101
#include <XPowersLib.h>
#include "../../../firmware/src/waveshare_lcd.h"
#include "ble_transport.h"

namespace {
constexpr int width = 480, height = 480, boot_pin = 9;
constexpr int touch_reset = 11, touch_interrupt = 5, touch_addr = 0x5a;
constexpr uint32_t hold_ms = 1000, window_ms = 120000;
XPowersPMU power;
lv_disp_draw_buf_t draw_buf;
lv_disp_drv_t driver;
lv_obj_t *status_label, *pin_label, *detail_label;
bool probe_ready = false, press_handled = false, button_was_down = false;
bool had_auth = false, pairing_visible = false;
uint32_t pressed_at = 0, window_until = 0;

void round_area(lv_disp_drv_t *, lv_area_t *a) {
  if (a->x1 % 2) --a->x1;
  if (a->y1 % 2) --a->y1;
  if (!(a->x2 % 2)) ++a->x2;
  if (!(a->y2 % 2)) ++a->y2;
}

lv_obj_t *make_label(const char *text, int y, const lv_font_t *font, uint32_t color) {
  lv_obj_t *label = lv_label_create(lv_scr_act());
  lv_label_set_text(label, text);
  lv_obj_set_width(label, width);
  lv_obj_set_pos(label, 0, y);
  lv_obj_set_style_text_font(label, font, 0);
  lv_obj_set_style_text_color(label, lv_color_hex(color), 0);
  lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
  return label;
}

bool begin_display() {
  Wire.begin(8, 7);
  if (!power.begin(Wire, AXP2101_SLAVE_ADDRESS, 8, 7)) return false;
  power.setALDO3Voltage(3300); power.enableALDO3(); delay(100);
  power.disableALDO3(); delay(100); power.enableALDO3(); delay(150);
  if (waveshare_lcd_begin(&driver) != ESP_OK) return false;
  // Match the touch controller reset sequence used by the working dashboard.
  pinMode(touch_reset, OUTPUT); digitalWrite(touch_reset, HIGH); delay(200);
  digitalWrite(touch_reset, LOW); delay(200); digitalWrite(touch_reset, HIGH); delay(200);
  pinMode(touch_interrupt, INPUT_PULLUP);
  lv_init();
  constexpr int pixels = width * 30;
  auto *buf = static_cast<lv_color_t *>(heap_caps_malloc(pixels * sizeof(lv_color_t), MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL));
  if (!buf) return false;
  lv_disp_draw_buf_init(&draw_buf, buf, nullptr, pixels);
  lv_disp_drv_init(&driver);
  driver.hor_res = width; driver.ver_res = height; driver.flush_cb = waveshare_lcd_flush;
  driver.rounder_cb = round_area; driver.draw_buf = &draw_buf;
  if (!lv_disp_drv_register(&driver)) return false;
  lv_obj_set_style_bg_color(lv_scr_act(), lv_color_hex(0x111924), 0);
  make_label("BLE TEST", 70, &lv_font_montserrat_32, 0x6fa8ff);
  status_label = make_label("HOLD SCREEN TO PAIR", 142, &lv_font_montserrat_18, 0xe9f1f5);
  pin_label = make_label("------", 195, &lv_font_montserrat_48, 0x5ae6c1);
  detail_label = make_label("TEST DATA ONLY", 300, &lv_font_montserrat_18, 0x9fb2bd);
  return true;
}

bool touch_down() {
  uint8_t data[10]{};
  Wire.beginTransmission(touch_addr); Wire.write(0xd0); Wire.write(0x00);
  const bool ok = Wire.endTransmission(false) == 0 && Wire.requestFrom(touch_addr, 10) == 10;
  if (!ok) return false;
  for (auto &byte : data) byte = Wire.read();
  return data[6] == 0xab && (data[5] & 0x7f) != 0 && (data[0] & 0x0f) == 0x06;
}

void set_status(const char *status, const char *detail) {
  lv_label_set_text(status_label, status);
  lv_label_set_text(detail_label, detail);
}
}  // namespace

void setup() {
  Serial.begin(115200);
  delay(1500);
  pinMode(boot_pin, INPUT_PULLUP);
  if (!begin_display()) { Serial.println("BLE probe display init failed"); return; }
  if (!bleTransportBegin()) { set_status("BLE INIT FAILED", "TEST STOPPED"); return; }
  probe_ready = true;
  Serial.println("BLE test ready; hold the touch screen to open pairing.");
}

void loop() {
  if (!probe_ready) { delay(50); return; }
  const uint32_t now = millis();
  const bool down = digitalRead(boot_pin) == LOW || touch_down();
  if (down && !button_was_down) { pressed_at = now; press_handled = false; }
  if (down && !press_handled && now - pressed_at >= hold_ms && !bleAuthenticated()) {
    press_handled = true;
    bleOpenPairingWindow();
    window_until = now + window_ms;
    pairing_visible = true;
    lv_label_set_text(pin_label, "------");
    set_status("PAIRING WINDOW OPEN", "PAIR IN WINDOWS SETTINGS");
  }
  button_was_down = down;

  uint32_t pin;
  if (bleTakePasskey(pin)) {
    char text[7];
    snprintf(text, sizeof(text), "%06lu", static_cast<unsigned long>(pin));
    lv_label_set_text(pin_label, text);  // On-board display only; never serial/log.
    set_status("ENTER PIN IN WINDOWS", "TEST DATA ONLY");
  }
  const bool auth = bleAuthenticated();
  if (auth && !had_auth) {
    pairing_visible = false;
    lv_label_set_text(pin_label, "------");
    set_status("PAIRED", "WAITING FOR TEST DATA");
  } else if (!auth && had_auth) {
    lv_label_set_text(pin_label, "------");
    set_status("DISCONNECTED", "HOLD SCREEN TO REPAIR");
  }
  had_auth = auth;
  if (pairing_visible && static_cast<int32_t>(window_until - now) <= 0) {
    pairing_visible = false;
    lv_label_set_text(pin_label, "------");
    set_status("PAIRING WINDOW CLOSED", "HOLD SCREEN TO RETRY");
  }

  static BleMessage message;
  if (bleTakeMessage(message)) {
    JsonDocument doc;
    const auto error = deserializeJson(doc, message.bytes, message.length);
    const char *mode = doc["mode"] | "";
    if (!error && strcmp(mode, "mock") == 0 && auth) {
      set_status("TEST FRAME RECEIVED", "MOCK DATA ONLY");
      Serial.println("Validated mock BLE message received.");
    } else {
      set_status("TEST DATA REJECTED", "MOCK DATA ONLY");
      Serial.println("BLE test message rejected.");
    }
  }
  lv_timer_handler();
  delay(10);
}
