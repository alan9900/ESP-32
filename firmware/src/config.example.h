#pragma once
// Copy to config.h. Never commit config.h; these values stay on your device.
#define DASH_WIFI_SSID "YOUR_2_4GHZ_WIFI"
#define DASH_WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
// Address of the companion on the SAME trusted LAN; use its LAN IP, not localhost.
#define DASH_STATUS_URL "http://192.168.1.100:8787/api/status"
// Same optional token configured in the companion; do not expose HTTP to the Internet.
#define DASH_BEARER_TOKEN ""
#define DASH_REFRESH_SECONDS 30
