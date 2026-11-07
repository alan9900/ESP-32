"""Create matching local device and server configuration without printing secrets."""
import getpass
import ipaddress
import json
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parent
BOARD = ROOT / "firmware" / "src" / "config.h"
BRIDGE = ROOT / "backend" / "config.local.json"


def c_string(value):
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("不能包含控制字符")
    return json.dumps(value, ensure_ascii=False)


def main():
    if BOARD.exists() or BRIDGE.exists():
        raise SystemExit("配置文件已存在，为防止覆盖请先自行备份或移走旧配置。")
    ssid = input("2.4 GHz Wi-Fi 名称: ").strip()
    password = getpass.getpass("Wi-Fi 密码（输入时不显示，开放网络直接回车）: ")
    address = input("电脑局域网 IPv4 地址: ").strip()
    try:
        ip = ipaddress.IPv4Address(address)
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
            raise ValueError("请输入电脑的局域网 IPv4 地址")
        if not ssid or len(ssid.encode('utf-8')) > 32:
            raise ValueError("Wi-Fi 名称必须为 1 至 32 字节")
        if password and not 8 <= len(password.encode('utf-8')) <= 63:
            raise ValueError("Wi-Fi 密码需为 8 至 63 字节，开放网络请留空")
        token = secrets.token_hex(32)
        config = ("#pragma once\n"
                  f"#define DASH_WIFI_SSID {c_string(ssid)}\n"
                  f"#define DASH_WIFI_PASSWORD {c_string(password)}\n"
                  f"#define DASH_STATUS_URL {c_string('http://' + str(ip) + ':8787/api/status')}\n"
                  f"#define DASH_BEARER_TOKEN {c_string(token)}\n"
                  "#define DASH_REFRESH_SECONDS 30\n")
    except ValueError as exc:
        raise SystemExit(f"配置有误：{exc}") from None
    # Exclusive creation avoids overwriting another configuration. Roll back only
    # the file created by this invocation if the second creation fails.
    created_board = False
    try:
        with BOARD.open('x', encoding='utf-8', newline='\n') as f:
            created_board = True
            f.write(config)
        with BRIDGE.open('x', encoding='utf-8', newline='\n') as f:
            json.dump({'host': '0.0.0.0', 'access_token': token}, f, ensure_ascii=False, indent=2)
            f.write('\n')
    except Exception:
        if created_board:
            BOARD.unlink(missing_ok=True)
        raise
    print("配置完成。密钥未输出；请保护两个本地配置文件及烧录产物。")


if __name__ == '__main__':
    main()
