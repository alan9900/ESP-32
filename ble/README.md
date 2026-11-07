# 蓝牙版：Codex 天气桌面屏

蓝牙版由 Windows 电脑采集天气和 Codex 额度，经 BLE 发送给开发板。开发板无需连接 Wi-Fi；电脑需要联网、开启蓝牙并在通信范围内持续运行发送程序。固定型号的开发板和 Windows 电脑已实测两页显示、触摸切换、PIN 配对及真实数据；长期运行、断电恢复和异常安全场景仍需进一步验证。

目录中的 `dashboard/` 是双页面固件，`ble_backend/` 是电脑端数据采集，`pc/` 是蓝牙发送程序；`firmware/` 是仅用于调试连接的 `BLE TEST` 探针，**日常使用请烧录 `dashboard/`**。Wi-Fi 方案另见 [wifi/](../wifi/README.md)。

## 安装与烧录

准备微雪 ESP32-C6-Touch-AMOLED-2.16、USB 数据线、具备蓝牙的 Windows 电脑、Python 3.10+ 和已使用 ChatGPT 账号登录的 Codex CLI。建议将仓库放在简短的英文路径。**以下命令均在仓库根目录运行**，首次编译需要下载 PlatformIO 工具链和依赖：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install platformio -r .\ble\pc\requirements.txt
.\.venv\Scripts\python.exe -m platformio run --project-dir .\ble\dashboard
```

连接开发板，在设备管理器中查看 COM 端口，将下面的 `COM5` 替换为实际端口。烧录会覆盖板上应用和相关分区；如需保留现有固件、启动器或数据，请先备份并验证备份。不要随意整片擦除 Flash。

```powershell
.\.venv\Scripts\python.exe -m platformio run --project-dir .\ble\dashboard --target upload --upload-port COM5
```

烧录后等待设备重启；如果仍是旧画面，可以短按 RESET/RST 或拔插 USB。进一步排查和回刷见[烧录指南](../docs/FLASHING.md)。

## 配对与运行

1. 首次配对时，在开发板未连接状态下长按触摸屏约 2 秒并松开，打开限时配对窗口。
2. 在 Windows 蓝牙设置中选择“添加设备”，选择 `ESP32-C6-Desk`，在系统提示框输入开发板屏幕显示的六位 PIN。不要公开配对码；超时后可重新长按屏幕。
3. 在仓库根目录启动电脑端发送程序：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\ble\pc\start_live.ps1
   ```

电脑端约每 60 秒采集、每 30 秒发送一次。首次启动请等待采集和发送；屏幕的“模拟数据”表示测试值，“--”或离线状态表示当前数据不可用。电脑重启后需要重新运行启动命令，本版本没有设置开机自启。`start_live.ps1` 使用仓库根目录 `.venv`，也支持通过 `-PythonPath` 指定已安装 Bleak 的其他 Python。

## 安全和排查

- 电脑必须能够通过 PATH 找到 `codex`，并使用有 Codex 额度的 ChatGPT 账号登录。Codex 接口或账号状态变化可能影响数据读取。
- 电脑端只发送显示所需的白名单字段；认证凭据保留在电脑。发送前检查 Windows 认证配对和受保护的 GATT 读取；仅发现一个匹配设备并不代表已验证身份。
- 如果屏幕显示离线，检查电脑蓝牙、后台程序、配对状态及设备距离。程序会尝试断线重连；某些系统配对问题仍可能需要人工排查。不要随意擦除 Flash。
- 电脑端日志保存在仓库的 `.project_storage/ble/`，只记录程序状态。不要分享配对码、个人配置或账户信息。

代码和依赖许可详见[仓库许可说明](../THIRD_PARTY.md)，本目录也保留参考项目、显示驱动及字库的许可文件。
