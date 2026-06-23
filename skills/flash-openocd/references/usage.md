# OpenOCD 烧录 Skill 用法

这个 skill 自带了一个可执行脚本 [scripts/openocd_flasher.py](../scripts/openocd_flasher.py)，适合在需要探测探针、组装 OpenOCD 配置、执行烧录与校验时直接调用。

## 能力概览

- 检测 OpenOCD 是否可用并获取版本信息
- 自动探测已连接的调试探针（ST-Link、CMSIS-DAP、J-Link）
- 扫描工作区中的 OpenOCD 配置文件线索
- 验证固件产物存在性和类型
- 组装并执行完整的 OpenOCD 烧录命令
- 支持 ELF/HEX 直接烧录和 BIN 带地址烧录
- 可选校验和复位控制
- 输出结构化的烧录结果报告

## 基础用法

```bash
# 探测 OpenOCD 环境和已连接探针
python3 skills/flash-openocd/scripts/openocd_flasher.py --detect

# 扫描工作区中的 OpenOCD 配置线索
python3 skills/flash-openocd/scripts/openocd_flasher.py --scan-configs /path/to/project

# 烧录 ELF（自动探测探针）
python3 skills/flash-openocd/scripts/openocd_flasher.py \
  --artifact /path/to/firmware.elf \
  --target target/stm32f4x.cfg

# 烧录 BIN（需要指定基地址）
python3 skills/flash-openocd/scripts/openocd_flasher.py \
  --artifact /path/to/firmware.bin \
  --target target/stm32f4x.cfg \
  --base-address 0x08000000
```

## 常见模式

### 0. 新会话恢复

```bash
python3 skills/flash-openocd/scripts/openocd_flasher.py --resume
```

成功烧录后缓存 artifact、interface、target/config、BIN 基地址和自定义命令；脚本启动即自动复用这些缓存参数（显式参数优先）；无缓存或缓存失效时自动回退，例如 探测探针或扫描配置。


### 1. 环境与探针探测

```bash
python3 skills/flash-openocd/scripts/openocd_flasher.py --detect
```

输出 OpenOCD 版本和已连接的调试探针列表。

### 2. 使用接口 + 目标配置烧录

```bash
python3 skills/flash-openocd/scripts/openocd_flasher.py \
  --artifact build/debug/app.elf \
  --interface stlink \
  --target target/stm32f4x.cfg
```

### 3. 使用板级配置烧录

```bash
python3 skills/flash-openocd/scripts/openocd_flasher.py \
  --artifact build/debug/app.elf \
  --config board/st_nucleo_f4.cfg
```

板级配置通常已包含接口和目标定义，无需再单独指定。

### 4. 烧录 BIN 文件

```bash
python3 skills/flash-openocd/scripts/openocd_flasher.py \
  --artifact build/firmware.bin \
  --interface cmsis-dap \
  --target target/stm32f1x.cfg \
  --base-address 0x08000000
```

BIN 文件必须提供 `--base-address`，否则脚本会拒绝执行。

### 5. 跳过校验或复位

```bash
python3 skills/flash-openocd/scripts/openocd_flasher.py \
  --artifact build/app.elf \
  --config board/st_nucleo_f4.cfg \
  --no-verify \
  --no-reset
```

### 6. 扫描工作区配置线索

```bash
python3 skills/flash-openocd/scripts/openocd_flasher.py \
  --scan-configs /repo/fw
```

在工作区中搜索 `openocd*.cfg`、`.vscode/launch.json` 等配置线索。

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `--detect` | 探测 OpenOCD 环境和已连接探针 |
| `--artifact` | 固件产物路径（ELF、HEX 或 BIN） |
| `--interface` | 调试接口：`stlink`、`cmsis-dap`、`daplink`、`jlink` |
| `--target` | OpenOCD 目标配置文件 |
| `--config` | 额外的 OpenOCD `-f` 配置，可重复 |
| `--base-address` | BIN 文件的烧录基地址（十六进制） |
| `--no-verify` | 跳过烧录后校验 |
| `--no-reset` | 烧录后不复位目标 |
| `--no-detect` | 禁止自动探测调试接口 |
| `--scan-configs` | 扫描指定目录中的 OpenOCD 配置线索 |
| `--openocd-command` | 自定义 OpenOCD 烧录命令（覆盖自动生成） |
| `--resume` | 从工程根目录 `.em_skill.json` 的缓存 profile 恢复上次成功参数 |
| `--profile` | 指定缓存 profile 名，默认 `default` |
| `--workspace` | 指定工程根目录，profile 固定读写该目录下的 `.em_skill.json` |
| `--show-profile` | 输出当前缓存 profile 并退出 |
| `--clear-profile` | 删除当前缓存 profile 并退出 |
| `--no-save-profile` | 成功后不更新缓存 profile |
| `-v`, `--verbose` | 输出详细日志 |

## SWD 接线参考

所有 SWD 调试器通用的最小接线：

```
调试器        MCU
--------    --------
SWDIO    →  PA13 (SWDIO)
SWCLK    →  PA14 (SWCLK)
GND      →  GND
3.3V     →  3.3V (可选，部分调试器可供电)
NRST     →  NRST (可选，用于硬件复位)
```

注意：PA13/PA14 是 STM32 默认 SWD 引脚，如果固件重新映射了这些引脚，需要在复位状态下烧录。

## 调试器对比

| 调试器 | 优势 | 缺点 | 推荐场景 |
|--------|------|------|----------|
| ST-Link V2/V3 | STM32 官方，稳定可靠 | 仅支持 ST 芯片 | STM32 专项开发 |
| CMSIS-DAP / DAPlink | 开源，低成本，多平台 | 速度较慢 | 教学、多平台开发 |
| J-Link | 速度快，芯片支持广 | 商业许可 | 专业开发、量产 |

## 完整工作流示例

### 开发迭代

```bash
# 1. 编译
python3 skills/build-cmake/scripts/cmake_builder.py --project /path/to/project

# 2. 烧录
python3 skills/flash-openocd/scripts/openocd_flasher.py \
  --artifact build/debug/app.elf \
  --interface stlink \
  --target target/stm32f4x.cfg

# 3. 验证串口输出
python3 skills/serial-monitor/scripts/serial_monitor.py \
  --auto --wait "System Start"
```

### 生产烧录

```bash
python3 skills/flash-openocd/scripts/openocd_flasher.py \
  --artifact build/release/app.hex \
  --interface stlink \
  --target target/stm32f4x.cfg \
  --no-reset
```

## 故障排查

### 探针未识别

症状：`Error: unable to find a matching CMSIS-DAP device` 或 `Error: open failed`

排查步骤：
1. 检查 USB 连接是否牢固
2. 确认设备管理器（Windows）或 `lsusb`（Linux）能看到调试器
3. 关闭其他占用调试器的程序（Keil、STM32CubeProgrammer、其他 OpenOCD 实例）
4. Linux 用户添加 udev 规则：
   ```bash
   # /etc/udev/rules.d/99-openocd.rules
   # ST-Link
   SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3748", MODE="0666"
   # CMSIS-DAP
   SUBSYSTEM=="usb", ATTR{idVendor}=="0d28", ATTR{idProduct}=="0204", MODE="0666"

   sudo udevadm control --reload-rules
   ```

### 烧录速度慢

尝试提高适配器速度：

```bash
python3 skills/flash-openocd/scripts/openocd_flasher.py \
  --artifact build/app.elf \
  --interface cmsis-dap \
  --target target/stm32f1x.cfg \
  --openocd-command "adapter speed 1000; program {artifact} verify reset exit"
```

### 烧录后程序不运行

排查步骤：
1. 确认烧录时没有使用 `--no-reset`
2. 检查 BOOT0 引脚是否拉低（应为 GND，从 Flash 启动）
3. 用 `--detect` 确认探针仍然连接
4. 尝试手动复位目标板

### BIN 文件烧录失败

BIN 文件不包含地址信息，必须指定 `--base-address`。STM32 Flash 起始地址通常为 `0x08000000`。

## 返回码

- `0`：烧录成功（含校验通过）
- `1`：参数非法、依赖缺失、探针连接失败、烧录失败、或校验失败

## 与 Skill 的配合方式

在 `flash-openocd` skill 中，推荐工作流是：

1. 先根据用户输入或 `Project Profile` 确定产物路径和 OpenOCD 配置
2. 若不确定探针状态，先用 `--detect` 确认
3. 组装合适的烧录参数（接口 + 目标，或板级配置）
4. 将脚本输出的烧录结果整理成简洁摘要
5. 更新 `Project Profile`，交给 `serial-monitor` 或 `debug-gdb-openocd`
