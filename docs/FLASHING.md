# 开发板烧录与恢复指南

本指南面向微雪 **ESP32-C6-Touch-AMOLED-2.16**、Windows 和仓库中经过实机验证的 **Wi-Fi 版**。其他 ESP32-C6 板即便芯片相同，也可能使用不同显示、电源、触摸和引脚，不应直接套用。蓝牙版基本链路已实测，详见 [开发状态](DEVELOPMENT_STATUS.md)。

## 烧录前

1. 使用能传输数据的 USB 线连接电脑并稳定供电，在 Windows 设备管理器中确认开发板 COM 端口。示例中的 `COM5` 必须换成实际端口；如果串口监视器占用端口，先关闭它。
2. 烧录会覆盖板上程序及所写入的 Flash 区域，可能影响原有启动器或程序。若需要保留出厂系统、个人数据或其他固件，先依据[微雪官方资料和示例](https://docs.waveshare.net/ESP32-C6-Touch-AMOLED-2.16/Resources-And-Documents)自行完成备份并验证备份；不要随意整片擦除 Flash，避免丢失配置及配对数据。
3. 安装 Python 3.9+、PlatformIO 和 Codex CLI，确认 Codex 使用自己的 ChatGPT 账号登录。推荐将仓库放在简短英文路径，避免部分 Windows 工具链不兼容中文路径。首次编译需要网络下载依赖。
4. 开发板连接 2.4 GHz Wi-Fi；电脑与板子需可通过局域网互访。访客网络或热点的客户端隔离、Windows 防火墙及电脑 IP 变化都可能造成离线。
5. 运行根目录 `setup_local.py` 创建个人配置。`firmware/src/config.h`、`backend/config.local.json` 和编译后的固件含个人网络信息或局域网访问令牌，必须留在本机，不要提交、分享或截图泄露。配置示例和源码可以公开。

## 编译与烧录 Wi-Fi 版

从仓库根目录的 PowerShell 运行，详细的准备和交互式配置见[首页](../README.md)：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install platformio
.\.venv\Scripts\python.exe setup_local.py
.\firmware\build.ps1
.\firmware\build.ps1 -Upload -Port COM5
```

`-Upload` 会实际写入 Flash；不带该选项只编译。等待工具明确报告成功，过程中不要拔线。构建和烧录都使用 `firmware/platformio.ini` 固定的 Arduino + PlatformIO 环境及该板显示驱动；不要使用针对其他显示板的固件。

```powershell
.\.venv\Scripts\python.exe backend\run_bridge.py
```

保持电脑端窗口运行，等待约一分钟进行首次采集，然后检查桌面、Codex 页面、天气和剩余额度，左右滑动切页。轻点屏幕可以提前刷新；`--` 表示当前数据不可用。电脑端需要能够通过 PATH 找到 `codex`，天气服务与 Codex 接口须可访问。

## 编译与烧录蓝牙版

蓝牙版使用同一个硬件驱动，但项目目录独立。按首页准备好项目 `.venv` 后，在仓库根目录运行，`COM5` 替换成实际端口：

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\ble\pc\requirements.txt
.\.venv\Scripts\python.exe -m platformio run --project-dir .\ble\dashboard
.\.venv\Scripts\python.exe -m platformio run --project-dir .\ble\dashboard --target upload --upload-port COM5
```

上传目标会写入固件及相关启动和分区区域，替换板上应用；不要对正在使用的板误操作。若 Windows 未配对，按 [蓝牙说明](../ble/README.md)进行 PIN 配对；之后运行 `.\ble\pc\start_live.ps1` 启动电脑端。蓝牙版在本项目指定开发板上已显示真实天气及 Codex 额度，但其他设备和长期运行尚未完整验证。Wi-Fi 本地配置和源码不会因切换蓝牙而删除，回刷方法见下方。

## 常见问题

- **烧录成功但仍是旧画面或黑屏**：先短按 RESET/RST；若仍无变化，拔下 USB 再重新插入，等待几秒。此前这块板测试中重新上电后才启动新程序。确认线缆供电、板型和本项目板级显示驱动；本项目早期非官方显示传输实现曾导致完全黑屏，已改用微雪示例驱动。
- **找不到串口或连接失败**：检查数据线、设备管理器端口、占用串口的软件和供电。必要时按[官方文档](https://docs.waveshare.net/ESP32-C6-Touch-AMOLED-2.16/Resources-And-Documents)使用 BOOT 进入下载模式；不要长按 BOOT 代替正常复位。
- **界面正常但离线、无天气或额度**：启动电脑服务并确认电脑与板子处于可互访网络，检查局域网 IPv4、令牌和防火墙；确认电脑联网和 Codex 登录状态，等待首次刷新。配置变化后须重新编译烧录对应固件。
- **已经烧录蓝牙测试版，如何恢复 Wi-Fi**：保留原 Wi-Fi 本地配置、源码和电脑服务；连接开发板，按上面的 Wi-Fi `-Upload` 命令重新编译烧录。若界面没有切换，短按复位或拔插 USB。若配置丢失，重新运行 `setup_local.py` 并按提示配置；脚本不会覆盖已有配置文件。

普通重新编译烧录能恢复本项目 Wi-Fi 应用，但不等于恢复出厂多固件启动器或擦除前的所有 Flash 数据；这些内容只有在事先备份且恢复方式正确时才能恢复。
