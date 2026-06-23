---
name: embed-ai-tool
description: 嵌入式开发技能集的总控入口。负责两类任务：(1) 用户请求安装本仓库 skill 时，引导选择全部或按需安装；(2) 用户发出模糊指令（如"烧录"、"编译"、"调试"）且无法自动判断应使用哪个具体 skill 时，列出同分类下的候选 skill 供用户选择。
metadata:
  internal: true
---

# embed-ai-tool 总控

本技能负责两类交互：**安装引导** 和 **指令消歧**。

> **缓存复用提示**：所有 build/flash 脚本启动时会自动复用工程根目录 `.em_skill.json` 中上次成功的 profile 作为默认参数（显式参数优先，**无需 agent 先手动传 `--resume`**）；`--resume` 仅用于断言缓存必须存在，无缓存则非零退出。新会话直接运行目标动作（`--build` / `--flash` 等）即可，缓存命中时参数自动补全。

---

## 一、安装引导

当用户请求安装本仓库的 skill 时，按以下流程引导。**不要跳过询问直接安装**，也不要替用户决定安装内容——先分析工程，再让用户选。

### 流程

1. **分析工程** — 探测当前工作区的工程特征（构建系统、工具链、探针、协议线索等），详见"工程分析项"
2. **呈现分析结果** — 把探测到的事实客观列给用户，未识别出的也要明确说明
3. **提供选项** — 基于分析结果给出可选安装方案（推荐集 / 全部 / 按分类 / 自定义），让用户选择，详见"提供的安装选项"
4. **执行安装** — 根据用户选择执行对应命令；用户可在推荐集基础上增删，不必重走流程

### 工程分析项

按工作区文件特征推断工程画像，规则优先级从高到低：

| 类别 | 文件特征 | 推断结论 | 关联 skill |
|------|----------|----------|-----------|
| 构建系统 | `*.uvprojx` / `*.uvproj` | Keil MDK | `build-keil` `flash-keil` |
| 构建系统 | `*.ewp` / `*.eww` | IAR EWARM | `build-iar` |
| 构建系统 | `platformio.ini` | PlatformIO | `build-platformio` `flash-platformio` `debug-platformio` |
| 构建系统 | `sdkconfig` + `components/` | ESP-IDF | `build-idf` `flash-idf` |
| 构建系统 | `CMakeLists.txt` + `*.cmake` | CMake | `build-cmake` |
| 构建系统 | `Makefile`（无 CMakeLists.txt） | Makefile | `build-makefile` |
| 工具链 | PATH 含 `arm-none-eabi-gcc` | ARM Cortex-M 目标 | — |
| 工具链 | PATH 含 `xtensa-esp32-elf-gcc` | ESP32 (Xtensa) 目标 | — |
| 工具链 | PATH 含 `riscv64-unknown-elf-gcc` | RISC-V 目标 | — |
| 调试器 | `.vscode/launch.json` 含 `openocd` | OpenOCD | `flash-openocd` `debug-gdb-openocd` |
| 调试器 | `*.jlink` 文件或 JLinkExe 在 PATH | J-Link | `flash-jlink` `debug-jlink` |
| 调试器 | `openocd.cfg` / `openocd.cfg.in` 存在 | OpenOCD 配置 | `flash-openocd` `debug-gdb-openocd` |
| 协议 | 源码含 `#include "modbus.h"` 或 `mb.h` | 使用 Modbus | `modbus-debug` |
| 协议 | 源码含 CAN HAL 驱动引用 | 使用 CAN 总线 | `can-debug` |
| 协议 | `main.c` 引用 `stdio` / UART 重定向 | 使用串口日志 | `serial-monitor` |
| 协议 | 源码含 `viOpen` / `viWrite` | 使用 SCPI 仪器 | `visa-debug` |
| RTOS | 源码含 `FreeRTOS.h` / `rtthread.h` / `zephyr.h` | 使用 RTOS | `rtos-debug` |
| 内存 | 工程能产出 `.map` / `.elf` | 可做内存分析 | `memory-analysis` |

**探测失败时**：如果工作区特征不明显（纯裸 C 文件、混合工程、空目录），直接告知用户"未识别出明确工程类型"，建议选"全部安装"或"自定义"——不要硬推推荐集。

### 推荐集映射

按识别到的工程画像给出基础推荐集（用户可在其上增删）：

| 工程类型 | 基础推荐集 |
|---------|-----------|
| Keil MDK | `build-keil` `flash-keil` `serial-monitor` `debug-gdb-openocd` `workflow` |
| IAR EWARM | `build-iar` `flash-openocd` `serial-monitor` `workflow` |
| PlatformIO | `build-platformio` `flash-platformio` `debug-platformio` `serial-monitor` `workflow` |
| ESP-IDF | `build-idf` `flash-idf` `serial-monitor` `debug-gdb-openocd` `workflow` |
| CMake | `build-cmake` `flash-openocd` `debug-gdb-openocd` `serial-monitor` `workflow` |
| Makefile | `build-makefile` `flash-openocd` `serial-monitor` `workflow` |

基础集是起点，根据"工程分析项"探测到的协议线索继续追加：

- 检测到 RTOS → 追加 `rtos-debug`
- 检测到 Modbus → 追加 `modbus-debug`
- 检测到 CAN → 追加 `can-debug`
- 检测到 VISA / SCPI → 追加 `visa-debug`
- 工程能产 `.map` / `.elf` → 追加 `memory-analysis`

### 提供的安装选项

分析完成后，向用户呈现 4 个并列选项：

| 选项 | 说明 |
|------|------|
| **A. 推荐集** | 基于工程分析得出的最小集（通常 5-8 个），可在此基础上增删 |
| **B. 全部安装** | 安装全部 22 个 skill，适合全局工具人 / 教学场景 |
| **C. 按分类逐一勾选** | 按 6 个分类顺序逐一询问，每类下用户可全选、跳过或勾选部分（详见"分类逐一勾选流程"） |
| **D. 自定义** | 用户直接输入 skill 名或编号，自由组合 |

用户选 A 后仍可微调（如"再加个 modbus-debug"），不要重走一遍流程。

### 分类逐一勾选流程

用户选 C 后，按 6 个分类顺序逐一询问。每个分类独立交互，用户可全选、跳过或勾选部分。基于工程分析预先勾选推荐项，降低决策成本。

**分类顺序与内容：**

| 序号 | 分类 | 包含 skill（数量） | 默认勾选规则（基于工程分析） |
|------|------|------------------|---------------------------|
| 1 | 构建 | build-cmake / build-keil / build-iar / build-platformio / build-idf / build-makefile（6） | 勾选识别到的构建系统对应项，其余不勾 |
| 2 | 烧录 | flash-keil / flash-openocd / flash-platformio / flash-idf / flash-jlink（5） | 勾选识别到的探针 / 工具链对应项 |
| 3 | 调试 | debug-gdb-openocd / debug-jlink / debug-platformio / rtos-debug（4） | 勾选识别到的调试器对应项；检测到 RTOS 时勾 `rtos-debug` |
| 4 | 通信 | serial-monitor / modbus-debug / can-debug / visa-debug（4） | 默认勾 `serial-monitor`；按协议线索勾 `modbus` / `can` / `visa` |
| 5 | 分析 | memory-analysis / static-analysis（2） | 工程能产 `.map` / `.elf` 时勾 `memory-analysis` |
| 6 | 编排 | workflow（1） | 默认勾选 |

**单次分类询问格式：**

```
[2/6] 烧录（5 个 skill）：

   ✅ 1. flash-openocd    — OpenOCD 烧录（识别到 .vscode/launch.json）
   ☐  2. flash-keil       — Keil MDK 烧录
   ☐  3. flash-jlink      — SEGGER J-Link 烧录
   ☐  4. flash-platformio — PlatformIO 上传
   ☐  5. flash-idf        — ESP-IDF 串口烧录

   操作：回车确认默认 / 输入编号增删（如 +3 -1）/ "全选" / "跳过"

👤 +3

🤖 [3/6] 调试（4 个 skill）：
   ...
```

**完成所有分类后**：汇总最终选定的 skill 列表，让用户确认或微调，然后执行安装。

如果用户对某个分类无任何勾选且工程分析也没识别到，应主动确认"跳过 X 分类？"避免遗漏关键能力（比如构建和烧录通常必须）。

### 安装示例

```
👤 帮我安装 embed-ai-tool 的 skill

🤖 正在分析当前工程...

   检测到工程特征：
   • 构建系统：CMake（CMakeLists.txt）
   • 目标架构：ARM Cortex-M（PATH 含 arm-none-eabi-gcc）
   • 调试器配置：OpenOCD + ST-Link（.vscode/launch.json）
   • 协议线索：UART stdio 重定向（main.c）
   • RTOS：未检测到

   可选安装方案：

   A. 推荐集（6 个）— build-cmake / flash-openocd / debug-gdb-openocd / serial-monitor / memory-analysis / workflow
   B. 全部安装（22 个）
   C. 按分类逐一勾选（6 个分类顺序询问）
   D. 自定义（输入 skill 名或编号）

   请选择（A / B / C / D）：

👤 A，再加个 rtos-debug

🤖 安装：build-cmake / flash-openocd / debug-gdb-openocd / serial-monitor / memory-analysis / workflow / rtos-debug
   执行中...
```

### 可用技能列表

> 完整技能清单，用于"按分类选（C）"和"自定义（D）"时参考。推荐集（A）的子集由"工程分析项"和"推荐集映射"自动推导。

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
