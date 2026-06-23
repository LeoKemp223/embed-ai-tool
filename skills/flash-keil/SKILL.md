---
name: flash-keil
description: 当需要通过 Keil MDK 内置调试器烧录固件到目标板时使用，利用工程中已配置的调试器和 Flash 算法执行下载。
---

# Keil MDK 烧录

## 适用场景

- `Project Profile` 中标明 `build_system: keil` 或工作区中存在 `.uvprojx` / `.uvproj` 文件。
- 用户希望将编译产物烧录到目标板，且工程已在 Keil 中配置好调试器（ST-Link、J-Link、CMSIS-DAP 等）。
- 不需要额外安装 OpenOCD，直接使用 Keil MDK 内置的 Flash Download 功能。

## 必要输入

- `.uvprojx` / `.uvproj` 工程文件路径（或从 `Project Profile` 获取）。
- 可选的构建目标名称和 UV4.exe 路径。

## 自动探测

- 脚本启动即自动复用工程根目录 `.em_skill.json` 中上次成功的 profile 作为默认参数（显式参数优先，无需先手动传 `--resume`）；`--resume` 仅用于断言缓存必须存在，无缓存则非零退出。无缓存或用户明确要求重新探测时，脚本自动回退到正常扫描。
- 复用 `build-keil` 的 UV4.exe 探测逻辑（配置文件 → 环境变量 → 常见路径 → PATH）。
- 解析工程 XML 中的 `<DriverSelection>` 识别调试器类型（ST-Link、J-Link、CMSIS-DAP、ULINK）。
- 若未指定目标，默认使用工程中的第一个 Target。

## 执行步骤

1. 先阅读 [references/usage.md](references/usage.md)，确认本次操作。
2. 对于常见场景，直接一次调用完成探测+烧录：
   ```bash
   python scripts/keil_flasher.py --detect --flash --project <工程文件> --target <目标名>
   ```
3. 读取脚本输出的烧录结果报告，关注成功/失败状态、调试器类型和日志证据。
4. 将烧录结果写回 `Project Profile`，推荐下一步 skill。

## 失败分流

- `environment-missing`：Keil MDK 未安装或 UV4.exe 不可用。
- `connection-failure`：调试器连接失败（USB 未连接、驱动问题、目标板未上电）。
- `project-config-error`：工程文件中的 Flash 配置无效或目标名不存在。

## 平台说明

- Keil MDK 烧录仅在 Windows 上支持。
- 烧录使用工程中已配置的调试器和 Flash 算法，无需额外配置。
- 烧录日志可能包含 GBK 编码字符，脚本自动处理多种编码。

## 输出约定

脚本执行完成后，必须将以下关键信息提取并呈现给用户：

- 烧录状态（成功/失败）
- 工程文件和目标名
- 芯片型号（如 STM32F103RC）
- 调试器类型（如 ST-Link、J-Link）
- 烧录固件路径和大小（如 Demo02.axf, 519.6 KB）
- 烧录完成时间
- 若失败：失败分类和日志证据

示例输出格式：

```
烧录成功 ✅
  工程: Demo02.uvprojx → 目标: Demo02
  芯片: STM32F103RC | 调试器: ST-Link
  固件: Demo02.axf (519.6 KB)
  状态: Erase Done → Programming Done → Verify OK → Application running
```

- 成功后推荐 `serial-monitor`（查看串口输出）或 `debug-gdb-openocd`（在线调试）。
- 失败时输出失败分类和日志证据，帮助用户定位问题。

## 交接关系

- 从 `build-keil` 接收编译成功的工程信息。
- 烧录成功后交给 `serial-monitor`（查看串口输出）或 `debug-gdb-openocd`（在线调试）。
