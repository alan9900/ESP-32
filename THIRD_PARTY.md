# 第三方代码和资料

- 屏幕硬件初始化参考微雪 [ESP32-C6-Touch-AMOLED-2.16 官方示例](https://gitee.com/waveshare/ESP32-C6-Touch-AMOLED-2.16)。
- 部分屏幕、电源和触摸实现参考 [cc-usage-display](https://github.com/wangjian124/cc-usage-display)，保留原作者 MIT 许可：`wifi/firmware/LICENSE-REFERENCE.txt`。
- `wifi/firmware/src/esp_lcd_sh8601.c` 和 `.h` 保留 Espressif 的版权及 Apache-2.0 SPDX 标识；许可全文见 `wifi/firmware/APACHE-2.0.txt`。
- 生成字库所用 Noto Sans SC 遵循 SIL Open Font License 1.1，许可见 `wifi/firmware/NOTO-SANS-SC-OFL.txt`。
- PlatformIO、Arduino ESP32、LVGL、ArduinoJson 和 XPowersLib 的各自许可随其依赖发布；不包含其完整源码于本仓库。

- 蓝牙版使用相同的硬件驱动及字库；对应许可证副本保留在 `ble/`。
