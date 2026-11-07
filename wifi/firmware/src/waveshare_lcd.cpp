// Uses Waveshare's board-specific SH8601-compatible QSPI transport.
#include "waveshare_lcd.h"
#include "esp_lcd_sh8601.h"
#include <driver/spi_master.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <Arduino.h>

namespace {
esp_lcd_panel_handle_t panel = nullptr;
constexpr int width = 480;
constexpr int lines = 30;
constexpr uint8_t a10[] = {0x10}, aa0[] = {0xa0}, a20[] = {0x20}, a80[] = {0x80};
constexpr uint8_t a55[] = {0x55}, a00[] = {0}, a30[] = {0x30}, aff[] = {0xff};
constexpr uint8_t bound[] = {0, 0, 1, 0xdf};
const sh8601_lcd_init_cmd_t init_cmds[] = {
  {0x11, nullptr, 0, 600}, {0xfe, a20, 1, 0}, {0x19, a10, 1, 0},
  {0x1c, aa0, 1, 0}, {0xfe, a00, 1, 0}, {0xc4, a80, 1, 0},
  {0x3a, a55, 1, 0}, {0x35, a00, 1, 0}, {0x36, a30, 1, 0},
  {0x53, a20, 1, 0}, {0x51, aff, 1, 0}, {0x63, aff, 1, 0},
  {0x2a, bound, 4, 0}, {0x2b, bound, 4, 0}, {0x29, nullptr, 0, 100},
};
// LVGL v8 explicitly permits lv_disp_flush_ready() in an interrupt callback.
bool color_done(esp_lcd_panel_io_handle_t, esp_lcd_panel_io_event_data_t *, void *ctx) {
  lv_disp_flush_ready(static_cast<lv_disp_drv_t *>(ctx));
  return false;
}
}

esp_err_t waveshare_lcd_begin(lv_disp_drv_t *disp) {
  if (!disp || panel) return ESP_ERR_INVALID_STATE;
  spi_bus_config_t bus = {};
  bus.sclk_io_num = 0; bus.data0_io_num = 1; bus.data1_io_num = 2;
  bus.data2_io_num = 3; bus.data3_io_num = 4;
  bus.max_transfer_sz = width * lines * sizeof(lv_color_t);
  esp_err_t result = spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO);
  if (result != ESP_OK) return result;

  esp_lcd_panel_io_spi_config_t io = {};
  io.cs_gpio_num = 15; io.dc_gpio_num = -1; io.spi_mode = 0;
  io.pclk_hz = 40 * 1000 * 1000; io.trans_queue_depth = 1;
  io.on_color_trans_done = color_done; io.user_ctx = disp;
  io.lcd_cmd_bits = 32; io.lcd_param_bits = 8; io.flags.quad_mode = true;
  esp_lcd_panel_io_handle_t io_handle = nullptr;
  result = esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)SPI2_HOST, &io, &io_handle);
  if (result != ESP_OK) return result;

  sh8601_vendor_config_t vendor = {};
  vendor.init_cmds = init_cmds;
  vendor.init_cmds_size = sizeof(init_cmds) / sizeof(init_cmds[0]);
  vendor.flags.use_qspi_interface = 1;
  esp_lcd_panel_dev_config_t cfg = {};
  cfg.reset_gpio_num = GPIO_NUM_NC; cfg.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
  cfg.bits_per_pixel = 16; cfg.vendor_config = &vendor;
  result = esp_lcd_new_panel_sh8601(io_handle, &cfg, &panel);
  if (result != ESP_OK) return result;
  return esp_lcd_panel_init(panel);
}

void waveshare_lcd_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *pixels) {
  if (!panel) { lv_disp_flush_ready(disp); return; }
  const esp_err_t result = esp_lcd_panel_draw_bitmap(panel, area->x1, area->y1,
                                                     area->x2 + 1, area->y2 + 1, pixels);
  if (result != ESP_OK) {
    Serial.printf("LCD flush failed: %s\n", esp_err_to_name(result));
    lv_disp_flush_ready(disp);
  }
}
