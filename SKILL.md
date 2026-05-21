---
name: embed-ai-tool
description: 嵌入式开发技能集的总控入口。负责两类任务：(1) 用户请求安装本仓库 skill 时，引导选择全部或按需安装；(2) 用户发出模糊指令（如"烧录"、"编译"、"调试"）且无法自动判断应使用哪个具体 skill 时，列出同分类下的候选 skill 供用户选择。
metadata:
  internal: true
---

# embed-ai-tool 总控

本技能负责两类交互：**安装引导** 和 **指令消歧**。

---

## 一、安装引导

当用户请求安装本仓库的 skill 时，按以下流程引导。不要跳过询问直接安装。

### 流程

1. 向用户展示下面的 **可用技能列表**
2. 询问用户选择安装方式：
   - **全部安装** — 安装所有 24 个 skill
   - **按需安装** — 用户指定要安装的 skill 名称
3. 根据用户选择执行对应的安装命令

### 可用技能

| 分类 | 技能 | 说明 |
|------|------|------|
| 构建 | `build-cmake` | 配置并构建基于 CMake 的 MCU 固件工程 |
| 构建 | `build-keil` | 配置并构建基于 Keil MDK 的固件工程 |
| 构建 | `build-iar` | 配置并构建基于 IAR EWARM 的固件工程 |
| 构建 | `build-platformio` | 配置并构建基于 PlatformIO 的固件工程 |
| 构建 | `build-idf` | 配置目标芯片并构建 ESP-IDF 固件工程 |
| 构建 | `build-makefile` | 配置并构建基于 Makefile 的固件工程 |
| 烧录 | `flash-keil` | 通过 Keil MDK 内置调试器烧录固件 |
| 烧录 | `flash-openocd` | 通过 OpenOCD 烧录 ELF/HEX/BIN 产物 |
| 烧录 | `flash-platformio` | 通过 PlatformIO 上传机制烧录固件 |
| 烧录 | `flash-idf` | 通过 ESP-IDF 工具链烧录固件并支持 JTAG 调试 |
| 烧录 | `flash-jlink` | 通过 SEGGER J-Link 烧录固件，支持 RTT 日志捕获 |
| 调试 | `debug-gdb-openocd` | 通过 OpenOCD 附着 GDB 调试 |
| 调试 | `debug-jlink` | 通过 J-Link GDB Server 在线调试和崩溃分析 |
| 调试 | `debug-platformio` | 通过 PlatformIO 内置 GDB 调试 |
| 调试 | `rtos-debug` | FreeRTOS/RT-Thread/Zephyr 线程感知调试 |
| 通信 | `serial-monitor` | 串口选择与运行日志抓取 |
| 通信 | `modbus-debug` | Modbus RTU/TCP 寄存器读写与从站扫描 |
| 通信 | `can-debug` | CAN 总线帧监听、发送和节点扫描 |
| 通信 | `visa-debug` | VISA 仪器 SCPI 通信、波形捕获和截图 |
| 分析 | `memory-analysis` | .map/ELF 内存使用报告与符号排名 |
| 分析 | `static-analysis` | cppcheck/clang-tidy 静态分析，MISRA-C 合规 |
| 开发 | `peripheral-driver` | 搜索并适配开源 BSP 外设驱动 |
| 开发 | `stm32-hal-development` | STM32 HAL 库开发指导与最佳实践 |
| 编排 | `workflow` | 串联编译+烧录+监控/调试的流水线 |

### 安装命令

优先使用 `npx skills`，若用户无 Node.js 环境改用 Python 脚本。

```bash
# npx 全部安装
npx skills add LeoKemp223/embed-ai-tool -g -y

# npx 按需安装
npx skills add LeoKemp223/embed-ai-tool --skill build-cmake --skill flash-openocd -g -y

# Python 全部安装
python3 /tmp/embed-ai-tool/scripts/install.py /path/to/project

# Python 按需安装
python3 /tmp/embed-ai-tool/scripts/install.py /path/to/project --skills build-cmake flash-openocd
```

---

## 二、指令消歧

当用户发出模糊指令（如"烧录"、"编译"、"调试"）时，先尝试自动探测工程类型；若无法明确判断，必须列出候选 skill 让用户选择，不要自行假设。

### 消歧流程

```
用户输入模糊指令
    │
    ▼
自动探测工程类型
    │
    ├─ 唯一匹配 → 直接调用对应 skill
    │
    └─ 匹配多个或无法判断 → 列出候选 skill 供用户选择
```

### 自动探测规则

按工作区文件特征判断工程类型，规则优先级从高到低：

| 文件特征 | 工程类型 | 对应 skill |
|----------|----------|-----------|
| `*.uvprojx` / `*.uvproj` | Keil MDK | `build-keil` `flash-keil` |
| `platformio.ini` | PlatformIO | `build-platformio` `flash-platformio` `debug-platformio` |
| `sdkconfig` + `components/` | ESP-IDF | `build-idf` `flash-idf` |
| `CMakeLists.txt` + `*.cmake` | CMake | `build-cmake` |
| `Makefile` / `makefile`（无 CMakeLists.txt） | Makefile | `build-makefile` |
| `.jlink` 文件或 JLinkExe 在 PATH | J-Link | `flash-jlink` `debug-jlink` |
| `.vscode/launch.json` 含 `openocd` | OpenOCD | `flash-openocd` `debug-gdb-openocd` |
| 以上均无 | 未知 | **必须询问用户** |

### 分类候选表

当自动探测无法唯一确定时，按用户指令所属分类展示候选 skill：

**编译 / 构建：**

| 技能 | 适用场景 |
|------|----------|
| `build-keil` | Keil MDK 工程（.uvprojx） |
| `build-cmake` | CMake 工程（CMakeLists.txt） |
| `build-iar` | IAR EWARM 工程（.ewp） |
| `build-platformio` | PlatformIO 工程（platformio.ini） |
| `build-idf` | ESP-IDF 工程（sdkconfig） |
| `build-makefile` | 裸 Makefile 工程 |

**烧录 / 下载：**

| 技能 | 适用场景 |
|------|----------|
| `flash-keil` | Keil 工程 + 内置调试器（ST-Link / J-Link / CMSIS-DAP） |
| `flash-openocd` | OpenOCD 兼容探针（ST-Link / CMSIS-DAP / DAPLink） |
| `flash-jlink` | SEGGER J-Link 探针 |
| `flash-platformio` | PlatformIO 上传（串口 / JTAG / DFU） |
| `flash-idf` | ESP-IDF 工具链（ESP32 系列串口烧录） |

**调试：**

| 技能 | 适用场景 |
|------|----------|
| `debug-gdb-openocd` | OpenOCD + GDB 调试 |
| `debug-jlink` | J-Link GDB Server 调试 |
| `debug-platformio` | PlatformIO 内置 GDB |
| `rtos-debug` | RTOS 线程感知调试（FreeRTOS / RT-Thread / Zephyr） |

**通信 / 监控：**

| 技能 | 适用场景 |
|------|----------|
| `serial-monitor` | 串口日志抓取 |
| `modbus-debug` | Modbus RTU/TCP 通信 |
| `can-debug` | CAN / CAN-FD 总线 |
| `visa-debug` | SCPI 仪器通信 |

### 示例交互

```
👤 烧录
🤖 当前工作区未检测到明确的烧录工具配置，请选择：
   1. flash-keil — Keil MDK 内置调试器烧录
   2. flash-openocd — OpenOCD 烧录（ST-Link / CMSIS-DAP）
   3. flash-jlink — SEGGER J-Link 烧录
   4. flash-platformio — PlatformIO 上传
   5. flash-idf — ESP-IDF 串口烧录
   请输入编号或 skill 名称：

👤 2
🤖 使用 flash-openocd，正在探测探针和固件产物...
```

---

## 安装后提示

安装完成后，告知用户：

- 已安装的 skill 列表
- 使用 `/skill-name` 调用具体 skill，例如 `/build-cmake`、`/serial-monitor`
- 用自然语言描述需求即可触发对应 skill，例如"编译烧录"、"看串口"
- 管理命令：`npx skills ls -g`（查看）、`npx skills update -g`（更新）、`npx skills remove -g`（移除）
