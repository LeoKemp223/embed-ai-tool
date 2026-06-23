---
name: build-platformio
description: 当需要通过 PlatformIO 命令行编译嵌入式工程，调用自带脚本解析环境配置、执行构建并定位固件产物时使用。
---

# 构建 PlatformIO 工程

## 适用场景

- `Project Profile` 中标明 `build_system: platformio` 或工作区中存在 `platformio.ini`。
- 用户希望对 PlatformIO 工程执行编译、清理或上传固件。
- 烧录或调试流程需要新的 `ELF`、`HEX` 或 `BIN`。
- 需要在构建前确认 PlatformIO CLI 是否就绪。

## 必要输入

- 工作区路径（包含 `platformio.ini`），或一份已有的 `Project Profile`。
- 可选的环境名称（environment）。

## 自动探测

- 脚本启动即自动复用工程根目录 `.em_skill.json` 中上次成功的 profile 作为默认参数（显式参数优先，无需先手动传 `--resume`）；`--resume` 仅用于断言缓存必须存在，无缓存则非零退出。无缓存或用户明确要求重新探测时，脚本自动回退到正常扫描。
- 脚本自动检测 `pio` 命令是否可用并获取版本。
- 解析 `platformio.ini` 中的环境列表，提取 platform、board、framework 和上传协议。
- 识别 `[platformio]` section 中的 `default_envs` 作为默认环境。
- 若未指定环境且存在默认环境，使用默认环境；否则使用第一个环境。
- 在 `.pio/build/<env>/` 中搜索 firmware.elf/hex/bin 产物，按 `ELF > HEX > BIN` 排序。
- 若存在多个同样合理的环境，列出候选而不是静默猜测。

## 执行步骤

1. 先阅读 [references/usage.md](references/usage.md)，确认本次是环境探测、列出环境、执行构建，还是仅扫描产物。
2. 若不确定环境是否就绪，先运行自带脚本 [scripts/platformio_builder.py](scripts/platformio_builder.py) 的 `--detect` 模式确认。
3. 使用 `--list-envs --project-dir <dir>` 确认可用环境，再用 `--project-dir` + `--env` 执行构建。
4. 读取脚本输出的构建结果和产物扫描报告，重点关注首选产物（ELF > HEX > BIN）和失败分类。
5. 将构建环境、产物路径和板卡信息写回 `Project Profile`，并在需要时交给下游 skill。

## 失败分流

- 当 `pio` 命令不可用时，返回 `environment-missing`。
- 当 `platformio.ini` 不存在或环境名无效时，返回 `project-config-error`。
- 当构建看似成功但未找到可烧录或可调试产物时，返回 `artifact-missing`。
- 当存在多个同样合理的环境，且任意选择都不安全时，返回 `ambiguous-context`。

## 平台说明

- PlatformIO 完全跨平台（Linux / macOS / Windows），无平台限制。
- 自带脚本使用 Python 标准库和 subprocess 调用 `pio`，构建调度路径本身是跨平台的。
- 输出中的构建目录和产物路径应保持为绝对路径，方便下游烧录和调试 skill 直接复用。

## 输出约定

- 输出构建命令、工程目录、环境名、板卡和首选产物路径。
- 用 `artifact_path`、`artifact_kind` 和板卡信息更新 `Project Profile`。
- 成功后推荐 `flash-openocd` 或 `debug-gdb-openocd`。

## 交接关系

- 当下一步意图是给硬件烧录程序时，将成功构建结果交给 `flash-openocd`。
- 当下一步需要符号信息或调试会话时，将成功构建结果交给 `debug-gdb-openocd`。
- PlatformIO 自带上传功能（`--upload`），简单场景可直接使用而无需交接。
