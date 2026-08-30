#!/usr/bin/env python3
"""RTOS 调试工具。

为 `rtos-debug` skill 提供可重复调用的执行入口，支持：

- 通过 ELF 符号自动检测 RTOS 类型
- 通过 GDB batch 模式读取任务列表
- 检查各任务栈水位
- 死锁检测（FreeRTOS / Zephyr）
- 队列/信号量/互斥锁状态查看（FreeRTOS / Zephyr）
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _SCRIPT_DIR.parent.parent
for _candidate in [_SKILLS_DIR / "shared", _SKILLS_DIR.parent / "shared"]:
    if (_candidate / "tool_config.py").exists():
        sys.path.insert(0, str(_candidate))
        break
from tool_config import get_tool_path


RTOS_SIGNATURES = {
    "freertos": ["vTaskStartScheduler", "xTaskCreate", "pxCurrentTCB"],
    "rt-thread": ["rt_thread_init", "rt_thread_create", "rt_current_thread"],
    "zephyr": ["k_thread_create", "k_thread_start", "_kernel"],
}

GDB_CANDIDATES = [
    "arm-zephyr-eabi-gdb", "arm-none-eabi-gdb", "gdb-multiarch",
]
# nm/readelf 候选前缀（NCS v2.6+ 使用 arm-zephyr-eabi 前缀）
GNU_PREFIXES = ["arm-zephyr-eabi", "arm-none-eabi", ""]
DEFAULT_GDB_PORT = 3333

FREERTOS_TASK_STATES = {
    0: "Running",
    1: "Ready",
    2: "Blocked",
    3: "Suspended",
    4: "Deleted",
}

# Zephyr thread_state 位定义（include/zephyr/kernel_structs.h）。
ZEPHYR_THREAD_STATE_DUMMY = 1 << 0
ZEPHYR_THREAD_STATE_PENDING = 1 << 1
ZEPHYR_THREAD_STATE_PRESTART = 1 << 2
ZEPHYR_THREAD_STATE_DEAD = 1 << 3
ZEPHYR_THREAD_STATE_SUSPENDED = 1 << 4
ZEPHYR_THREAD_STATE_QUEUED = 1 << 7

# Zephyr 可读取的内核对象类型。
# cast:   对象强转类型
# link:   追踪链表遍历用的 next 成员路径（k_fifo/k_lifo 内嵌 k_queue，
#         路径多一层 _queue）
# wqpath: wait_q 成员路径（线程 pended_on 与该地址匹配以确定等待者）
ZEPHYR_OBJ_TYPES = {
    "msgq":  {"cast": "struct k_msgq",  "link": "obj_core.node.next",        "wqpath": "wait_q"},
    "sem":   {"cast": "struct k_sem",   "link": "obj_core.node.next",        "wqpath": "wait_q"},
    "mutex": {"cast": "struct k_mutex", "link": "obj_core.node.next",        "wqpath": "wait_q"},
    "queue": {"cast": "struct k_queue", "link": "obj_core.node.next",        "wqpath": "wait_q"},
    "fifo":  {"cast": "struct k_fifo",  "link": "_queue.obj_core.node.next", "wqpath": "_queue.wait_q"},
    "lifo":  {"cast": "struct k_lifo",  "link": "_queue.obj_core.node.next", "wqpath": "_queue.wait_q"},
}

# Zephyr 追踪链表头符号（CONFIG_TRACING_OBJECT_TRACKING）。
ZEPHYR_TRACK_HEADS = {
    "msgq": "_track_list_k_msgq",
    "sem": "_track_list_k_sem",
    "mutex": "_track_list_k_mutex",
    "queue": "_track_list_k_queue",
    "fifo": "_track_list_k_fifo",
    "lifo": "_track_list_k_lifo",
}

# Zephyr 静态对象 section 符号（K_MSGQ_DEFINE 等宏把对象本身放入
# _k_*_list_start..end 之间的连续内存）。
ZEPHYR_SECTION_SYMS = {
    "msgq": ("_k_msgq_list_start", "_k_msgq_list_end"),
    "sem": ("_k_sem_list_start", "_k_sem_list_end"),
    "mutex": ("_k_mutex_list_start", "_k_mutex_list_end"),
    "queue": ("_k_queue_list_start", "_k_queue_list_end"),
    "fifo": ("_k_fifo_list_start", "_k_fifo_list_end"),
    "lifo": ("_k_lifo_list_start", "_k_lifo_list_end"),
}

MAX_ZEPHYR_THREADS = 64
MAX_TRACK_DEPTH = 32
GDB_BATCH_TIMEOUT = 60


@dataclass
class TaskInfo:
    name: str
    state: str
    priority: int
    stack_high_water: int = -1
    stack_base: int = 0
    stack_size: int = 0
    address: int = 0    # Zephyr: k_thread 地址
    pending_on: int = 0  # Zephyr: pended_on（等待对象 wait_q 地址），0 = 未等待


@dataclass
class KernelObjectInfo:
    name: str
    obj_type: str  # msgq / sem / mutex / queue / fifo / lifo
    address: int = 0
    wait_q_addr: int = 0
    count: int = -1          # sem: 当前计数; mutex: lock_count; msgq: used_msgs
    limit: int = -1          # sem: limit; msgq: max_msgs
    msg_size: int = -1       # msgq: msg_size
    owner: str = ""          # mutex: 持有线程名
    owner_addr: int = 0      # mutex: 持有线程 TCB 地址
    waiters: list[str] = field(default_factory=list)  # 等待线程名


@dataclass
class RTOSResult:
    status: str
    summary: str
    rtos_type: str | None = None
    tasks: list[TaskInfo] = field(default_factory=list)
    objects: list[KernelObjectInfo] = field(default_factory=list)
    deadlock_detected: bool = False
    observations: list[str] = field(default_factory=list)
    failure_category: str | None = None
    evidence: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# RTOS 类型检测
# ---------------------------------------------------------------------------

def _find_gnu_tool(name: str) -> str | None:
    """按候选前缀查找 binutils 工具（nm/readelf）。"""
    for prefix in GNU_PREFIXES:
        tool = shutil.which(f"{prefix}-{name}" if prefix else name)
        if tool:
            return tool
    return None


def detect_rtos_from_elf(elf_path: str) -> str | None:
    nm_tool = _find_gnu_tool("nm")
    if not nm_tool:
        readelf = _find_gnu_tool("readelf")
        if not readelf:
            return None
        try:
            result = subprocess.run(
                [readelf, "-s", elf_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            output = result.stdout
        except Exception:
            return None
    else:
        try:
            result = subprocess.run(
                [nm_tool, elf_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            output = result.stdout
        except Exception:
            return None

    for rtos_type, symbols in RTOS_SIGNATURES.items():
        for sym in symbols:
            if sym in output:
                return rtos_type
    return None


# ---------------------------------------------------------------------------
# ELF 符号工具（地址 ↔ 变量名映射）
# ---------------------------------------------------------------------------

def read_elf_symbols(elf_path: str) -> dict[str, int]:
    """读取 ELF 符号表中的全局符号地址映射。

    返回 {变量名: 地址}。用于把 GDB 读到的内核对象地址映射回源码变量名。
    nm 不可用或失败时回退到 readelf -sW。
    """
    output = ""
    nm_tool = _find_gnu_tool("nm")
    if nm_tool:
        try:
            result = subprocess.run(
                [nm_tool, elf_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            )
            output = result.stdout or ""
        except Exception:
            output = ""
    if not output:
        readelf = _find_gnu_tool("readelf")
        if not readelf:
            return {}
        try:
            result = subprocess.run(
                [readelf, "-sW", elf_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            )
            # readelf -sW 列格式: Num: Value Size Type Bind Vis Ndx Name
            for line in (result.stdout or "").splitlines():
                parts = line.split()
                if len(parts) < 8:
                    continue
                try:
                    int(parts[1], 16)
                except ValueError:
                    continue
                output += f"{parts[1]} {parts[3]} {parts[7]}\n"
        except Exception:
            return {}

    symbols: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) < 3:
            continue
        addr_str, _sym_type, name = parts
        try:
            addr = int(addr_str, 16)
        except ValueError:
            continue
        if name and addr != 0:
            symbols[name] = addr
    return symbols


def find_symbol_by_address(symbols: dict[str, int], address: int) -> str:
    """按地址反查符号名，找不到时返回十六进制地址字符串。

    多个符号同地址时（如相邻 _k_* 静态段的边界符号与段内首对象重叠），
    优先返回非边界符号，避免把对象命名成 _k_sem_list_start/_end。
    """
    if not address:
        return "?"
    candidates = [name for name, addr in symbols.items() if addr == address]
    if not candidates:
        return f"0x{address:08X}"
    for name in candidates:
        if name.startswith("_k_") and name.endswith(("_list_start", "_list_end")):
            continue
        return name
    return candidates[0]


# ---------------------------------------------------------------------------
# GDB 工具
# ---------------------------------------------------------------------------

def find_gdb(explicit: str | None) -> str | None:
    if explicit:
        path = shutil.which(explicit) or explicit
        return path if Path(path).exists() else None

    for name in ("arm-zephyr-eabi-gdb", "arm-none-eabi-gdb"):
        configured = get_tool_path(name)
        if configured:
            path = shutil.which(configured) or configured
            if Path(path).exists():
                return path

    for candidate in GDB_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def run_gdb_commands(
    gdb_path: str,
    elf_path: str,
    gdb_port: int,
    commands: list[str],
    timeout: int = GDB_BATCH_TIMEOUT,
) -> tuple[bool, str]:
    elf_posix = elf_path.replace("\\", "/")
    lines = [
        f"file {elf_posix}",
        f"target extended-remote localhost:{gdb_port}",
    ] + commands + ["quit"]

    script = "\n".join(lines) + "\n"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".gdb", delete=False, encoding="utf-8",
    ) as f:
        f.write(script)
        script_path = f.name

    try:
        result = subprocess.run(
            [gdb_path, "--batch", "-x", script_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "GDB 执行超时"
    except FileNotFoundError:
        return False, f"未找到 GDB: {gdb_path}"
    finally:
        Path(script_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# FreeRTOS 任务读取
# ---------------------------------------------------------------------------

def read_freertos_tasks(
    gdb_path: str, elf_path: str, gdb_port: int,
) -> tuple[list[TaskInfo], list[str]]:
    commands = [
        "monitor halt",
        "set print pretty on",
        "set pagination off",
        # 读取当前任务
        "print pxCurrentTCB",
        "print pxCurrentTCB->pcTaskName",
        "print pxCurrentTCB->uxPriority",
        # 遍历就绪列表
        "print pxReadyTasksLists",
        # 遍历延迟列表
        "print xDelayedTaskList1",
        "print xDelayedTaskList2",
        # 遍历挂起列表
        "print xSuspendedTaskList",
        # 任务总数
        "print uxCurrentNumberOfTasks",
    ]

    ok, output = run_gdb_commands(gdb_path, elf_path, gdb_port, commands)
    tasks: list[TaskInfo] = []
    observations: list[str] = []

    if not ok:
        observations.append(f"GDB 读取 FreeRTOS 数据失败")
        return tasks, observations

    # 解析当前任务
    current_name_match = re.search(r'pcTaskName\s*=\s*"(\w+)"', output)
    current_pri_match = re.search(r'uxPriority\s*=\s*(\d+)', output)
    if current_name_match:
        tasks.append(TaskInfo(
            name=current_name_match.group(1),
            state="Running",
            priority=int(current_pri_match.group(1)) if current_pri_match else 0,
        ))

    # 解析任务数量
    num_tasks_match = re.search(r'uxCurrentNumberOfTasks\s*=\s*(\d+)', output)
    if num_tasks_match:
        observations.append(f"FreeRTOS 任务总数: {num_tasks_match.group(1)}")

    # 解析更多任务名
    task_names = re.findall(r'pcTaskName\s*=\s*"(\w+)"', output)
    known = {t.name for t in tasks}
    for name in task_names:
        if name not in known:
            tasks.append(TaskInfo(name=name, state="Unknown", priority=0))
            known.add(name)

    return tasks, observations


def check_freertos_stack(
    gdb_path: str, elf_path: str, gdb_port: int,
) -> tuple[list[str], list[str]]:
    commands = [
        "monitor halt",
        "set pagination off",
        "print pxCurrentTCB->pxStack",
        "print pxCurrentTCB->pxTopOfStack",
        "print pxCurrentTCB->pcTaskName",
    ]

    ok, output = run_gdb_commands(gdb_path, elf_path, gdb_port, commands)
    observations: list[str] = []
    warnings: list[str] = []

    if not ok:
        observations.append("GDB 读取栈信息失败")
        return observations, warnings

    stack_base_match = re.search(r'pxStack\s*=\s*\(.*?\)\s*(0x[0-9a-fA-F]+)', output)
    stack_top_match = re.search(r'pxTopOfStack\s*=\s*\(.*?\)\s*(0x[0-9a-fA-F]+)', output)
    task_name_match = re.search(r'pcTaskName\s*=\s*"(\w+)"', output)

    if stack_base_match and stack_top_match:
        base = int(stack_base_match.group(1), 16)
        top = int(stack_top_match.group(1), 16)
        used = abs(top - base)
        name = task_name_match.group(1) if task_name_match else "当前任务"
        observations.append(f"任务 '{name}' 栈使用: 0x{base:08X} - 0x{top:08X} ({used} bytes)")
        if used < 64:
            warnings.append(f"⚠️ 任务 '{name}' 栈余量极低（{used} bytes），存在溢出风险！")

    return observations, warnings


# ---------------------------------------------------------------------------
# Zephyr 线程读取
# ---------------------------------------------------------------------------

def read_zephyr_tasks(
    gdb_path: str, elf_path: str, gdb_port: int,
    elf_syms: dict[str, int] | None = None,
) -> tuple[list[TaskInfo], list[str]]:
    """通过 _kernel.threads 链表（CONFIG_THREAD_MONITOR）读取线程列表。

    线程经 next_thread 串联（与 k_thread_foreach 一致）。状态取
    base.thread_state，等待对象取 base.pended_on。全部通过 GDB 表达式
    按字段名读取，不依赖结构体偏移，对 SCHED_*/WAITQ_* 配置不敏感。
    """
    observations: list[str] = []
    if elf_syms is None:
        elf_syms = read_elf_symbols(elf_path)

    # 第一步：探测内核结构成员是否存在（不同 Kconfig / 版本有差异）。
    probe = [
        "monitor halt",
        "set pagination off",
        'printf "P_THREADS=%d\\n", _kernel.threads != 0',
        'printf "P_NAME=%d\\n", _kernel.cpus[0].current->name != 0',
        'printf "P_PEND=%d\\n", _kernel.cpus[0].current->base.pended_on != 0',
        'printf "CURRENT=%p\\n", _kernel.cpus[0].current',
    ]
    ok, output = run_gdb_commands(gdb_path, elf_path, gdb_port, probe)
    has_threads = "P_THREADS=1" in output or "P_THREADS=0" in output
    if not ok or not has_threads:
        # GDB batch 连接失败时 returncode 可能为 0，需检查输出内容；
        # 错误文本可能是 GBK 乱码，匹配 ASCII 的 "could not connect"
        if ("could not connect" in output.lower()
                or "connection" in output.lower()
                or "localhost" in output.lower()):
            observations.append(
                f"无法连接 GDB Server localhost:{gdb_port}（请确认 "
                "OpenOCD/JLinkGDBServer 已运行）"
            )
        else:
            observations.append(
                "无法访问 _kernel.threads（需要 CONFIG_THREAD_MONITOR=y）"
            )
        return [], observations

    has_name = "P_NAME=" in output
    has_pend = "P_PEND=" in output
    cur_m = re.search(r'CURRENT=(0x[0-9a-fA-F]+)', output)
    current_addr = int(cur_m.group(1), 16) if cur_m else 0
    if not has_name:
        observations.append("未启用 CONFIG_THREAD_NAME，线程名由 ELF 符号推断")

    # 第二步：单次 GDB 会话内循环遍历链表。
    kthread = "(struct k_thread *)$t"
    name_expr = (
        f'{kthread}->name != 0 ? {kthread}->name : "(unnamed)"'
        if has_name else None
    )
    if has_name:
        row_fmt = 'printf "T=%p|name=%s|state=0x%x|prio=%d|pend=%p\\n", '
        row_fmt += f"(void *)$t, {name_expr}, "
    else:
        row_fmt = 'printf "T=%p|state=0x%x|prio=%d|pend=%p\\n", (void *)$t, '
    row_fmt += (
        f"(unsigned){kthread}->base.thread_state, "
        f"(int){kthread}->base.prio, "
        + (f"(void *){kthread}->base.pended_on" if has_pend else "0")
    )

    walk = [
        "set pagination off",
        "set $t = _kernel.threads",
        "set $i = 0",
        f"while ($t != 0 && $i < {MAX_ZEPHYR_THREADS})",
        row_fmt,
        f"  set $t = {kthread}->next_thread",
        "  set $i = $i + 1",
        "end",
    ]
    ok2, out2 = run_gdb_commands(gdb_path, elf_path, gdb_port, walk)
    # GDB 的 %p 对空指针输出 "(nil)"，统一归一化为 0x0 以便解析
    out2 = out2.replace("(nil)", "0x0")
    if not ok2 and "T=0x" not in out2:
        observations.append("GDB 遍历线程链表失败")
        return [], observations

    tasks: list[TaskInfo] = []
    if has_name:
        # 线程名可含空格（如 "BT LW WQ"），用非 | 匹配而非 \S+
        pattern = (
            r'T=(0x[0-9a-fA-F]+)\|name=([^|]+)\|state=(0x[0-9a-fA-F]+)'
            r'\|prio=(-?\d+)\|pend=(0x[0-9a-fA-F]+)'
        )
        for m in re.finditer(pattern, out2):
            addr = int(m.group(1), 16)
            name = m.group(2)
            state_bits = int(m.group(3), 16)
            prio = int(m.group(4))
            pended = int(m.group(5), 16)
            tasks.append((addr, name, state_bits, prio, pended))
    else:
        pattern = (
            r'T=(0x[0-9a-fA-F]+)\|state=(0x[0-9a-fA-F]+)'
            r'\|prio=(-?\d+)\|pend=(0x[0-9a-fA-F]+)'
        )
        for m in re.finditer(pattern, out2):
            addr = int(m.group(1), 16)
            name = find_symbol_by_address(elf_syms, addr)
            state_bits = int(m.group(2), 16)
            prio = int(m.group(3), 16)
            pended = int(m.group(4), 16)
            tasks.append((addr, name, state_bits, prio, pended))

    result: list[TaskInfo] = []
    for addr, name, state_bits, prio, pended in tasks:
        if state_bits & ZEPHYR_THREAD_STATE_DEAD:
            state = "Dead"
        elif (state_bits & ZEPHYR_THREAD_STATE_SUSPENDED) and (state_bits & ZEPHYR_THREAD_STATE_PENDING):
            state = "Pending+Susp"
        elif state_bits & ZEPHYR_THREAD_STATE_PENDING:
            state = "Pending"
        elif state_bits & ZEPHYR_THREAD_STATE_SUSPENDED:
            state = "Suspended"
        elif addr == current_addr:
            state = "Running"
        else:
            state = "Ready"
        result.append(TaskInfo(
            name=name, state=state, priority=prio,
            address=addr, pending_on=pended if has_pend else 0,
        ))

    if not result:
        observations.append("线程链表为空或解析失败")
    return result, observations


# ---------------------------------------------------------------------------
# Zephyr 内核对象读取（队列 / 信号量 / 互斥锁等）
# ---------------------------------------------------------------------------

def _zephyr_gather_object_addrs(
    gdb_path: str, elf_path: str, gdb_port: int, tag: str,
    cast: str, link: str, elf_syms: dict[str, int],
) -> tuple[list[int], list[str]]:
    """收集某类型内核对象实例地址。

    通道 1: CONFIG_TRACING_OBJECT_TRACKING 追踪链表 _track_list_*，
            对象经 obj_core.node 串联（含动态创建的对象）。
    通道 2: 静态 section 符号 _k_*_list_start/_end（K_MSGQ_DEFINE 等宏
            生成的连续对象区）。
    返回 (地址列表, 观察记录)。
    """
    notes: list[str] = []
    head_sym = ZEPHYR_TRACK_HEADS[tag]
    addrs: list[int] = []

    if head_sym in elf_syms:
        cmds = [
            "set pagination off",
            f"set $o = {head_sym}",
            "set $i = 0",
            f"while ($o != 0 && $i < {MAX_TRACK_DEPTH})",
            '  printf "OBJ=%p\\n", (void *)$o',
            f"  set $o = (({cast} *)$o)->{link}",
            "  set $i = $i + 1",
            "end",
        ]
        ok, out = run_gdb_commands(gdb_path, elf_path, gdb_port, cmds)
        out = out.replace("(nil)", "0x0")
        if ok:
            for m in re.finditer(r'OBJ=(0x[0-9a-fA-F]+)', out):
                a = int(m.group(1), 16)
                if a:
                    addrs.append(a)
        if addrs:
            notes.append(f"{tag}: 经追踪链表 {head_sym} 发现 {len(addrs)} 个对象")
        else:
            notes.append(f"{tag}: 追踪链表为空")

    if not addrs:
        start_sym, end_sym = ZEPHYR_SECTION_SYMS[tag]
        if start_sym in elf_syms and end_sym in elf_syms:
            start, end = elf_syms[start_sym], elf_syms[end_sym]
            if end > start:
                sz_ok, sz_out = run_gdb_commands(
                    gdb_path, elf_path, gdb_port,
                    [f'printf "SZ=%d\\n", sizeof({cast})'],
                )
                obj_size = 0
                if sz_ok:
                    m = re.search(r'SZ=(\d+)', sz_out)
                    if m:
                        obj_size = int(m.group(1))
                if obj_size > 0:
                    count = (end - start) // obj_size
                    addrs = [start + i * obj_size for i in range(count)]
                    notes.append(
                        f"{tag}: 经静态段 {start_sym}..{end_sym} 发现 {count} 个对象"
                    )
    return addrs, notes


def read_zephyr_objects(
    gdb_path: str, elf_path: str, gdb_port: int,
    tasks: list[TaskInfo], elf_syms: dict[str, int],
) -> tuple[list[KernelObjectInfo], list[str]]:
    """读取 Zephyr 内核对象状态，并把 pended_on 匹配等待线程。"""
    observations: list[str] = []
    objects: list[KernelObjectInfo] = []

    # pending 线程 → wait_q 地址索引
    pend_map: dict[int, list[str]] = {}
    for t in tasks:
        if t.pending_on:
            pend_map.setdefault(t.pending_on, []).append(t.name)

    for tag, spec in ZEPHYR_OBJ_TYPES.items():
        cast, wqpath = spec["cast"], spec["wqpath"]
        addrs, notes = _zephyr_gather_object_addrs(
            gdb_path, elf_path, gdb_port, tag, cast, spec["link"], elf_syms,
        )
        observations.extend(notes)
        if not addrs:
            continue

        # 按类型批量读取：一条 GDB 会话读取该类型全部对象
        cmds = ["set pagination off"]
        for addr in addrs:
            o = f"(({cast} *){addr:#x})"
            wq = f"&({o}->{wqpath})"
            if tag == "msgq":
                fmt = (f'printf "OBJ@{addr:#x}|MSGQ USED=%d MAX=%d MSGSZ=%d|WQ=%p\\n", '
                       f"(int)({o}->used_msgs), (int)({o}->max_msgs), "
                       f"(int)({o}->msg_size), (void *){wq}")
            elif tag == "sem":
                # count/limit 为 uint32_t，limit 可能是 UINT_MAX（无限），
                # 用无符号读取避免 (int) 强转把 UINT_MAX 打成 -1
                fmt = (f'printf "OBJ@{addr:#x}|SEM USED=%u MAX=%u|WQ=%p\\n", '
                       f"(unsigned int)({o}->count), (unsigned int)({o}->limit), "
                       f"(void *){wq}")
            elif tag == "mutex":
                fmt = (f'printf "OBJ@{addr:#x}|MUTEX LK=%d OWNER=%p|WQ=%p\\n", '
                       f"(int)({o}->lock_count), (void *)({o}->owner), (void *){wq}")
            else:
                fmt = f'printf "OBJ@{addr:#x}|WQ=%p\\n", (void *){wq}'
            cmds.append(fmt)
        ok, out = run_gdb_commands(gdb_path, elf_path, gdb_port, cmds)
        out = out.replace("(nil)", "0x0")
        if not ok and "OBJ@" not in out:
            observations.append(f"{tag}: GDB 读取对象状态失败")
            continue

        # GDB printf 的 \n 输出为真实换行，按行匹配（不可匹配字面 "\\n"）
        for line_m in re.finditer(r'OBJ@(0x[0-9a-fA-F]+)\|([^\n]*)', out):
            addr = int(line_m.group(1), 16)
            payload = line_m.group(2)
            wq_m = re.search(r'WQ=(0x[0-9a-fA-F]+)', payload)
            wait_q_addr = int(wq_m.group(1), 16) if wq_m else 0

            info = KernelObjectInfo(
                name=find_symbol_by_address(elf_syms, addr),
                obj_type=tag,
                address=addr,
                wait_q_addr=wait_q_addr,
                waiters=pend_map.get(wait_q_addr, []),
            )
            if tag == "msgq":
                m = re.search(r'MSGQ USED=(\d+) MAX=(\d+) MSGSZ=(\d+)', payload)
                if m:
                    info.count, info.limit, info.msg_size = (
                        int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    )
            elif tag == "sem":
                m = re.search(r'SEM USED=(\d+) MAX=(\d+)', payload)
                if m:
                    info.count, info.limit = int(m.group(1)), int(m.group(2))
            elif tag == "mutex":
                m = re.search(r'MUTEX LK=(\d+) OWNER=(0x[0-9a-fA-F]+)', payload)
                if m:
                    info.count = int(m.group(1))
                    info.owner_addr = int(m.group(2), 16)
                    owner_task = next(
                        (t for t in tasks if t.address == info.owner_addr), None,
                    )
                    if owner_task:
                        info.owner = owner_task.name
                    elif info.owner_addr:
                        info.owner = find_symbol_by_address(elf_syms, info.owner_addr)
            objects.append(info)
    return objects, observations


# ---------------------------------------------------------------------------
# 死锁检测
# ---------------------------------------------------------------------------

def check_deadlock(
    gdb_path: str, elf_path: str, gdb_port: int, rtos_type: str,
) -> tuple[bool, list[str]]:
    if rtos_type != "freertos":
        return False, ["死锁检测目前仅支持 FreeRTOS"]

    commands = [
        "monitor halt",
        "set pagination off",
        "print pxCurrentTCB->pcTaskName",
        "print pxReadyTasksLists",
        "print uxCurrentNumberOfTasks",
    ]

    ok, output = run_gdb_commands(gdb_path, elf_path, gdb_port, commands)
    observations: list[str] = []

    if not ok:
        return False, ["GDB 读取失败，无法检测死锁"]

    num_match = re.search(r'uxCurrentNumberOfTasks\s*=\s*(\d+)', output)
    total_tasks = int(num_match.group(1)) if num_match else 0

    ready_items = len(re.findall(r'uxNumberOfItems\s*=\s*([1-9]\d*)', output))
    observations.append(f"总任务数: {total_tasks}, 就绪列表非空项: {ready_items}")

    if total_tasks > 1 and ready_items == 0:
        observations.append("⚠️ 所有任务均不在就绪状态，可能存在死锁！")
        return True, observations

    return False, observations


def check_zephyr_deadlock(
    gdb_path: str, elf_path: str, gdb_port: int,
) -> tuple[bool, list[str]]:
    """Zephyr 死锁检测。

    强证据: mutex 等待环 —— 线程 A 永久等待的 mutex 由线程 B 持有，
    且链上互为等待形成环。
    启发式: 无任何 Ready 线程（就绪队列为空）且线程数 > 1，
    与 FreeRTOS 检测逻辑对齐。
    """
    observations: list[str] = []
    elf_syms = read_elf_symbols(elf_path)
    tasks, task_notes = read_zephyr_tasks(gdb_path, elf_path, gdb_port, elf_syms)
    observations.extend(task_notes)
    if not tasks:
        return False, observations

    name_by_addr = {t.address: t.name for t in tasks}

    # 1) mutex 等待环检测：等待者 → 持有者建图找环
    objects, obj_notes = read_zephyr_objects(gdb_path, elf_path, gdb_port, tasks, elf_syms)
    observations.extend(obj_notes)

    addr_by_name = {t.name: t.address for t in tasks}
    graph: dict[int, int] = {}
    for o in objects:
        if o.obj_type == "mutex" and o.owner_addr:
            for w in o.waiters:
                w_addr = addr_by_name.get(w)
                if w_addr and w_addr != o.owner_addr:
                    graph[w_addr] = o.owner_addr

    deadlock = False
    for start in list(graph):
        cycle = [start]
        cur = graph.get(start)
        steps = 0
        while cur and steps <= len(tasks):
            if cur == start:
                names = [name_by_addr.get(a, f"0x{a:08X}") for a in cycle]
                observations.append(
                    "⚠️ 检测到 mutex 等待环: " + " -> ".join(names + [names[0]])
                )
                deadlock = True
                break
            cycle.append(cur)
            cur = graph.get(cur)
            steps += 1
        if deadlock:
            break

    # 2) 启发式: 无 Ready 线程 + 线程数 > 1（与 FreeRTOS 检测对齐）
    if not deadlock:
        has_ready = any(t.state in ("Ready", "Running") for t in tasks)
        if not has_ready and len(tasks) > 1:
            pending = [t.name for t in tasks if t.state.startswith("Pending")]
            observations.append("⚠️ 所有线程均未就绪（就绪队列为空），可能存在死锁！")
            if pending:
                observations.append(f"等待内核对象的线程: {', '.join(pending)}")
            deadlock = True
        else:
            pend_only = [t.name for t in tasks if t.state.startswith("Pending")]
            if pend_only:
                observations.append(
                    f"ℹ️ Pending 线程（等待内核对象）: {', '.join(pend_only)}"
                )

    return deadlock, observations


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------

def print_detect_report(elf_path: str | None, rtos_type: str | None, gdb_path: str | None) -> None:
    print("\n📊 RTOS 调试环境探测结果：")

    if gdb_path:
        print(f"  ✅ GDB: {gdb_path}")
    else:
        print("  ❌ GDB: 未找到 arm-none-eabi-gdb 或 gdb-multiarch")

    nm = _find_gnu_tool("nm")
    print(f"  {'✅' if nm else '❌'} nm: {nm or '未找到'}")

    if rtos_type:
        print(f"\n  ✅ 检测到 RTOS: {rtos_type}")
    elif elf_path:
        print("\n  ⚠️ ELF 中未检测到已知 RTOS 符号")
    else:
        print("\n  ℹ️ 未提供 ELF 文件，跳过 RTOS 检测")


def print_rtos_report(result: RTOSResult) -> None:
    icon = {"success": "✅", "failure": "❌", "blocked": "⚠️"}.get(result.status, "❓")
    print(f"\n📊 RTOS 调试结果: {icon} {result.summary}")

    if result.rtos_type:
        print(f"\n  RTOS 类型: {result.rtos_type}")

    if result.tasks:
        print(f"\n  任务列表（共 {len(result.tasks)} 个）:")
        print(f"    {'任务名':<20} {'状态':<14} {'优先级':<8}")
        print(f"    {'─'*20} {'─'*14} {'─'*8}")
        for t in result.tasks:
            print(f"    {t.name:<20} {t.state:<14} {t.priority:<8}")

    if result.objects:
        print(f"\n  内核对象（共 {len(result.objects)} 个）:")
        for o in result.objects:
            parts = [f"[{o.obj_type}] {o.name}"]
            if o.obj_type == "msgq":
                parts.append(f"used={o.count}/{o.limit} msg_size={o.msg_size}")
            elif o.obj_type == "sem":
                parts.append(f"count={o.count}/{o.limit}")
            elif o.obj_type == "mutex":
                lock_desc = f"locked({o.count}) by {o.owner}" if o.count > 0 else "unlocked"
                parts.append(lock_desc)
            if o.waiters:
                parts.append(f"等待者: {', '.join(o.waiters)}")
            print(f"    {' | '.join(parts)}")

    if result.deadlock_detected:
        print("\n  ⚠️ 检测到潜在死锁！")

    if result.observations:
        print(f"\n🔍 观察（共 {len(result.observations)} 条）:")
        for obs in result.observations:
            print(f"  {obs}")

    if result.evidence:
        print("\n📝 证据:")
        for line in result.evidence[:15]:
            print(f"  {line}")

    if result.failure_category:
        print(f"\n  失败分类: {result.failure_category}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RTOS 调试工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --detect --elf build/app.elf
  %(prog)s --tasks --elf build/app.elf --port 3333
  %(prog)s --stack-check --elf build/app.elf --port 3333
  %(prog)s --deadlock --elf build/app.elf --port 3333
  %(prog)s --queues --elf build/app.elf --port 3333 --rtos zephyr
        """,
    )
    parser.add_argument("--detect", action="store_true", help="检测 RTOS 类型和调试工具")
    parser.add_argument("--tasks", action="store_true", help="读取任务列表")
    parser.add_argument("--stack-check", action="store_true", help="检查各任务栈水位")
    parser.add_argument("--deadlock", action="store_true", help="检测死锁")
    parser.add_argument("--queues", action="store_true", help="列出队列/信号量状态")
    parser.add_argument("--elf", help="ELF 文件路径")
    parser.add_argument("--rtos", choices=["freertos", "rt-thread", "zephyr"], help="显式指定 RTOS 类型")
    parser.add_argument("--gdb", help="GDB 可执行文件路径")
    parser.add_argument("--port", type=int, default=DEFAULT_GDB_PORT, help="GDB 服务端口（默认 3333）")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    return parser


def _run_zephyr_tasks(gdb_path: str, elf_path: str, port: int) -> RTOSResult:
    tasks, observations = read_zephyr_tasks(gdb_path, elf_path, port)
    return RTOSResult(
        status="success" if tasks else "failure",
        summary=f"读取到 {len(tasks)} 个线程" if tasks else "线程读取失败",
        rtos_type="zephyr",
        tasks=tasks,
        observations=observations,
        failure_category="target-response-abnormal" if not tasks else None,
    )


def _run_zephyr_queues(gdb_path: str, elf_path: str, port: int) -> RTOSResult:
    elf_syms = read_elf_symbols(elf_path)
    tasks, task_notes = read_zephyr_tasks(gdb_path, elf_path, port, elf_syms)
    objects, observations = read_zephyr_objects(gdb_path, elf_path, port, tasks, elf_syms)
    observations = task_notes + observations
    return RTOSResult(
        status="success" if objects else "failure",
        summary=f"找到 {len(objects)} 个内核对象" if objects else "未发现内核对象",
        rtos_type="zephyr",
        tasks=tasks,
        objects=objects,
        observations=observations,
        failure_category="target-response-abnormal" if not objects else None,
    )


def _run_zephyr_deadlock(gdb_path: str, elf_path: str, port: int) -> RTOSResult:
    detected, observations = check_zephyr_deadlock(gdb_path, elf_path, port)
    return RTOSResult(
        status="success",
        summary="检测到潜在死锁" if detected else "未检测到死锁",
        rtos_type="zephyr",
        deadlock_detected=detected,
        observations=observations,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    gdb_path = find_gdb(args.gdb)
    rtos_type = args.rtos

    # 探测模式
    if args.detect:
        if args.elf and Path(args.elf).is_file() and not rtos_type:
            rtos_type = detect_rtos_from_elf(args.elf)
        print_detect_report(args.elf, rtos_type, gdb_path)
        return 0

    # 以下模式需要 ELF 和 GDB
    if not args.elf:
        print("❌ 请提供 --elf（ELF 文件路径）。")
        return 1

    elf_path = str(Path(args.elf).resolve())
    if not Path(elf_path).exists():
        print(f"❌ ELF 文件不存在: {elf_path}")
        return 1

    if not gdb_path:
        print("❌ 未找到兼容的 GDB（需要 arm-none-eabi-gdb 或 gdb-multiarch）。")
        return 1

    if not rtos_type:
        rtos_type = detect_rtos_from_elf(elf_path)
    if not rtos_type:
        print("❌ 未检测到 RTOS 类型，请使用 --rtos 显式指定。")
        result = RTOSResult(
            status="blocked",
            summary="无法确定 RTOS 类型",
            failure_category="ambiguous-context",
        )
        print_rtos_report(result)
        return 1

    print(f"ℹ️ RTOS: {rtos_type}, GDB: {gdb_path}, 端口: {args.port}")

    # 任务列表
    if args.tasks:
        if rtos_type == "freertos":
            tasks, observations = read_freertos_tasks(gdb_path, elf_path, args.port)
            result = RTOSResult(
                status="success" if tasks else "failure",
                summary=f"读取到 {len(tasks)} 个任务" if tasks else "任务读取失败",
                rtos_type=rtos_type,
                tasks=tasks,
                observations=observations,
                failure_category="target-response-abnormal" if not tasks else None,
            )
        elif rtos_type == "zephyr":
            result = _run_zephyr_tasks(gdb_path, elf_path, args.port)
        else:
            result = RTOSResult(
                status="blocked",
                summary=f"{rtos_type} 任务列表读取为基本支持级别",
                rtos_type=rtos_type,
                observations=[f"{rtos_type} 任务列表读取为基本支持级别"],
            )
        print_rtos_report(result)
        return 0 if result.status == "success" else 1

    # 栈检查
    if args.stack_check:
        if rtos_type == "freertos":
            observations, warnings = check_freertos_stack(gdb_path, elf_path, args.port)
            observations = observations + warnings
        else:
            observations = [f"{rtos_type} 栈检查为基本支持级别"]

        result = RTOSResult(
            status="success",
            summary="栈水位检查完成",
            rtos_type=rtos_type,
            observations=observations,
        )
        print_rtos_report(result)
        return 0

    # 死锁检测
    if args.deadlock:
        if rtos_type == "freertos":
            detected, observations = check_deadlock(gdb_path, elf_path, args.port, rtos_type)
            result = RTOSResult(
                status="success",
                summary="检测到潜在死锁" if detected else "未检测到死锁",
                rtos_type=rtos_type,
                deadlock_detected=detected,
                observations=observations,
            )
        elif rtos_type == "zephyr":
            result = _run_zephyr_deadlock(gdb_path, elf_path, args.port)
        else:
            result = RTOSResult(
                status="blocked",
                summary=f"{rtos_type} 死锁检测暂不支持",
                rtos_type=rtos_type,
                observations=[f"{rtos_type} 死锁检测暂不支持"],
            )
        print_rtos_report(result)
        return 0

    # 队列状态
    if args.queues:
        if rtos_type == "freertos":
            commands = [
                "monitor halt",
                "set pagination off",
                "print xQueueRegistry",
            ]
            ok, output = run_gdb_commands(gdb_path, elf_path, args.port, commands)
            observations = []
            if ok:
                queue_names = re.findall(r'pcQueueName\s*=\s*"(\w+)"', output)
                for qn in queue_names:
                    observations.append(f"队列: {qn}")
            result = RTOSResult(
                status="success" if ok else "failure",
                summary=f"找到 {len(observations)} 个已注册队列" if ok else "队列读取失败",
                rtos_type=rtos_type,
                observations=observations,
                failure_category="target-response-abnormal" if not ok else None,
            )
        elif rtos_type == "zephyr":
            result = _run_zephyr_queues(gdb_path, elf_path, args.port)
        else:
            result = RTOSResult(
                status="blocked",
                summary=f"{rtos_type} 队列查看暂不支持",
                rtos_type=rtos_type,
                observations=[f"{rtos_type} 队列查看暂不支持"],
            )
        print_rtos_report(result)
        return 0 if result.status == "success" else 1

    print("❌ 请提供 --tasks、--stack-check、--deadlock 或 --queues 参数。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
