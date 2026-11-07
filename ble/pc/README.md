# Windows 蓝牙发送端隔离原型

`demo_sender.py` 仅发送**构造的模拟数据**，不会读取账户信息或任何 Key。`live_sender.py` 通过经过认证的连接发送天气与 Codex 显示字段；`auto_live.py` 负责发现附近唯一的显示设备并调用它，`start_live.ps1` 用于后台启动。2026-11-07 已在指定 Windows 电脑和开发板验证真实数据显示；未配对读写拒绝、异常重配对和长期运行稳定性仍需进一步验证。

## 协议

- 服务：`8bf540f4-54ca-49cf-b7e5-e191b62a0001`。
- 写特征：`8bf540f4-54ca-49cf-b7e5-e191b62a0002`；状态特征：`8bf540f4-54ca-49cf-b7e5-e191b62a0003`。
- 每帧至多 20 字节，以兼容默认 ATT MTU；每个 GATT 写入使用 `response=True`，并等待特征的应用层确认后再发下一帧。连接和每帧操作都有超时。
- `BEGIN`: `01` + uint16 小端长度 + uint32 小端 CRC32；`DATA`: `02` + uint16 小端分片序号（从零开始）+ 最多 17 字节；`END`: `03`。单消息最多 4096 字节。
- 状态为 3 字节：状态码 + uint16 小端下一个分片序号。BEGIN 接受后 `(1,0)`；DATA 的序号 n 接受后 `(1,n+1)`；END 完成后 `(2,分片总数)`；状态码 `3` 是失败。
- `host_utc` 是电脑发送时的 UTC 时间，`updated_at` 和 `weather.updated_at` 分别保留原始采集时间。固件校时必须在受保护连接、完整数据验证后执行。

## 离线测试

```powershell
cd ble/pc
py -3 -m unittest -v test_protocol
```

实际蓝牙探针依赖 `bleak`；建议安装进独立虚拟环境。首先长按探针的触摸屏开启限时配对，再在 Windows 蓝牙设置中配对 `ESP32-C6-Desk`，仅在 Windows 系统提示框输入开发板屏幕显示的六位码；不要把配对码写入聊天或日志。之后运行 `demo_sender.py --once`。当前 Bleak 3.0.1 的 Windows 自动配对实现只处理 `CONFIRM_ONLY`，因此探针不使用 `pair=True` 来代替 PIN 配对。2026-10-29 在用户的板子上验证过 PIN 配对、认证加密、模拟数据完整发送与重连。探针发送演示值并标注 `mode=mock`，不会使用真实数据。

使用真实数据前，必须完成 Windows 与设备端**经过认证的加密配对**；还应进一步验证未配对读写拒绝、异常重配对、断开和重连、过期状态、时钟设置和长期实机资源情况。`protocol.make_payload` 是字段白名单纯函数，没有任何数据读取功能；不要自行向未经验证的蓝牙连接发送真实账户摘要。

`live_sender.py` 使用 `ble/ble_backend/` 内独立的本机数据采集代码，不依赖 Wi-Fi 方案的数据服务或令牌。它要求明确选择设备地址，在 Windows 上检查配对保护级别，为读写特征设置加密和认证要求，再进行受保护的状态读取；验证失败时不启动真实数据采集。Windows 服务发现强制绕过旧缓存。`auto_live.py` 只有发现唯一匹配设备时才启动上述认证流程；自动发现本身不代表身份验证。本方案依赖固定的 Bleak Windows 后端行为，升级后需要重新验证。

参考：[Bleak 客户端](https://bleak.readthedocs.io/en/stable/api/client.html)、[Windows GATT](https://learn.microsoft.com/en-us/windows/apps/develop/devices-sensors/gatt-client)、[ESP32-C6 BLE](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c6/api-guides/ble/overview.html)。
