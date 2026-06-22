---
name: serial-shell
description: 当需要通过串口与嵌入式设备建立交互式 Shell 会话、执行单条命令或批量脚本时使用。
---

# 串口 Shell 交互

## 适用场景

- 用户需要登录嵌入式 Linux / RTOS 设备的串口 Shell，进行命令行交互。
- 用户需要通过串口向设备发送单条命令并捕获响应，供脚本或自动化流程使用。
- 用户有一组命令需要在设备上按顺序执行，希望从文件批量导入。
- 设备运行在 RS-485 半双工总线上，需要用 RTS 控制收发切换。
- 设备 Shell 使用非 UTF-8 编码，或需要 CR+LF 换行符才能正常解析命令。
- 烧录或复位已完成，下一步需要在设备端 Shell 中手动验证或配置。

## 必要输入

- 一个串口设备路径（Windows 下为 `COMn`，Linux 下为 `/dev/ttyUSBn` 或 `/dev/ttyACMn`）。
- 波特率（常见：115200、9600）。
- 若为单命令模式，需提供要执行的命令字符串。
- 若为批量模式，需提供命令脚本文件路径。
- 可选参数：编码、换行风格、RS-485 模式、超时时间、Shell 提示符正则、日志文件路径。

## 自动探测

- 串口优先级为：显式用户输入、`Project Profile` 中的 `serial_port`、脚本自动检测结果，否则阻塞并要求用户指定。
- 波特率优先级为：显式用户输入、`Project Profile` 中的 `baud_rate`、工作区文档或代码常量，最后回落到 `115200`。
- 编码默认为 `utf-8`；若设备回显出现乱码，优先尝试 `gbk`，其次 `latin-1`。
- 换行符默认为 `LF`；若命令发送后设备无响应，尝试 `--crlf`。
- 模式默认为交互式终端；只有在用户显式提供 `--cmd` 或 `--script` 时才切换为非交互模式。
- 若存在多个同样合理的串口候选，列出候选项并阻塞，不要静默猜测。

## 执行步骤

1. 确认 `pyserial` 已安装（`pip install pyserial`），若缺失则返回 `environment-missing` 并指导安装。
2. 运行自带脚本 [shell_proxy.py](shell_proxy.py)，根据用户意图选择模式：
   - **交互模式（默认）**：`python shell_proxy.py -p <端口> -b <波特率>`，进入交互式终端，按 `Ctrl+]` 退出。
   - **单命令模式**：`python shell_proxy.py -p <端口> -b <波特率> --cmd "<命令>"`，等待响应后自动退出。
   - **批量脚本模式**：`python shell_proxy.py -p <端口> -b <波特率> --script <脚本文件>`，逐条执行并打印每条的响应。
3. 若设备 Shell 需要先登录或进入特定目录，使用 `--init "<命令>"`（可重复多次），按顺序在连接后自动发送。
4. 若设备回显乱码，先用 `--encoding gbk` 尝试；若仍无法识别，用 `--hex` 查看原始字节辅助诊断。
5. 若设备使用 RS-485 半双工，启用 `--rs485`；若需捕获逐字符回显，进一步启用 `--rs485-byte`。
6. 若需要将输出保存到文件，使用 `--log <文件路径>`。
7. 读取脚本输出时，重点关注命令执行结果、错误信息和 Shell 提示符返回状态，而不是只转述原始文本。
8. 将确认有效的串口、波特率和编码写回 `Project Profile`。

## 失败分流

- 当缺少 `pyserial` 时，返回 `environment-missing`。
- 当指定串口无法打开（端口不存在、被其他程序占用、设备掉线）时，返回 `connection-failure`。
- 当宿主机没有权限访问串口设备时，返回 `permission-problem`。
- 当命令发送后超时无响应，且编码和换行符均已尝试仍未恢复时，返回 `target-response-abnormal`。
- 当存在多个合理串口候选，或工作区中隐含互相冲突的波特率时，返回 `ambiguous-context`。
- 当脚本文件不存在或无法解析时，返回 `project-config-error`。

## 平台说明

- 串口命名规则复用 [shared/platform-compatibility.md](../../shared/platform-compatibility.md)。
- 自带脚本使用 `pyserial`，跨 Linux、macOS、Windows 三种宿主平台。
- Windows 下端口名使用 `COMn` 格式，输出中保留完整端口名。
- Linux 下常见权限问题表现为 `PermissionError`，需检查用户组成员资格或 udev 规则。
- macOS 下优先关注 `/dev/cu.*` 端口，`/dev/tty.*` 作为次级候选。

## 输出约定

- 输出选中的串口、波特率、编码、执行模式，以及命令执行结果或交互会话的关键观察结论。
- 用 `serial_port`、`baud_rate` 更新 `Project Profile`。
- 若使用了 `--log`，记录日志文件路径。
- 若使用了 `--init`，记录初始化命令及其执行结果。
- 当命令输出表明目标固件发生崩溃、断言或异常复位时，推荐 `debug-gdb-openocd` 或 `debug-jlink`。

## 交接关系

- 当交互会话完成后，需要持续监视设备运行日志时，将结果交给 `serial-monitor`。
- 当 Shell 输出表明固件崩溃、需要断点或回溯分析时，将结果交给 `debug-gdb-openocd` 或 `debug-jlink`。
- 当串口 Shell 缺少所需工具，需要重新构建并烧录固件时，将结果交给对应的 `build-*` 和 `flash-*` 技能。
