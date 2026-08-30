# RTOS 调试 Skill 用法

这个 skill 自带了一个可执行脚本 [scripts/rtos_debugger.py](../scripts/rtos_debugger.py)，适合在需要进行 RTOS 线程感知调试时直接调用。

## 能力概览

- 通过 ELF 符号自动检测 RTOS 类型（FreeRTOS、RT-Thread、Zephyr）
- 通过 GDB batch 模式读取任务列表和状态
- 检查各任务栈水位
- 死锁检测（FreeRTOS：全任务等待启发式；Zephyr：mutex 等待环检测）
- 队列/信号量状态查看（FreeRTOS 队列注册表；Zephyr 内核对象追踪）

## 前置条件

- GDB Server 必须已在运行（OpenOCD 或 JLinkGDBServer）
- 带符号的 ELF 文件
- arm-zephyr-eabi-gdb、arm-none-eabi-gdb 或 gdb-multiarch

### Zephyr 固件要求

- `CONFIG_THREAD_MONITOR=y`（读取线程链表 `_kernel.threads` 的必需配置）
- `CONFIG_THREAD_NAME=y`（推荐，否则线程名退化为 ELF 符号推断）
- 对象追踪（可选）：启用 `CONFIG_TRACING_OBJECT_TRACKING=y` 后可通过追踪链表发现动态创建的对象；未启用时脚本回退到静态段符号 `_k_*_list_start/_end`，只能发现 `K_MSGQ_DEFINE`/`K_SEM_DEFINE` 等静态定义的对象

## 基础用法

```bash
# 探测 RTOS 类型和工具
python3 skills/rtos-debug/scripts/rtos_debugger.py --detect --elf build/app.elf

# 读取任务列表（需要 GDB Server 已运行）
python3 skills/rtos-debug/scripts/rtos_debugger.py \
  --tasks --elf build/app.elf --port 3333

# 检查栈水位
python3 skills/rtos-debug/scripts/rtos_debugger.py \
  --stack-check --elf build/app.elf --port 3333

# 死锁检测
python3 skills/rtos-debug/scripts/rtos_debugger.py \
  --deadlock --elf build/app.elf --port 3333

# 查看队列状态
python3 skills/rtos-debug/scripts/rtos_debugger.py \
  --queues --elf build/app.elf --port 3333
```

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `--detect` | 检测 RTOS 类型和调试工具 |
| `--tasks` | 读取任务列表 |
| `--stack-check` | 检查各任务栈水位 |
| `--deadlock` | 检测死锁 |
| `--queues` | 列出队列/信号量状态 |
| `--elf` | ELF 文件路径 |
| `--rtos` | 显式指定 RTOS 类型 |
| `--gdb` | GDB 可执行文件路径 |
| `--port` | GDB 服务端口（默认 3333） |
| `-v`, `--verbose` | 详细输出 |

## RTOS 支持级别

| RTOS | 任务列表 | 栈水位 | 死锁检测 | 队列/对象状态 |
|------|---------|--------|---------|---------|
| FreeRTOS | ✅ 完整 | ✅ 完整 | ✅ 基本 | ✅ 基本 |
| Zephyr | ✅ 完整 | ❌ 暂不支持 | ✅ mutex 等待环 | ✅ msgq/sem/mutex/queue/fifo/lifo |
| RT-Thread | ⚠️ 基本 | ⚠️ 基本 | ❌ | ❌ |

### Zephyr 支持细节

- **任务列表**：遍历 `_kernel.threads` 链表（`next_thread` 串联），读取线程名、
  `base.thread_state`、`base.prio`、`base.pended_on`。全部通过 GDB 按字段名
  读取，不依赖结构体偏移，对 `SCHED_*`/`WAITQ_*` Kconfig 变体不敏感。
- **内核对象**：支持 `k_msgq`/`k_sem`/`k_mutex`/`k_queue`/`k_fifo`/`k_lifo`。
  显示 sem 计数/上限、msgq 已用/容量/消息大小、mutex 持有者与锁计数，
  并通过线程的 `pended_on` 与对象 `wait_q` 地址匹配自动列出等待者。
- **死锁检测**：构建 mutex 等待者→持有者图做环检测（报出形如
  `deadlockB -> deadlockA -> deadlockB` 的等待环）；辅助启发式为
  "无就绪线程且任务数 > 1"。

## 典型工作流

```bash
# 1. 启动 OpenOCD（或 JLinkGDBServer）
openocd -f interface/stlink.cfg -f target/stm32f4x.cfg &

# 2. 检测 RTOS 类型
python3 skills/rtos-debug/scripts/rtos_debugger.py --detect --elf build/app.elf

# 3. 查看任务状态
python3 skills/rtos-debug/scripts/rtos_debugger.py --tasks --elf build/app.elf

# 4. 检查栈水位
python3 skills/rtos-debug/scripts/rtos_debugger.py --stack-check --elf build/app.elf
```

## 返回码

- `0`：操作成功
- `1`：参数非法、依赖缺失、连接失败、读取失败
