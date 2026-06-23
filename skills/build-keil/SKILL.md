---
name: build-keil
description: 当需要通过 Keil MDK 命令行编译嵌入式工程，调用自带脚本解析工程文件、执行构建并定位固件产物时使用。
---

# 构建 Keil MDK 工程

## 适用场景

- `Project Profile` 中标明 `build_system: keil` 或工作区中存在 `.uvprojx` / `.uvproj` 文件。
- 用户希望对 Keil MDK 工程执行编译、重编译或确认固件产物。
- 烧录或调试流程需要新的 `AXF`（ELF）、`HEX` 或 `BIN`。
- 需要在编译前确认 Keil MDK 环境是否就绪（UV4.exe、ARMCC/ARMCLANG）。

## 必要输入

- 工作区路径或 `.uvprojx` / `.uvproj` 工程文件路径，或一份已有的 `Project Profile`。
- 可选的构建目标名称、UV4.exe 路径和日志输出路径。

## 自动探测

- 脚本启动即自动复用工程根目录 `.em_skill.json` 中上次成功的 profile 作为默认参数（显式参数优先，无需先手动传 `--resume`）；`--resume` 仅用于断言缓存必须存在，无缓存则非零退出。无缓存或用户明确要求重新探测时，脚本自动回退到正常扫描。
- 脚本自动搜索常见 Keil MDK 安装路径和环境变量（`KEIL_ROOT`、`MDK_ROOT`）定位 UV4.exe。
- 解析 `.uvprojx` 工程文件中的 Target 列表，提取芯片型号、输出目录、工具链（ARMCC/ARMCLANG）。
- 若未指定目标，默认使用工程中的第一个 Target。
- 在输出目录中搜索 AXF、HEX、BIN 产物，按 `ELF > HEX > BIN` 排序。
- 若存在多个同样合理的工程文件或目标，列出候选而不是静默猜测。

## 执行步骤

1. 先阅读 [references/usage.md](references/usage.md)，确认本次是环境探测、工程扫描、列出目标，还是执行编译。
2. 对于单工程、单目标的常见场景，优先使用一次调用完成探测+编译：
   ```bash
   python scripts/keil_builder.py --detect --project <工程文件> --target <目标名>
   ```
   这样只启动一次 Python 进程，避免 `--detect` → `--list-targets` → `--build` 三次串行调用的开销。
3. 仅在需要交互式选择（多个工程文件或多个目标需要用户确认）时，才分步执行 `--scan`、`--list-targets`。
4. 读取脚本输出的构建结果和产物扫描报告，重点关注首选产物（AXF/ELF > HEX > BIN）、错误/警告统计和失败分类。
5. 将构建目标、产物路径、芯片型号和工具链信息写回 `Project Profile`，并在需要时交给下游 skill。

## 失败分流

- 当 Keil MDK 未安装或 UV4.exe 不可用时，返回 `environment-missing`。
- 当工程文件损坏、目标名无效或编译因配置问题失败时，返回 `project-config-error`。
- 当编译看似成功但未找到可烧录或可调试产物时，返回 `artifact-missing`。
- 当存在多个同样合理的工程文件或目标，且任意选择都不安全时，返回 `ambiguous-context`。

## 平台说明

- Keil MDK 仅在 Windows 上原生运行，UV4.exe 命令行编译需要 Windows 环境。
- 自带脚本在非 Windows 平台上仍可执行工程解析（`--list-targets`）、工程扫描（`--scan`）和产物扫描（`--scan-artifacts`），但实际编译会被阻塞。
- 编译日志可能包含 GBK 编码的中文字符，脚本会自动尝试多种编码。
- 输出中的产物路径应保持为绝对路径，方便下游烧录和调试 skill 直接复用。

## 输出约定

脚本执行完成后，必须将以下关键信息提取并呈现给用户：

- 编译状态（成功/失败）
- 工程文件和目标名
- 芯片型号和工具链（如 STM32F103RC [ARMCC]）
- 固件大小明细（Code、RO-data、RW-data、ZI-data）及 Flash/RAM 汇总
- 编译耗时
- 产物列表（AXF/HEX/BIN 及文件大小）
- 错误/警告统计
- 若失败：失败分类和日志证据

示例输出格式：

```
编译成功 ✅
  工程: Demo02.uvprojx → 目标: Demo02
  芯片: STM32F103RC | 工具链: ARMCC
  固件大小: Flash ≈ 3.2 KB  RAM ≈ 1.6 KB
  产物: Demo02.axf (518.9 KB), Demo02.hex (9.0 KB)
  编译耗时: 00:00:05
```

- 用 `artifact_path`、`artifact_kind`、`target_mcu` 和 `toolchain` 更新 `Project Profile`。
- 成功后推荐 `flash-keil`、`flash-openocd` 或 `debug-gdb-openocd`。

## 交接关系

- 当下一步意图是给硬件烧录程序时，将成功构建结果交给 `flash-keil`（使用 Keil 内置调试器）或 `flash-openocd`（使用 OpenOCD）。
- 当下一步需要符号信息或调试会话时，将成功构建结果交给 `debug-gdb-openocd`。