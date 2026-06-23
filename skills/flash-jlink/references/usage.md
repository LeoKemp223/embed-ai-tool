# J-Link 烧录 Skill 用法

这个 skill 自带了一个可执行脚本 [scripts/jlink_flasher.py](../scripts/jlink_flasher.py)，适合在需要探测 J-Link 探针、执行烧录、启动 RTT 日志捕获时直接调用。

## 能力概览

- 检测 JLinkExe 是否可用并获取版本信息
- 列出已连接的 J-Link 设备
- 扫描工作区中的 `.jlink` 配置文件和 `.vscode/launch.json` 中的 J-Link 设置
- 生成 J-Link Commander 脚本并执行烧录
- 支持 ELF/HEX 直接烧录和 BIN 带地址烧录
- RTT 日志捕获（J-Link 独有功能）
- 输出结构化的烧录结果报告

## 基础用法

```bash
# 探测 J-Link 环境和已连接设备
python3 skills/flash-jlink/scripts/jlink_flasher.py --detect

# 扫描工作区中的 J-Link 配置线索
python3 skills/flash-jlink/scripts/jlink_flasher.py --scan-configs /path/to/project

# 烧录 ELF
python3 skills/flash-jlink/scripts/jlink_flasher.py \
  --artifact /path/to/firmware.elf \
  --device STM32F407VG

# 烧录 BIN（需要指定基地址）
python3 skills/flash-jlink/scripts/jlink_flasher.py \
  --artifact /path/to/firmware.bin \
  --device STM32F407VG \
  --base-address 0x08000000

# RTT 日志捕获
python3 skills/flash-jlink/scripts/jlink_flasher.py \
  --rtt --device STM32F407VG --rtt-duration 30
```

## 常见模式

### 0. 新会话恢复

```bash
python3 skills/flash-jlink/scripts/jlink_flasher.py --resume
```

成功烧录后缓存 artifact、device、interface、speed 和 BIN 基地址；脚本启动即自动复用这些缓存参数（显式参数优先）；无缓存或缓存失效时自动回退，例如 探测或重新指定设备。


### 1. 环境探测

```bash
python3 skills/flash-jlink/scripts/jlink_flasher.py --detect
```

输出 JLinkExe 版本和已连接的 J-Link 设备列表。

### 2. SWD 模式烧录（默认）

```bash
python3 skills/flash-jlink/scripts/jlink_flasher.py \
  --artifact build/debug/app.elf \
  --device STM32F407VG
```

### 3. JTAG 模式烧录

```bash
python3 skills/flash-jlink/scripts/jlink_flasher.py \
  --artifact build/debug/app.elf \
  --device STM32F407VG \
  --interface JTAG
```

### 4. 自定义烧录速度

```bash
python3 skills/flash-jlink/scripts/jlink_flasher.py \
  --artifact build/debug/app.hex \
  --device nRF52840_xxAA \
  --speed 8000
```

### 5. RTT 实时日志

```bash
python3 skills/flash-jlink/scripts/jlink_flasher.py \
  --rtt --device STM32F407VG --rtt-duration 60
```

RTT 是 J-Link 独有功能，通过调试口传输日志，不占用 UART，速度比串口快数十倍。

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `--detect` | 探测 J-Link 环境和已连接设备 |
| `--artifact` | 固件产物路径（ELF、HEX 或 BIN） |
| `--device` | 目标芯片型号（如 STM32F407VG），J-Link 必需 |
| `--interface` | 调试接口：`SWD`（默认）或 `JTAG` |
| `--speed` | 烧录速度 kHz（默认 4000） |
| `--base-address` | BIN 文件的烧录基地址（十六进制） |
| `--scan-configs` | 扫描指定目录中的 J-Link 配置线索 |
| `--rtt` | 启动 RTT 日志捕获 |
| `--rtt-duration` | RTT 捕获时长（秒，默认 10） |
| `--save-config` | 探测成功后保存工具路径到配置 |
| `--resume` | 从工程根目录 `.em_skill.json` 的缓存 profile 恢复上次成功参数 |
| `--profile` | 指定缓存 profile 名，默认 `default` |
| `--workspace` | 指定工程根目录，profile 固定读写该目录下的 `.em_skill.json` |
| `--show-profile` | 输出当前缓存 profile 并退出 |
| `--clear-profile` | 删除当前缓存 profile 并退出 |
| `--no-save-profile` | 成功后不更新缓存 profile |
| `-v`, `--verbose` | 输出详细日志 |

## JLinkExe 查找顺序

1. 配置文件（`get_tool_path("jlink")`）
2. `JLinkExe`（Linux/macOS PATH）或 `JLink.exe`（Windows PATH）
3. `/opt/SEGGER/JLink/JLinkExe`（Linux/macOS）
4. `C:\Program Files\SEGGER\JLink\JLink.exe`（Windows）

## J-Link 与 OpenOCD 对比

| 特性 | J-Link (本 skill) | OpenOCD (flash-openocd) |
|------|-------------------|------------------------|
| RTT 日志 | ✅ 原生支持 | ❌ 不支持 |
| SWO 输出 | ✅ 原生支持 | ⚠️ 部分支持 |
| 烧录速度 | 更快（直接通信） | 较慢 |
| 芯片支持 | 广泛（需许可） | 广泛（开源） |
| 商业许可 | 需要（教育版免费） | 开源免费 |

## 返回码

- `0`：操作成功
- `1`：参数非法、依赖缺失、探针连接失败、烧录失败
