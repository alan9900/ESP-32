// Display/power wiring based on the Waveshare ESP32-C6-Touch-AMOLED-2.16
// examples and cc-usage-display; see LICENSE-REFERENCE.txt.
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include <lvgl.h>
#include "waveshare_lcd.h"
#include <time.h>
#include <sys/time.h>
#include <esp_sntp.h>
#define XPOWERS_CHIP_AXP2101
#include <XPowersLib.h>
extern "C" const lv_font_t zh_ui_20;
extern "C" const lv_font_t zh_ui_16;
extern "C" const lv_font_t clock_digits_88;

#if __has_include("config.h")
#include "config.h"
#else
#include "config.example.h"
#endif

namespace {
constexpr int WIDTH = 480, HEIGHT = 480, PAGE_COUNT = 2;
constexpr int I2C_SDA = 8, I2C_SCL = 7, TOUCH_ADDR = 0x5a, RTC_ADDR = 0x51;
constexpr int TOUCH_RST = 11, TOUCH_INT = 5;
constexpr uint8_t RTC_UTC_MARKER = 0xC6;
constexpr uint32_t BG = 0x111924, PANEL = 0x1b2935, MUTED = 0x9fb2bd;
constexpr uint32_t TEXT = 0xe9f1f5, GREEN = 0x5ae6c1, BLUE = 0x6fa8ff;
constexpr uint32_t WARNING = 0xf5b765, ERROR_COLOR = 0xf08383;
constexpr time_t MIN_VALID_TIME = 1672531200;  // 2023-01-01 UTC
constexpr long SNAPSHOT_STALE_SECONDS = 120, WEATHER_STALE_SECONDS = 30 * 60;

XPowersPMU power;
lv_disp_draw_buf_t draw_buf;
lv_color_t *draw_pixels;
SemaphoreHandle_t data_mutex;
TaskHandle_t network_task;

struct Window { bool valid; float remaining; time_t reset_epoch; };
struct Snapshot {
  Window five, week;
  bool weather_valid; float temperature; char city[32]; char condition[24];
  bool humidity_valid, high_valid, low_valid;
  float humidity, high_temp, low_temp;
  time_t weather_epoch; bool weather_error;
  time_t updated_epoch;
  bool codex_error, mock, online, has_data;
};
Snapshot snapshot{};
volatile bool ntp_sync_pending = false;
volatile bool clock_valid = false;
volatile bool clock_from_rtc = false;

lv_obj_t *page_roots[PAGE_COUNT], *page_dots[PAGE_COUNT];
lv_obj_t *page_title, *state_label, *footer;
lv_obj_t *clock_value, *clock_date;
lv_obj_t *weather_city, *weather_cond, *weather_temp, *weather_note, *weather_humidity;
lv_obj_t *weather_sun, *weather_cloud;
lv_obj_t *page_subtitle, *page_update;
lv_obj_t *five_value, *week_value, *five_reset, *week_reset;
lv_obj_t *five_countdown, *week_countdown, *five_bar, *week_bar;
int current_page = 0;
// readTouch runs on the LVGL thread; process actions after lv_timer_handler.
int pending_action = 0;  // -1: previous, +1: next, 2: refresh

bool i2cRead(uint8_t address, uint8_t reg, uint8_t *buf, size_t len) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(static_cast<int>(address), static_cast<int>(len)) != static_cast<int>(len)) return false;
  for (size_t i = 0; i < len; ++i) buf[i] = static_cast<uint8_t>(Wire.read());
  return true;
}
bool i2cWrite(uint8_t address, uint8_t reg, const uint8_t *buf, size_t len) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  for (size_t i = 0; i < len; ++i) Wire.write(buf[i]);
  return Wire.endTransmission() == 0;
}
int fromBcd(uint8_t x) { return (x >> 4) * 10 + (x & 15); }
bool validBcd(uint8_t x) { return (x & 15) <= 9 && (x >> 4) <= 9; }
uint8_t toBcd(int x) { return static_cast<uint8_t>((x / 10 << 4) | (x % 10)); }

// The PCF85063A's one-byte user RAM is used as an explicit UTC ownership marker.
// A factory/local-time RTC value is not treated as UTC until this firmware has
// successfully written it after NTP sync. No actual hardware validation yet.
bool restoreRtc() {
  uint8_t control = 0, data[8]{};
  if (!i2cRead(RTC_ADDR, 0x00, &control, 1) || (control & 0x20) ||
      !i2cRead(RTC_ADDR, 0x03, data, sizeof(data)) || data[0] != RTC_UTC_MARKER ||
      (data[1] & 0x80)) return false;  // STOP or oscillator-stop flag
  const uint8_t raw[] = {static_cast<uint8_t>(data[1] & 0x7f),
                         static_cast<uint8_t>(data[2] & 0x7f),
                         static_cast<uint8_t>(data[3] & 0x3f),
                         static_cast<uint8_t>(data[4] & 0x3f),
                         static_cast<uint8_t>(data[6] & 0x1f), data[7]};
  for (uint8_t v : raw) if (!validBcd(v)) return false;
  tm t{};
  t.tm_sec = fromBcd(raw[0]); t.tm_min = fromBcd(raw[1]); t.tm_hour = fromBcd(raw[2]);
  t.tm_mday = fromBcd(raw[3]); t.tm_mon = fromBcd(raw[4]) - 1;
  // Waveshare's PCF85063 example stores year as offset from 1970.
  t.tm_year = 70 + fromBcd(raw[5]);
  if (t.tm_sec > 59 || t.tm_min > 59 || t.tm_hour > 23 || t.tm_mday < 1 ||
      t.tm_mday > 31 || t.tm_mon < 0 || t.tm_mon > 11) return false;
  const tm original = t;
  time_t epoch = mktime(&t);  // TZ is UTC0
  if (epoch < MIN_VALID_TIME || t.tm_year != original.tm_year || t.tm_mon != original.tm_mon ||
      t.tm_mday != original.tm_mday || t.tm_hour != original.tm_hour ||
      t.tm_min != original.tm_min || t.tm_sec != original.tm_sec) return false;
  timeval tv{}; tv.tv_sec = epoch;
  if (settimeofday(&tv, nullptr) != 0) return false;
  clock_from_rtc = true; clock_valid = true;
  return true;
}
bool saveRtc(time_t epoch) {
  tm t{}; gmtime_r(&epoch, &t);
  int year = t.tm_year + 1900;
  if (epoch < MIN_VALID_TIME || year < 1970 || year > 2069) return false;
  uint8_t ctrl = 0, marker = 0;
  if (!i2cRead(RTC_ADDR, 0x00, &ctrl, 1) || !i2cWrite(RTC_ADDR, 0x03, &marker, 1)) return false;
  const uint8_t stopped = ctrl | 0x20;
  if (!i2cWrite(RTC_ADDR, 0x00, &stopped, 1)) return false;
  const uint8_t data[] = {toBcd(t.tm_sec), toBcd(t.tm_min), toBcd(t.tm_hour),
                          toBcd(t.tm_mday), toBcd(t.tm_wday), toBcd(t.tm_mon + 1),
                          toBcd(year - 1970)};
  const bool wrote = i2cWrite(RTC_ADDR, 0x04, data, sizeof(data));
  const uint8_t running = ctrl & ~0x20;
  const bool resumed = i2cWrite(RTC_ADDR, 0x00, &running, 1);
  if (!wrote || !resumed) return false;
  marker = RTC_UTC_MARKER;
  return i2cWrite(RTC_ADDR, 0x03, &marker, 1);
}
void ntpSynced(struct timeval *) { ntp_sync_pending = true; }

void onWifiEvent(arduino_event_id_t event, arduino_event_info_t info) {
  if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
    Serial.printf("[wifi] IP: %s\n", WiFi.localIP().toString().c_str());
  } else if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    Serial.printf("[wifi] disconnected, reason: %u\n", info.wifi_sta_disconnected.reason);
  }
}

void roundArea(lv_disp_drv_t *, lv_area_t *a) {
  if (a->x1 % 2) --a->x1;
  if (a->y1 % 2) --a->y1;
  if (!(a->x2 % 2)) ++a->x2;
  if (!(a->y2 % 2)) ++a->y2;
}
void readTouch(lv_indev_drv_t *, lv_indev_data_t *out) {
  static bool down = false;
  static int start_x = 0, start_y = 0, last_x = 0, last_y = 0;
  static uint32_t pressed_at = 0;
  uint8_t data[10]{};
  Wire.beginTransmission(TOUCH_ADDR); Wire.write(0xd0); Wire.write(0x00);
  bool ok = Wire.endTransmission(false) == 0 && Wire.requestFrom(TOUCH_ADDR, 10) == 10;
  if (ok) for (auto &b : data) b = Wire.read();
  ok = ok && data[6] == 0xab && (data[5] & 0x7f) != 0 && (data[0] & 0x0f) == 0x06;
  if (!ok) {
    if (down) {
      int dx = last_x - start_x, dy = last_y - start_y;
      if (abs(dx) >= 65 && abs(dx) > abs(dy) * 1.3f) pending_action = dx < 0 ? 1 : -1;
      else if (abs(dx) < 25 && abs(dy) < 25 && millis() - pressed_at < 1000) pending_action = 2;
      down = false;
    }
    out->state = LV_INDEV_STATE_REL; return;
  }
  const int x = constrain(WIDTH - ((static_cast<int>(data[2]) << 4) | (data[3] & 0x0f)), 0, WIDTH - 1);
  const int y = constrain((static_cast<int>(data[1]) << 4) | (data[3] >> 4), 0, HEIGHT - 1);
  if (!down) { down = true; start_x = x; start_y = y; pressed_at = millis(); }
  last_x = x; last_y = y;
  out->point.x = x; out->point.y = y; out->state = LV_INDEV_STATE_PR;
}

lv_obj_t *label(lv_obj_t *parent, const char *text, int x, int y,
                const lv_font_t *font, uint32_t color, int width = 0) {
  auto *obj = lv_label_create(parent);
  lv_label_set_text(obj, text);
  lv_obj_set_pos(obj, x, y);
  lv_obj_set_style_text_color(obj, lv_color_hex(color), 0);
  lv_obj_set_style_text_font(obj, font, 0);
  if (width) { lv_obj_set_width(obj, width); lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP); }
  lv_obj_clear_flag(obj, LV_OBJ_FLAG_CLICKABLE);
  return obj;
}
lv_obj_t *container(lv_obj_t *parent, int x, int y, int w, int h, bool filled) {
  auto *obj = lv_obj_create(parent);
  lv_obj_set_pos(obj, x, y); lv_obj_set_size(obj, w, h);
  lv_obj_set_style_bg_color(obj, lv_color_hex(PANEL), 0);
  lv_obj_set_style_bg_opa(obj, filled ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
  lv_obj_set_style_border_width(obj, 0, 0); lv_obj_set_style_radius(obj, 18, 0);
  lv_obj_set_style_pad_all(obj, 0, 0);
  lv_obj_clear_flag(obj, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
  return obj;
}
void makeWindow(lv_obj_t *parent, int y, const char *title, uint32_t color,
                lv_obj_t **value, lv_obj_t **reset, lv_obj_t **countdown, lv_obj_t **bar) {
  auto *p = container(parent, 24, y, 432, 151, true);
  label(p, title, 19, 13, &zh_ui_20, TEXT);
  *value = label(p, "--%", 235, 8, &lv_font_montserrat_40, color, 170);
  lv_obj_set_style_text_align(*value, LV_TEXT_ALIGN_RIGHT, 0);
  *reset = label(p, "重置 --", 16, 102, &zh_ui_16, MUTED, 210);
  *countdown = label(p, "--", 225, 102, &zh_ui_16, TEXT, 185);
  lv_obj_set_style_text_align(*countdown, LV_TEXT_ALIGN_RIGHT, 0);
  *bar = lv_bar_create(p); lv_obj_set_pos(*bar, 16, 72); lv_obj_set_size(*bar, 400, 8);
  lv_bar_set_range(*bar, 0, 100); lv_bar_set_value(*bar, 0, LV_ANIM_OFF);
  lv_obj_set_style_bg_color(*bar, lv_color_hex(0x2a3743), LV_PART_MAIN);
  lv_obj_set_style_bg_color(*bar, lv_color_hex(color), LV_PART_INDICATOR);
  lv_obj_clear_flag(*bar, LV_OBJ_FLAG_CLICKABLE);
}
void showPage(int n) {
  if (n < 0 || n >= PAGE_COUNT) return;
  current_page = n;
  const char *titles[] = {"桌面", "Codex"};
  lv_label_set_text(page_title, titles[n]);
  for (int i = 0; i < PAGE_COUNT; ++i) {
    if (i == n) lv_obj_clear_flag(page_roots[i], LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(page_roots[i], LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_bg_color(page_dots[i], lv_color_hex(i == n ? GREEN : 0x465564), 0);
  }
}
void createUi() {
  auto *screen = lv_scr_act();
  lv_obj_set_style_bg_color(screen, lv_color_hex(BG), 0);
  lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
  page_title = label(screen, "桌面", 28, 20, &zh_ui_20, TEXT);
  state_label = label(screen, "连接中", 340, 22, &zh_ui_16, MUTED, 112);
  lv_obj_set_style_text_align(state_label, LV_TEXT_ALIGN_RIGHT, 0);
  auto *divider = container(screen, 28, 57, 424, 1, true);
  lv_obj_set_style_bg_color(divider, lv_color_hex(0x283644), 0);
  for (int i = 0; i < PAGE_COUNT; ++i) page_roots[i] = container(screen, 0, 60, WIDTH, 384, false);

  clock_value = label(page_roots[0], "--:--", 0, 12, &clock_digits_88, TEXT, WIDTH);
  lv_obj_set_style_text_align(clock_value, LV_TEXT_ALIGN_CENTER, 0);
  clock_date = label(page_roots[0], "时间未同步", 0, 127, &zh_ui_20, MUTED, WIDTH);
  lv_obj_set_style_text_align(clock_date, LV_TEXT_ALIGN_CENTER, 0);
  auto *weather = container(page_roots[0], 24, 180, 432, 186, true);
  weather_city = label(weather, "天气", 20, 16, &zh_ui_20, TEXT, 210);
  weather_sun = container(weather, 24, 62, 30, 30, true);
  lv_obj_set_style_radius(weather_sun, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(weather_sun, lv_color_hex(0xffd47f), 0);
  weather_cloud = container(weather, 26, 82, 54, 16, true);
  lv_obj_set_style_radius(weather_cloud, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(weather_cloud, lv_color_hex(0xd5e1e9), 0);
  weather_cond = label(weather, "--", 90, 68, &zh_ui_20, TEXT, 145);
  weather_temp = label(weather, "-- C", 250, 55, &lv_font_montserrat_40, TEXT, 158);
  lv_obj_set_style_text_align(weather_temp, LV_TEXT_ALIGN_RIGHT, 0);
  auto *weather_divider = container(weather, 20, 124, 390, 1, true);
  lv_obj_set_style_bg_color(weather_divider, lv_color_hex(0x344755), 0);
  weather_note = label(weather, "最高 --  最低 --", 20, 138, &zh_ui_16, MUTED, 245);
  weather_humidity = label(weather, "湿度 --", 270, 138, &zh_ui_16, MUTED, 142);
  lv_obj_set_style_text_align(weather_humidity, LV_TEXT_ALIGN_RIGHT, 0);

  page_subtitle = label(page_roots[1], "剩余额度", 28, 5, &zh_ui_16, MUTED);
  page_update = label(page_roots[1], "读取 --", 270, 5, &zh_ui_16, MUTED, 182);
  lv_obj_set_style_text_align(page_update, LV_TEXT_ALIGN_RIGHT, 0);
  makeWindow(page_roots[1], 44, "5 小时额度", GREEN, &five_value, &five_reset, &five_countdown, &five_bar);
  makeWindow(page_roots[1], 211, "每周额度", BLUE, &week_value, &week_reset, &week_countdown, &week_bar);

  footer = label(page_roots[1], "", 28, 365, &zh_ui_16, MUTED, 300);
  for (int i = 0; i < PAGE_COUNT; ++i) {
    page_dots[i] = lv_obj_create(screen);
    lv_obj_set_pos(page_dots[i], 225 + i * 19, 452); lv_obj_set_size(page_dots[i], 11, 6);
    lv_obj_set_style_radius(page_dots[i], LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(page_dots[i], 0, 0);
    lv_obj_set_style_pad_all(page_dots[i], 0, 0);
    lv_obj_clear_flag(page_dots[i], LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
  }
  showPage(0);
}

// Parse an ISO 8601 timestamp carrying Z or an explicit +/-HH:MM offset.
time_t parseIso(const char *input) {
  int yr, mon, day, hour, min, sec = 0, zone_h = 0, zone_m = 0;
  if (!input || sscanf(input, "%d-%d-%dT%d:%d:%d", &yr, &mon, &day, &hour, &min, &sec) != 6) return 0;
  if (yr < 2023 || mon < 1 || mon > 12 || day < 1 || day > 31 ||
      hour > 23 || min > 59 || sec > 59) return 0;
  const char *z = input + 19;
  while (*z && *z != '+' && *z != '-' && *z != 'Z') ++z;
  if (!*z) return 0;
  char sign = *z;
  if ((sign == '+' || sign == '-') && sscanf(z + 1, "%d:%d", &zone_h, &zone_m) != 2) return 0;
  tm t{}; t.tm_year = yr - 1900; t.tm_mon = mon - 1; t.tm_mday = day;
  t.tm_hour = hour; t.tm_min = min; t.tm_sec = sec;
  time_t epoch = mktime(&t);
  if (sign == '+' || sign == '-') epoch += (sign == '+' ? -1 : 1) * (zone_h * 3600 + zone_m * 60);
  return epoch >= MIN_VALID_TIME ? epoch : 0;
}
void displayTime(time_t epoch, char *out, size_t n) {
  if (!epoch) { snprintf(out, n, "--"); return; }
  epoch += 8 * 3600; tm local{}; gmtime_r(&epoch, &local);
  snprintf(out, n, "%02d/%02d %02d:%02d", local.tm_mon + 1, local.tm_mday, local.tm_hour, local.tm_min);
}
void copyAscii(char *out, size_t n, const char *input, const char *fallback) {
  if (!input || !*input) input = fallback;
  size_t i = 0;
  for (; *input && i + 1 < n; ++input) {
    unsigned char c = static_cast<unsigned char>(*input);
    if (c >= 32 && c < 127) out[i++] = static_cast<char>(c);
    else out[i++] = '?';
  }
  out[i] = 0;
}
void windowFromJson(JsonVariantConst json, Window &w) {
  w.valid = json["remaining_percent"].is<float>() || json["remaining_percent"].is<int>();
  if (w.valid) w.remaining = constrain(json["remaining_percent"].as<float>(), 0.0f, 100.0f);
  w.reset_epoch = parseIso(json["resets_at"] | static_cast<const char *>(nullptr));
}
bool decode(const String &body, Snapshot &s) {
  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;
  if (!doc["codex"].is<JsonObject>()) return false;
  windowFromJson(doc["codex"]["five_hour"], s.five);
  windowFromJson(doc["codex"]["weekly"], s.week);
  auto weather = doc["weather"];
  s.weather_valid = !weather.isNull() && !weather["temperature_c"].isNull();
  if (s.weather_valid) s.temperature = weather["temperature_c"].as<float>();
  s.humidity_valid = !weather.isNull() && !weather["humidity_percent"].isNull();
  if (s.humidity_valid) s.humidity = weather["humidity_percent"].as<float>();
  s.high_valid = !weather.isNull() && !weather["high_c"].isNull();
  if (s.high_valid) s.high_temp = weather["high_c"].as<float>();
  s.low_valid = !weather.isNull() && !weather["low_c"].isNull();
  if (s.low_valid) s.low_temp = weather["low_c"].as<float>();
  copyAscii(s.city, sizeof(s.city), weather["city"] | "", "--");
  copyAscii(s.condition, sizeof(s.condition), weather["condition"] | "", "--");
  s.weather_epoch = parseIso(weather["updated_at"] | static_cast<const char *>(nullptr));
  s.weather_error = weather.isNull() || !weather["error"].isNull();
  s.updated_epoch = parseIso(doc["updated_at"] | static_cast<const char *>(nullptr));
  s.codex_error = !doc["codex"]["error"].isNull();
  s.mock = strcmp(doc["mode"] | "live", "mock") == 0;
  s.online = true; s.has_data = true;
  return true;
}
void pollTask(void *) {
  WiFi.onEvent(onWifiEvent);
  WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true); WiFi.begin(DASH_WIFI_SSID, DASH_WIFI_PASSWORD);
  Serial.println("[wifi] connecting");
  bool ntp_started = false;
  for (;;) {
    bool ok = false; Snapshot next{};
    if (WiFi.status() == WL_CONNECTED) {
      if (!ntp_started) {
        sntp_set_time_sync_notification_cb(ntpSynced);
        configTzTime("UTC0", "pool.ntp.org", "time.cloudflare.com");
        ntp_started = true;
      }
      HTTPClient http; http.setTimeout(4000);
      if (http.begin(DASH_STATUS_URL)) {
        if (strlen(DASH_BEARER_TOKEN)) http.addHeader("Authorization", String("Bearer ") + DASH_BEARER_TOKEN);
        const int status = http.GET();
        Serial.printf("[bridge] HTTP status: %d\n", status);
        if (status == HTTP_CODE_OK && (http.getSize() < 0 || http.getSize() <= 16384)) {
          String body = http.getString();
          if (body.length() <= 16384) ok = decode(body, next);
        }
        http.end();
      }
    }
    xSemaphoreTake(data_mutex, portMAX_DELAY);
    if (ok) snapshot = next;
    else snapshot.online = false;
    xSemaphoreGive(data_mutex);
    ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(DASH_REFRESH_SECONDS * 1000));
  }
}
void countdown(time_t reset, time_t now, char *out, size_t size) {
  if (!clock_valid || !reset) { snprintf(out, size, "还剩 --"); return; }
  long remaining = static_cast<long>(reset - now);
  if (remaining <= 0) { snprintf(out, size, "等待重置"); return; }
  long minutes = (remaining + 59) / 60;
  long days = minutes / 1440, hours = minutes % 1440 / 60, mins = minutes % 60;
  if (days) snprintf(out, size, "还剩 %ld天%ld小时", days, hours);
  else snprintf(out, size, "还剩 %ld小时%02ld分", hours, mins);
}
void render() {
  Snapshot s{};
  xSemaphoreTake(data_mutex, portMAX_DELAY); s = snapshot; xSemaphoreGive(data_mutex);
  time_t now = time(nullptr);
  bool stale = s.has_data && clock_valid && s.updated_epoch && now - s.updated_epoch > SNAPSHOT_STALE_SECONDS;
  bool weather_stale = s.weather_error || !s.online || !s.weather_epoch ||
                       (clock_valid && now - s.weather_epoch > WEATHER_STALE_SECONDS);
  bool partial = current_page == 0 ? (!s.weather_valid || weather_stale) :
                                     (s.codex_error || !s.five.valid || !s.week.valid);
  const char *status = !s.online ? "已离线" :
                       s.mock ? "模拟数据" : stale ? "数据过期" :
                       partial ? "数据不全" : "已连接";
  lv_label_set_text(state_label, status);
  lv_obj_set_style_text_color(state_label, lv_color_hex(!s.online || stale ? ERROR_COLOR : (s.mock || partial ? WARNING : GREEN)), 0);
  char buf[96], temp[32];
  if (clock_valid && now >= MIN_VALID_TIME) {
    time_t local_epoch = now + 8 * 3600; tm local{}; gmtime_r(&local_epoch, &local);
    const char *days[] = {"日", "一", "二", "三", "四", "五", "六"};
    snprintf(buf, sizeof(buf), "%02d:%02d", local.tm_hour, local.tm_min); lv_label_set_text(clock_value, buf);
    snprintf(buf, sizeof(buf), "%04d年%02d月%02d日  星期%s", local.tm_year + 1900, local.tm_mon + 1,
             local.tm_mday, days[local.tm_wday]); lv_label_set_text(clock_date, buf);
  } else {
    lv_label_set_text(clock_value, "--:--"); lv_label_set_text(clock_date, "时间未同步");
  }
  const char *city = s.has_data && s.city[0] ? s.city : "天气";
  if (!strcasecmp(city, "Changsha")) city = "长沙";
  lv_label_set_text(weather_city, city);
  const char *condition = "--";
  if (s.weather_valid) {
    if (!strcmp(s.condition, "Clear")) condition = "晴";
    else if (!strcmp(s.condition, "Cloudy")) condition = "多云";
    else if (!strcmp(s.condition, "Fog")) condition = "雾";
    else if (!strcmp(s.condition, "Drizzle")) condition = "小雨";
    else if (!strcmp(s.condition, "Rain")) condition = "雨";
    else if (!strcmp(s.condition, "Snow")) condition = "雪";
    else if (!strcmp(s.condition, "Thunder")) condition = "雷雨";
    else condition = "未知";
  }
  lv_label_set_text(weather_cond, condition);
  if (s.weather_valid && (!strcmp(s.condition, "Clear") || !strcmp(s.condition, "Cloudy")))
    lv_obj_clear_flag(weather_sun, LV_OBJ_FLAG_HIDDEN);
  else lv_obj_add_flag(weather_sun, LV_OBJ_FLAG_HIDDEN);
  if (s.weather_valid && strcmp(s.condition, "Clear")) lv_obj_clear_flag(weather_cloud, LV_OBJ_FLAG_HIDDEN);
  else lv_obj_add_flag(weather_cloud, LV_OBJ_FLAG_HIDDEN);
  if (s.weather_valid) snprintf(buf, sizeof(buf), "%.0f C", s.temperature); else snprintf(buf, sizeof(buf), "-- C");
  lv_label_set_text(weather_temp, buf);
  char high[16], low[16];
  if (s.high_valid) snprintf(high, sizeof(high), "%.0f C", s.high_temp); else snprintf(high, sizeof(high), "--");
  if (s.low_valid) snprintf(low, sizeof(low), "%.0f C", s.low_temp); else snprintf(low, sizeof(low), "--");
  snprintf(buf, sizeof(buf), "最高 %s  最低 %s", high, low);
  lv_label_set_text(weather_note, buf);
  if (s.humidity_valid) snprintf(buf, sizeof(buf), "湿度 %.0f%%", s.humidity);
  else snprintf(buf, sizeof(buf), "湿度 --");
  lv_label_set_text(weather_humidity, buf);
  if (s.five.valid) snprintf(buf, sizeof(buf), "%.0f%%", s.five.remaining); else snprintf(buf, sizeof(buf), "--%%");
  lv_label_set_text(five_value, buf);
  if (s.week.valid) snprintf(buf, sizeof(buf), "%.0f%%", s.week.remaining); else snprintf(buf, sizeof(buf), "--%%");
  lv_label_set_text(week_value, buf);
  displayTime(s.five.reset_epoch, temp, sizeof(temp)); snprintf(buf, sizeof(buf), "重置 %s", temp); lv_label_set_text(five_reset, buf);
  displayTime(s.week.reset_epoch, temp, sizeof(temp)); snprintf(buf, sizeof(buf), "重置 %s", temp); lv_label_set_text(week_reset, buf);
  countdown(s.five.reset_epoch, now, buf, sizeof(buf)); lv_label_set_text(five_countdown, buf);
  countdown(s.week.reset_epoch, now, buf, sizeof(buf)); lv_label_set_text(week_countdown, buf);
  lv_bar_set_value(five_bar, s.five.valid ? static_cast<int>(s.five.remaining) : 0, LV_ANIM_OFF);
  lv_bar_set_value(week_bar, s.week.valid ? static_cast<int>(s.week.remaining) : 0, LV_ANIM_OFF);
  lv_obj_set_style_bg_color(five_bar, lv_color_hex(s.five.valid && s.five.remaining <= 20 ? WARNING : GREEN), LV_PART_INDICATOR);
  lv_obj_set_style_bg_color(week_bar, lv_color_hex(s.week.valid && s.week.remaining <= 20 ? WARNING : BLUE), LV_PART_INDICATOR);
  displayTime(s.updated_epoch, temp, sizeof(temp)); snprintf(buf, sizeof(buf), "读取 %s", temp);
  lv_label_set_text(page_update, s.has_data ? buf : "读取 --");
}
} // namespace

void setup() {
  Serial.begin(115200);
  delay(1500); // Give the USB serial monitor time to attach during hardware testing.
  Serial.println("[boot] setup");
  setenv("TZ", "UTC0", 1); tzset();
  Wire.begin(I2C_SDA, I2C_SCL);
  Serial.println("[boot] I2C ready; probing AXP2101");
  if (!power.begin(Wire, AXP2101_SLAVE_ADDRESS, I2C_SDA, I2C_SCL)) {
    Serial.println("AXP2101 not detected"); return;
  }
  Serial.println("[boot] AXP2101 found; restoring RTC");
  restoreRtc();
  Serial.println("[boot] resetting display");
  power.setALDO3Voltage(3300); power.enableALDO3(); delay(100);
  power.disableALDO3(); delay(100); power.enableALDO3(); delay(150);
  static lv_disp_drv_t drv;
  esp_err_t lcd_error = waveshare_lcd_begin(&drv);
  if (lcd_error != ESP_OK) { Serial.printf("LCD initialization failed: %s\n", esp_err_to_name(lcd_error)); return; }
  Serial.println("[boot] display initialized; initializing touch and LVGL");
  pinMode(TOUCH_RST, OUTPUT); digitalWrite(TOUCH_RST, HIGH); delay(200);
  digitalWrite(TOUCH_RST, LOW); delay(200); digitalWrite(TOUCH_RST, HIGH); delay(200);
  pinMode(TOUCH_INT, INPUT_PULLUP);
  lv_init();
  constexpr int pixels = WIDTH * 30;
  draw_pixels = static_cast<lv_color_t *>(heap_caps_malloc(pixels * sizeof(lv_color_t), MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL));
  if (!draw_pixels) { Serial.println("Insufficient DMA buffer memory"); return; }
  lv_disp_draw_buf_init(&draw_buf, draw_pixels, nullptr, pixels);
  lv_disp_drv_init(&drv);
  drv.hor_res = WIDTH; drv.ver_res = HEIGHT; drv.flush_cb = waveshare_lcd_flush; drv.rounder_cb = roundArea; drv.draw_buf = &draw_buf;
  lv_disp_drv_register(&drv);
  static lv_indev_drv_t indev; lv_indev_drv_init(&indev);
  indev.type = LV_INDEV_TYPE_POINTER; indev.read_cb = readTouch; lv_indev_drv_register(&indev);
  data_mutex = xSemaphoreCreateMutex();
  if (!data_mutex) { Serial.println("Mutex allocation failed"); return; }
  createUi();
  Serial.println("[boot] UI created");
  xTaskCreate(pollTask, "status", 8192, nullptr, 1, &network_task);
  Serial.println("[boot] setup complete");
}
void loop() {
  static char serial_command[16]{};
  static size_t serial_len = 0;
  while (Serial.available()) {
    const char ch = static_cast<char>(Serial.read());
    if (ch == '\r' || ch == '\n') {
      serial_command[serial_len] = '\0';
      if (strcmp(serial_command, "mem") == 0) {
        lv_mem_monitor_t lv_memory{};
        lv_mem_monitor(&lv_memory);
        Serial.printf("[mem] heap_total=%lu heap_free=%lu heap_min_free=%lu heap_max_block=%lu\n",
                      static_cast<unsigned long>(ESP.getHeapSize()),
                      static_cast<unsigned long>(ESP.getFreeHeap()),
                      static_cast<unsigned long>(ESP.getMinFreeHeap()),
                      static_cast<unsigned long>(ESP.getMaxAllocHeap()));
        Serial.printf("[mem] lvgl_total=%lu lvgl_free=%lu lvgl_max_block=%lu\n",
                      static_cast<unsigned long>(lv_memory.total_size),
                      static_cast<unsigned long>(lv_memory.free_size),
                      static_cast<unsigned long>(lv_memory.free_biggest_size));
      }
      serial_len = 0;
    } else if (serial_len < sizeof(serial_command) - 1) {
      serial_command[serial_len++] = ch;
    }
  }
  if (data_mutex) {
    if (ntp_sync_pending) {
      ntp_sync_pending = false;
      time_t now = time(nullptr);
      if (now >= MIN_VALID_TIME) {
        clock_valid = true; clock_from_rtc = false;
        Serial.println("[time] synchronized by NTP");
        if (!saveRtc(now)) Serial.println("RTC sync unavailable");
      }
    }
    static uint32_t last_render = 0;
    if (millis() - last_render > 1000) { render(); last_render = millis(); }
    lv_timer_handler();
    int action = pending_action; pending_action = 0;
    if (action == -1 || action == 1) { showPage(current_page + action); render(); }
    else if (action == 2 && network_task) xTaskNotifyGive(network_task);
  }
  delay(10);
}
