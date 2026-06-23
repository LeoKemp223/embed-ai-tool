---
name: flash-jlink
description: 当需要使用 SEGGER J-Link 探针烧录固件，或启动 RTT 日志捕获时使用。
---

# J-Link 烧录

## 适用场景

- 工作区已有可用固件产物，且目标板连接了 SEGGER J-Link 探针。
- 需要使用 J-Link Commander 进行烧录和校验，而非 OpenOCD。
- 需要利用 J-Link RTT（Real-Time Transfer）进行高速日志捕获。
- 需要扫描工作区中的 `.jlink` 配置文件或 `.vscode/launch.json` 中的 J-Link 设置。

## 必要输入

- 固件产物路径，或包含 `artifact_path` 的 `Project Profile`。
- `--device` 参数指定目标芯片型号（如 `STM32F407VG`），J-Link Commander 要求必须指定。
- 可选的接口类型（SWD 或 JTAG，默认 SWD）和烧录速度。
- 若产物为 BIN，还需要 `--base-address` 烧录基地址。

## 自动探测

- 脚本启动即自动复用工程根目录 `.em_skill.json` 中上次成功的 profile 作为默认参数（显式参数优先，无需先手动传 `--resume`）；`--resume` 仅用于断言缓存必须存在，无缓存则非零退出。无缓存或用户明确要求重新探测时，脚本自动回退到正常扫描。
- 按 `ELF > HEX > BIN` 选择固件产物。
- 脚本自动查找 JLinkExe，按配置文件、PATH、常见安装路径的顺序搜索。
- `--scan-configs` 扫描工作区 `.jlink` 文件和 `.vscode/launch.json` 中的 J-Link 配置。
- 不会猜测设备名；当 `--device` 缺失时阻塞并返回 `ambiguous-context`。

## 执行步骤

1. 先阅读 [references/usage.md](references/usage.md)，确认本次是环境探测、配置扫描，还是执行烧录。
2. 若不确定 J-Link 环境状态，先运行自带脚本 [scripts/jlink_flasher.py](scripts/jlink_flasher.py) 的 `--detect` 模式确认。
3. 若不确定设备型号或接口配置，使用 `--scan-configs` 扫描工作区线索。
4. 使用 `--artifact` + `--device` 执行烧录，可选 `--interface` 和 `--speed`。
5. 对 BIN 文件，必须同时提供 `--base-address`。
6. 需要 RTT 日志时，使用 `--rtt` 启动 RTT 捕获。
7. 读取脚本输出的烧录结果报告，重点关注校验状态和失败分类。

## 失败分流

- 当 `JLinkExe` 不可用时，返回 `environment-missing`。
- 当无法安全解析到产物，或 `BIN` 缺少烧录基地址时，返回 `artifact-missing`。
- 当 J-Link 无法发现探针或目标时，返回 `connection-failure`。
- 当配置文件无效或设备名不被 J-Link 识别时，返回 `project-config-error`。
- 当烧录开始但校验或复位失败时，返回 `target-response-abnormal`。
- 当 `--device` 缺失且无法从工作区推断时，返回 `ambiguous-context`。

## 平台说明

- JLinkExe 在 Linux/macOS 下为 `JLinkExe`，Windows 下为 `JLink.exe`。
- SEGGER 默认安装路径：Linux `/opt/SEGGER/JLink/`，Windows `C:\Program Files\SEGGER\JLink\`。
- 自带脚本使用 Python 标准库和 subprocess 调用 JLinkExe，跨平台兼容。
- RTT 功能为 J-Link 独有，不占用 UART，适合无串口场景。

## 输出约定

- 输出 JLinkExe 命令、设备名、接口类型、产物路径和校验结果。
- 在 `Project Profile` 中保留或更新 `artifact_path`、`artifact_kind`、`jlink_device`、`jlink_interface`。
- 烧录成功后推荐 `serial-monitor` 或 `debug-jlink`。

## 交接关系

- 当下一步要看运行日志时，将成功烧录结果交给 `serial-monitor`。
- 当用户需要 GDB 调试时，将结果交给 `debug-jlink`。
- 当需要 RTT 日志替代串口时，可直接使用本 skill 的 `--rtt` 模式。
