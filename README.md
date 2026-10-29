# Codex 天气桌面屏（Wi-Fi 版）

使用微雪 **ESP32-C6-Touch-AMOLED-2.16** 和一台 Windows 电脑，显示时间、日期、长沙天气，以及使用 ChatGPT 账号登录的 Codex 五小时和每周剩余额度与重置时间。屏幕左右滑动切换两个页面，轻点屏幕可刷新。此项目不需要云服务器，也不提供蓝牙连接或 DeepSeek 显示。

本项目是 Arduino + PlatformIO 固件、Windows Python 数据服务和网页布局预览。已在上述型号的实物上验证屏幕、触摸、Wi-Fi、天气及两项 Codex 额度；其他屏幕型号、操作系统及不同的 Codex 版本未做完整验证。

## 工作方式

```text
Codex 本机登录状态 ──> Windows 数据服务 <── Open-Meteo 天气
                               │
                     同一局域网 / HTTP
                               │
                    ESP32-C6 触摸屏
```

电脑端每 60 秒更新聚合数据；天气成功时缓存 15 分钟，失败时约 2 分钟重试。屏幕每 30 秒从电脑读取一次，轻点可提前请求；刚启动时请留出首次采集时间。时间通过网络同步，屏幕按北京时间显示。数据源不可用时显示 `--` 或状态提示，并非使用模拟数值冒充真实数据。

电脑必须运行本项目服务，电脑和屏幕需处于可以互访的同一局域网。手机热点也可使用，但某些热点或路由器启用了客户端隔离，会阻止设备间访问；电脑休眠、关机或服务退出后屏幕不能更新。电脑局域网 IP 改变后需要更新固件地址并重新烧录。

## 准备

1. 一块 [微雪 ESP32-C6-Touch-AMOLED-2.16](https://docs.waveshare.net/ESP32-C6-Touch-AMOLED-2.16/Resources-And-Documents)、USB 数据线、支持 2.4 GHz 的 Wi-Fi，以及已连接同一网络的 Windows 电脑。
2. 安装 Python 3.9 或更高版本（包含 Python Launcher `py`），以及可通过命令行运行的 [Codex CLI](https://developers.openai.com/codex/cli/)，使用 ChatGPT 账号登录，并确保该账号有 Codex 额度。可先执行 `codex --version` 检查命令是否可用。
3. 下载本仓库并解压到路径只包含英文字母、数字的目录，如 `C:\work\codex-weather-display`。中文或过长的构建路径在某些 Windows 工具链上可能导致链接失败。以下命令均在项目根目录的 PowerShell 中执行。

## 安装与配置

创建项目专用 Python 环境并安装 PlatformIO（首次编译还会下载工具链和依赖）：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install platformio
```

查看电脑 Wi-Fi 网卡的 IPv4 地址：

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Format-Table InterfaceAlias,IPAddress
```

记下 Wi-Fi 网卡对应的地址，运行交互式配置：

```powershell
.\.venv\Scripts\python.exe setup_local.py
```

输入 2.4 GHz Wi-Fi 名称、密码和上一步的电脑 IPv4。密码输入时不会显示；脚本自动生成设备与电脑之间使用的随机令牌，并生成 `firmware/src/config.h` 和 `backend/config.local.json`。脚本不会覆盖已有配置文件。

这两个文件包含个人网络配置和令牌，受 `.gitignore` 排除，**不要上传或分享**。Wi-Fi 密码和令牌也会进入烧录后的设备及本机编译产物，请勿分享包含真实配置的固件文件。此令牌只控制设备访问本地服务，不是 ChatGPT 密码或 API Key。

## 编译和烧录

使用 USB 数据线连接开发板。在设备管理器中查看对应 COM 端口，替换下面的 `COM5`：

```powershell
.\firmware\build.ps1
.\firmware\build.ps1 -Upload -Port COM5
```

首次编译可能需要较长时间。烧录会替换板上现有程序，请事先备份需要保留的内容。完成后开发板重启；如遇黑屏，检查板型、供电和 USB 数据线，不要将其他型号固件直接用于此屏。

## 启动电脑端服务

在项目根目录运行，并保持窗口打开：

```powershell
.\.venv\Scripts\python.exe backend\run_bridge.py
```

首次运行可能出现 Windows 防火墙提示：只在可信的专用网络允许局域网访问 8787 端口。服务启动后等待约一分钟，屏幕应显示天气与额度；滑动可切换页面。屏幕连接的是电脑局域网 IPv4，不是 `127.0.0.1`。

Codex 数据由本机 `codex app-server` 使用本地登录状态获取，不读取、显示或发送认证凭据。脚本需要能在服务进程的 PATH 中找到 `codex`；找不到时可设置 `DESK_CODEX_EXE` 指向实际的 `codex.exe`。Codex 的登录、账户权限或 app-server 接口变化可能导致额度不可用。

HTTP 传输未加密。请只在可信局域网使用，不要将 8787 端口映射到公网；同网段的流量仍可能被其他人观察到。电脑服务绑定全部网卡并使用随机令牌验证，防火墙也应限制为可信网络。

## 修改和排查

- **屏幕离线**：确认服务窗口仍在运行、电脑和屏幕 Wi-Fi 可互访、Windows 防火墙允许访问，并检查电脑 IP 是否发生变化。
- **天气不显示**：确认电脑可以访问 Open-Meteo；天气失败不会阻止 Codex 数据更新。
- **Codex 显示 `--`**：确认 `codex --version` 可运行、CLI 使用有额度的 ChatGPT 账号登录；等待一次刷新。五小时和每周窗口由 app-server 返回，未返回时不会猜测。
- **换 Wi-Fi 或电脑 IP**：修改 `firmware/src/config.h` 中对应字段后重新编译和烧录。若令牌改变，请同时修改 `backend/config.local.json`；两个文件的令牌必须一致。
- **换天气位置**：启动服务之前设置 `DESK_WEATHER_CITY`、`DESK_WEATHER_LATITUDE`、`DESK_WEATHER_LONGITUDE`；三个值需匹配。固件中文字库只包含有限字符，其他城市建议使用英文或拼音。默认是长沙。
- **仅预览**：运行 `.\.venv\Scripts\python.exe backend\server.py`，打开 <http://127.0.0.1:8787/>。默认是模拟数据，页面会明确标记，不是实时额度。
- **测试**：在 `backend` 目录运行 `..\.venv\Scripts\python.exe -m unittest -v test_server`。测试使用构造数据，不需要账户凭据。

## 文件与许可

`firmware/` 是设备程序，`backend/` 是本机服务，`simulator/` 是浏览器交互预览，`setup_local.py` 生成本地配置。项目自有代码以 MIT 许可发布；第三方硬件驱动、参考项目及字库分别遵循其自身许可，详见 [THIRD_PARTY.md](THIRD_PARTY.md)。
