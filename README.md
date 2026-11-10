# Codex 天气桌面屏

适配微雪 **ESP32-C6-Touch-AMOLED-2.16** 的中文桌面屏，在两页中显示时间、日期、天气，以及使用 ChatGPT 账号登录的 Codex 五小时和每周剩余额度、重置时间。左右滑动切换页面，默认天气为长沙。电脑端通过本机 Codex app-server 和 Open-Meteo 获取数据；不包含 DeepSeek 显示。

## 选择一种连接方案

| | [Wi-Fi 版](wifi/README.md) | [蓝牙版](ble/README.md) |
| --- | --- | --- |
| 连接方式 | 开发板与电脑通过局域网 HTTP 通信 | 开发板与电脑通过 BLE 通信 |
| 网络条件 | 电脑和开发板必须在可互访的局域网，开发板需支持 2.4 GHz Wi-Fi | 电脑需联网和开启蓝牙，开发板不需要连接 Wi-Fi，双方需在蓝牙范围内 |
| 本地程序 | `wifi/backend/` | `ble/ble_backend/` 和 `ble/pc/` |
| 固件 | `wifi/firmware/` | `ble/dashboard/`；`ble/firmware/` 是仅用于测试的探针 |
| 实测状态 | 指定开发板与 Windows 电脑已验证页面、触摸和真实数据 | 指定开发板与 Windows 电脑已验证 PIN 配对、页面、触摸和真实数据；长期稳定性仍需验证 |

**从对应版本的 README 开始复刻**：

- [Wi-Fi 版：安装、配置、烧录与使用](wifi/README.md)
- [蓝牙版：安装、配对、烧录与使用](ble/README.md)
- [国内云中转与米家数据：预选方案](cloud_mijia/README.md)（仅设计，暂缓推进，不提供云版固件）
- [烧录、故障排查与回刷指南](docs/FLASHING.md) · [开发及验证状态](docs/DEVELOPMENT_STATUS.md)

Wi-Fi 和蓝牙是现有的两套独立程序和配置，一块开发板同一时刻运行一套固件，切换需要重新烧录。两者均需要电脑保持开机联网、运行对应的电脑端程序。国内云中转与米家方案仅为预选设计，尚未部署或完成验证。

## 仓库目录

```text
wifi/                     Wi-Fi 版（在该目录内安装与运行）
  firmware/               设备固件与烧录脚本
  backend/                Windows 本地数据服务
  simulator/              网页界面预览
  setup_local.py          生成个人 Wi-Fi 和本地服务配置
ble/                      蓝牙版
  dashboard/              双页面设备固件
  firmware/               蓝牙连接测试探针，不是日常桌面固件
  ble_backend/            独立的电脑端数据采集
  pc/                     Windows 蓝牙发送程序
cloud_mijia/              国内云中转与米家数据预选设计，尚未实现
docs/                     烧录、回刷和开发状态
```

## 隐私与安全

ChatGPT 登录凭据保存在电脑本机，不应上传仓库或发送给开发板。Wi-Fi 名称、密码、本地访问令牌、蓝牙配对码和含个人配置的固件文件也不应公开；`.gitignore` 仅是辅助，上传前仍应自行检查。Wi-Fi 版使用未加密 HTTP，只适合可信局域网，不要映射到公网。蓝牙版使用 Windows PIN 配对和认证加密；异常配对、未配对访问和长期稳定性仍需更多测试。

项目代码许可见 [LICENSE](LICENSE)，第三方驱动和字库许可见 [THIRD_PARTY.md](THIRD_PARTY.md)。
