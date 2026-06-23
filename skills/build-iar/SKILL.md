---
name: build-iar
description: 当需要通过 IAR Embedded Workbench 命令行编译嵌入式工程，调用自带脚本解析工程文件、执行构建并定位固件产物时使用。
---

# 构建 IAR Embedded Workbench 工程

## 适用场景

- `Project Profile` 中标明 `build_system: iar` 或工作区中存在 `.ewp` / `.eww` 文件。
- 用户希望对 IAR EWARM 工程执行编译、重编译或确认固件产物。
- 烧录或调试流程需要新的 `.out`（ELF）、`HEX` 或 `BIN`。
- 需要在编译前确认 IAR 环境是否就绪（iarbuild.exe、工具链）。

## 必要输入

- 工作区路径或 `.ewp` 工程文件路径，或一份已有的 `Project Profile`。
- 可选的配置名称（configuration）和 IAR 安装路径。

## 自动探测

- 脚本启动即自动复用工程根目录 `.em_skill.json` 中上次成功的 profile 作为默认参数（显式参数优先，无需先手动传 `--resume`）；`--resume` 仅用于断言缓存必须存在，无缓存则非零退出。无缓存或用户明确要求重新探测时，脚本自动回退到正常扫描。
- 脚本自动搜索常见 IAR 安装路径和环境变量（`IAR_ROOT`、`EWARM_ROOT`）定位 iarbuild.exe。
- 解析 `.ewp` 工程文件中的 configuration 列表，提取工具链（ARM/RISCV）、芯片型号、输出目录和输出文件名。
- 若未指定配置，默认使用工程中的第一个 configuration。
- 在输出目录中搜索 .out（ELF）、HEX、BIN 产物，按 `ELF > HEX > BIN` 排序。
- 若存在多个同样合理的工程文件或配置，列出候选而不是静默猜测。

## 执行步骤

1. 先阅读 [references/usage.md](references/usage.md)，确认本次是环境探测、工程扫描、列出配置，还是执行编译。
2. 若不确定环境是否就绪，先运行自带脚本 [scripts/iar_builder.py](scripts/iar_builder.py) 的 `--detect` 模式确认。
3. 若不确定工程文件位置，使用 `--scan` 搜索工作区。
4. 使用 `--list-configs --project X.ewp` 确认可用配置，再用 `--project` + `--config` 执行编译。
5. 读取脚本输出的构建结果和产物扫描报告，重点关注首选产物（.out/ELF > HEX > BIN）、错误/警告统计和失败分类。
6. 将构建配置、产物路径、芯片型号和工具链信息写回 `Project Profile`，并在需要时交给下游 skill。

## 失败分流

- 当 IAR 未安装或 iarbuild.exe 不可用时，返回 `environment-missing`。
- 当工程文件损坏、配置名无效或编译因配置问题失败时，返回 `project-config-error`。
- 当编译看似成功但未找到可烧录或可调试产物时，返回 `artifact-missing`。
- 当存在多个同样合理的工程文件或配置，且任意选择都不安全时，返回 `ambiguous-context`。

## 平台说明

- IAR Embedded Workbench 仅在 Windows 上原生运行，iarbuild.exe 命令行编译需要 Windows 环境。
- 自带脚本在非 Windows 平台上仍可执行工程解析（`--list-configs`）、工程扫描（`--scan`）和产物扫描（`--scan-artifacts`），但实际编译会被阻塞。
- 输出中的产物路径应保持为绝对路径，方便下游烧录和调试 skill 直接复用。

## 输出约定

- 输出编译命令、工程文件、配置名、芯片型号、工具链和首选产物路径。
- 输出错误和警告统计，以及关键编译日志证据。
- 用 `artifact_path`、`artifact_kind`、`target_mcu` 和 `toolchain` 更新 `Project Profile`。
- 成功后推荐 `flash-openocd` 或 `debug-gdb-openocd`。

## 交接关系

- 当下一步意图是给硬件烧录程序时，将成功构建结果交给 `flash-openocd`。
- 当下一步需要符号信息或调试会话时，将成功构建结果交给 `debug-gdb-openocd`。
