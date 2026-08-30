---
name: rtos-debug
description: 当需要进行 FreeRTOS/RT-Thread/Zephyr 的线程感知调试，查看任务列表、栈水位或死锁检测时使用。
---

# RTOS 调试

## 适用场景

- 固件运行了 RTOS（FreeRTOS、RT-Thread 或 Zephyr），需要查看任务状态。
- 怀疑任务栈溢出导致 HardFault 或异常行为。
- 需要检测死锁（所有任务都处于等待状态）。
- 需要查看队列、信号量等内核对象状态。
- 需要自动识别固件使用的 RTOS 类型。

## 必要输入

- 带符号的 `ELF` 文件路径。
- 已运行的 GDB Server（OpenOCD 或 JLinkGDBServer），通过 `--port` 指定 GDB 端口。
- 可选显式指定 RTOS 类型（`--rtos freertos|rt-thread|zephyr`）。

## 自动探测

- 通过 ELF 符号表自动判断 RTOS 类型：`vTaskStartScheduler` → FreeRTOS，`rt_thread_init` → RT-Thread，`k_thread_create` → Zephyr。
- 不依赖 OpenOCD 的 RTOS awareness 功能，改用 GDB 直接读取 RTOS 内核数据结构。
- FreeRTOS 提供完整支持（任务列表、栈水位、队列）。
- Zephyr 支持任务列表、内核对象状态（msgq/sem/mutex/queue/fifo/lifo）和死锁检测，需固件启用 `CONFIG_THREAD_MONITOR=y`（线程名需 `CONFIG_THREAD_NAME=y`）。对象发现优先使用 `CONFIG_TRACING_OBJECT_TRACKING` 追踪链表，未启用时回退到静态段符号 `_k_*_list_start/_end`（仅覆盖静态定义的对象）。
- RT-Thread 仅提供基本任务列表支持。

## 执行步骤

1. 先阅读 [references/usage.md](references/usage.md) 和 [references/rtos-patterns.md](references/rtos-patterns.md)，了解常见 RTOS 问题模式。
2. 确保 GDB Server（OpenOCD 或 JLinkGDBServer）已在运行。
3. 若不确定 RTOS 类型，先运行 [scripts/rtos_debugger.py](scripts/rtos_debugger.py) 的 `--detect` 模式。
4. 使用 `--tasks` 查看任务列表和状态。
5. 使用 `--stack-check` 检查各任务栈水位。
6. 使用 `--deadlock` 检查死锁特征（Zephyr 会检测 mutex 等待环，如 `A -> B -> A`）。
7. 使用 `--queues` 查看队列和信号量状态（Zephyr 支持 msgq/sem/mutex/queue/fifo/lifo，含持有者与等待者）。

## 失败分流

- 当缺少 GDB 时，返回 `environment-missing`。
- 当没有可用的 `ELF` 时，返回 `artifact-missing`。
- 当 GDB 无法连接到 GDB Server 时，返回 `connection-failure`。
- 当 ELF 中未检测到 RTOS 符号时，返回 `project-config-error`。
- 当 GDB 可以连接但无法读取 RTOS 数据结构时，返回 `target-response-abnormal`。
- 当无法确定 RTOS 类型时，返回 `ambiguous-context`。

## 平台说明

- 自带脚本使用 Python 标准库和 subprocess 调用 GDB，跨平台兼容。
- GDB Server 需要由用户或上游 skill（`debug-gdb-openocd` 或 `debug-jlink`）预先启动。
- RTOS 数据结构读取依赖 ELF 符号信息，Release 优化可能导致部分符号被优化掉。

## 输出约定

- 输出检测到的 RTOS 类型和版本（如果可获取）。
- 输出任务列表，包含任务名、状态、优先级和栈使用信息。
- 栈水位低于安全阈值时输出告警。
- 死锁检测结果以明确的是/否形式输出。
- 在 `Project Profile` 中更新 `rtos` 字段。

## 交接关系

- 当确认栈溢出时，建议使用 `memory-analysis` 分析固件内存布局。
- 当需要更深入的单步调试时，交给 `debug-gdb-openocd` 或 `debug-jlink`。
