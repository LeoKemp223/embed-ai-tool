---
name: flash-platformio
description: 当需要通过 PlatformIO 烧录固件到目标板时使用，利用 platformio.ini 中的上传配置自动完成烧录。
---

# PlatformIO 烧录

## 适用场景

- `Project Profile` 中标明 `build_system: platformio` 或工作区中存在 `platformio.ini`。
- 用户希望将编译产物烧录到目标板，利用 PlatformIO 内置的上传机制。
- 支持串口、JTAG、DFU 等多种上传协议，由 `platformio.ini` 中的 `upload_protocol` 决定。

## 必要输入

- PlatformIO 工程目录（包含 `platformio.ini`）。
- 可选的环境名称和上传端口。

## 自动探测

- 脚本启动即自动复用工程根目录 `.em_skill.json` 中上次成功的 profile 作为默认参数（显式参数优先，无需先手动传 `--resume`）；`--resume` 仅用于断言缓存必须存在，无缓存则非零退出。无缓存或用户明确要求重新探测时，脚本自动回退到正常扫描。
- 自动定位 `pio` CLI。
- 解析 `platformio.ini` 中的环境列表和 `upload_protocol`。
- 若未指定环境，使用 `default_envs` 或第一个环境。
- 可列出已连接设备帮助用户确认端口。

## 执行步骤

1. 先阅读 [references/usage.md](references/usage.md)，确认本次操作。
2. 对于常见场景，直接一次调用完成烧录：
   ```bash
   python scripts/pio_flasher.py --flash --project-dir <工程目录> --env <环境名>
   ```
3. 若需指定上传端口：
   ```bash
   python scripts/pio_flasher.py --flash --project-dir <工程目录> --env <环境名> --upload-port COM3
   ```
4. 读取脚本输出的烧录结果报告，关注成功/失败状态和证据。
5. 将烧录结果写回 `Project Profile`，推荐下一步 skill。

## 失败分流

- `connection-failure`：设备未连接、串口被占用或权限不足。
- `project-config-error`：板卡配置无效或环境名不存在。
- `upload-failure`：上传过程中出错。

## 输出约定

示例输出格式：

```
烧录成功 ✅
  工程: ESP32_DEV → 环境: esp32dev
  板卡: esp32dev | 平台: espressif32
  固件: firmware.bin (200.0 KB)
  耗时: 15.3 秒
```

- 成功后推荐 `serial-monitor`（查看串口输出）或 `debug-platformio`（在线调试）。
- 失败时输出失败分类和日志证据。

## 交接关系

- 从 `build-platformio` 接收编译成功的工程信息。
- 烧录成功后交给 `serial-monitor`（查看串口输出）或 `debug-platformio`（在线调试）。
