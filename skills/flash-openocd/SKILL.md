---
name: flash-openocd
description: 当需要使用已探测或显式指定的产物与探针配置，调用自带脚本通过 OpenOCD 烧录嵌入式固件时使用。
---

# OpenOCD 烧录

## 适用场景

- 工作区已经具备可用固件产物，且用户希望给硬件烧录程序。
- 已探测或用户指定的探针与 OpenOCD 兼容。
- 团队需要一条标准化的 OpenOCD 烧录流程，并可顺畅交接到串口观察或调试。
- 需要在烧录前确认探针连接状态或扫描工作区中的 OpenOCD 配置线索。

## 必要输入

- 固件产物路径，或包含 `artifact_path` 的 `Project Profile`。
- OpenOCD 配置信息：显式接口 + 目标配置、板级配置、现有 profile 数据，或工作区中的配置线索。
- 可选的复位行为和校验偏好。默认开启校验和复位。
- 若产物为 BIN，还需要烧录基地址。

## 自动探测

- 脚本启动即自动复用工程根目录 `.em_skill.json` 中上次成功的 profile 作为默认参数（显式参数优先，无需先手动传 `--resume`）；`--resume` 仅用于断言缓存必须存在，无缓存则非零退出。无缓存或用户明确要求重新探测时，脚本自动回退到正常扫描。
- 按 `ELF > HEX > BIN` 选择固件产物。
- 脚本可自动探测已连接的调试探针（ST-Link、CMSIS-DAP、J-Link），优先使用探测到的第一个。
- 配置优先级依次为：显式用户输入、现有 `Project Profile`、`--scan-configs` 扫描到的工作区线索。
- 若产物为 `BIN`，必须从工作区或用户输入中获得明确的烧录基地址，否则脚本会阻塞。
- 不要拼接多个"部分匹配"的配置；这种情况应返回 `ambiguous-context`。

## 执行步骤

1. 先阅读 [references/usage.md](references/usage.md)，确认本次是环境探测、配置扫描，还是执行烧录。
2. 若不确定探针状态，先运行自带脚本 [scripts/openocd_flasher.py](scripts/openocd_flasher.py) 的 `--detect` 模式确认。
3. 若不确定 OpenOCD 配置，使用 `--scan-configs` 扫描工作区线索。
4. 使用 `--artifact` 指定产物，配合 `--interface` + `--target` 或 `--config` 执行烧录。
5. 对 BIN 文件，必须同时提供 `--base-address`。
6. 读取脚本输出的烧录结果报告，重点关注校验状态和失败分类。
7. 将烧录配置和结果写回 `Project Profile`，并在需要时交给下游 skill。

## 失败分流

- 当 `openocd` 不可用时，返回 `environment-missing`。
- 当无法安全解析到产物，或 `BIN` 缺少烧录基地址时，返回 `artifact-missing`。
- 当 OpenOCD 无法发现探针或目标板时，返回 `connection-failure`。
- 当所选配置文件无效时，返回 `project-config-error`。
- 当烧录开始了，但校验、停核或复位失败时，返回 `target-response-abnormal`。
- 当存在多个同样合理的配置集合或目标时，返回 `ambiguous-context`。

## 平台说明

- 探针访问失败在所有宿主平台上都可能表现为 USB 或驱动问题，只是具体报错文本会随操作系统不同而变化。
- 自带脚本使用 Python 标准库和 subprocess 调用 openocd，因此烧录调度路径本身是跨平台的。
- 输出中应保留完整 OpenOCD 配置列表，方便在其他宿主环境中复现同一会话。

## 输出约定

- 输出 OpenOCD 命令、所选配置文件、产物路径，以及是否要求校验和复位。
- 在 `Project Profile` 中保留或更新 `artifact_path`、`artifact_kind`、`openocd_config`。
- 根据用户意图推荐下一步 skill：做启动验证后推荐 `serial-monitor`，需要调试时推荐 `debug-gdb-openocd`。

## 交接关系

- 当下一步要看运行日志时，将成功烧录结果交给 `serial-monitor`。
- 当用户需要断点、停核控制或崩溃分析时，将成功或部分成功的烧录结果交给 `debug-gdb-openocd`。