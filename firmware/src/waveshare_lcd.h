#pragma once

#include <Arduino.h>
#include <esp_err.h>
#include <lvgl.h>

// Reset the panel through AXP2101 ALDO3 before calling this once.
// disp must remain valid for the lifetime of the panel; it is also passed to
// lv_disp_drv_register. Configure LV_COLOR_16_SWAP=1 for direct RGB565 DMA.
esp_err_t waveshare_lcd_begin(lv_disp_drv_t *disp);
void waveshare_lcd_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *pixels);
