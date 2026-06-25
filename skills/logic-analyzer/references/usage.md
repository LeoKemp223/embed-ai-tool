# 逻辑分析仪采集 Skill 用法

## 基础用法

```bash
# 探测环境（包、端口、Logic 2 连通性、设备）
python scripts/la_tool.py --detect

# 列出已连接设备
python scripts/la_tool.py --devices

# 包含仿真设备（无硬件测试）
python scripts/la_tool.py --devices --include-sim

# 单协议 I2C（SCL=CH0, SDA=CH1），输出自动落到 .captures/logic-analyzer/
python scripts/la_tool.py --capture --channels 0-1 --samplerate 4M --duration 5 \
    --analyzer "i2c:scl=0,sda=1"

# 多协议同时解码：I2C + UART + SPI，各自导出独立 CSV
python scripts/la_tool.py --capture --channels 0-6 --samplerate 16M --duration 5 \
    --analyzer "i2c:scl=0,sda=1" \
    --analyzer "uart:rx=2,baud=115200" \
    --analyzer "spi:clk=3,mosi=4,miso=5,cs=6"

# 同协议多路（自动按 i2c / i2c2 命名导出）
python scripts/la_tool.py --capture --channels 0-3 --samplerate 4M --duration 5 \
    --analyzer "i2c:scl=0,sda=1" --analyzer "i2c:scl=2,sda=3"

# CAN（单线，500kbps）
python scripts/la_tool.py --capture --channels 0 --samplerate 4M --duration 5 \
    --analyzer "can:can=0,baud=500000"

# 自动启动 Logic 2（实验性，部分环境不可用，见“前置条件”）
python scripts/la_tool.py --launch --capture --channels 0-1 \
    --analyzer "i2c:scl=0,sda=1"

# 单解码器指定输出文件名与进制
python scripts/la_tool.py --capture --channels 0-1 --samplerate 4M --duration 5 \
    --analyzer "i2c:scl=0,sda=1" --output bus1.csv --radix hex

# 同时导出原始波形和保存 .sal
python scripts/la_tool.py --capture --channels 0-1 --samplerate 4M --duration 5 \
    --analyzer "i2c:scl=0,sda=1" --raw-dir raw_out --save cap.sal

# JSON 输出
python scripts/la_tool.py --capture --channels 0-1 --analyzer "uart:rx=0,baud=115200" --format json

# 旧式单协议写法（向后兼容，仍可用）
python scripts/la_tool.py --capture --channels 0-1 --samplerate 4M --duration 5 \
    --decode i2c --i2c-scl 0 --i2c-sda 1
```

## 参数说明

### 模式参数

| 参数 | 说明 |
| --- | --- |
| `--detect` | 探测环境与 Logic 2 连通性（不依赖包安装也会给提示） |
| `--devices` | 列出已连接设备 |
| `--capture` | 执行在线采集 |

### 连接参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--address` | 127.0.0.1 | Logic 2 地址 |
| `--port` | 10430 | 自动化服务端口 |
| `--connect-timeout` | 5.0 | 连接超时秒数 |
| `--device-id` | — | 指定设备 ID（不填用第一个） |
| `--include-sim` | false | 包含 Logic 2 仿真设备 |
| `--launch` | false | 自动启动 Logic 2（用完自动关闭，实验性，部分环境不可用） |
| `--app-path` | — | Logic 2 可执行文件路径（`--launch` 时；不填自动查找） |

### 采集参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--channels` | 0-3 | 数字通道，如 `0-3` 或 `0,1,4,7` |
| `--samplerate` | 10M | 数字采样率，支持 `24M`/`10M`/`500K`/数字 |
| `--duration` | 5.0 | 采集持续秒数（定时模式） |

### 解码参数（推荐）

| 参数 | 说明 |
| --- | --- |
| `--analyzer SPEC` | 可重复。格式 `协议:键=值,...`，一次采集挂多个解码器 |

各协议的键：

| 协议 | SPEC 示例 | 键（必填 / 可选） |
| --- | --- | --- |
| i2c | `i2c:scl=0,sda=1` | `scl`、`sda`（均必填） |
| spi | `spi:clk=3,mosi=4,miso=5,cs=6` | `clk` 必填；`mosi`、`miso`、`cs` 可选 |
| uart | `uart:rx=2,baud=115200` | `rx` 必填；`baud` 默认 115200 |
| can | `can:can=0,baud=500000` | `can` 必填；`baud` 默认 500000 |

### 解码参数（旧式，向后兼容）

仅在未提供 `--analyzer` 时生效。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--decode` | — | 协议类型：`i2c`/`spi`/`uart` |
| `--i2c-sda` | 0 | I2C SDA 通道 |
| `--i2c-scl` | 1 | I2C SCL 通道 |
| `--spi-mosi` | — | SPI MOSI 通道 |
| `--spi-miso` | — | SPI MISO 通道 |
| `--spi-clk` | — | SPI Clock 通道 |
| `--spi-cs` | — | SPI Enable/CS 通道 |
| `--uart-rx` | 0 | UART 输入通道 |
| `--baudrate` | 115200 | UART 波特率 |

### 输出参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--output` | — | 单解码器时的 CSV 路径；多解码器时忽略，按 label 自动命名 |
| `--radix` | hex | 数据进制：`hex`/`dec`/`bin`/`ascii` |
| `--raw-dir` | — | 原始波形导出目录 |
| `--save` | — | 保存 .sal 采集文件路径 |
| `--format` | table | 输出格式：table、json |

### 输出位置规则

- 默认目录：工程根 `.captures/logic-analyzer/`，可用环境变量 `LA_CAPTURE_DIR` 覆盖。
- 未指定 `--output`：按 `<协议label>_<时间戳>.csv` 自动命名，防覆盖。
- `--output` 给相对路径：相对默认目录；给绝对路径：原样使用。
- `--raw-dir` / `--save` 同理（相对默认目录或绝对路径）。

## 解码器设置键核对表

脚本传给 `add_analyzer(name, settings)` 的名称与键**必须与 Logic 2 界面显示完全一致**。
若 Logic 2 版本更新导致键名变化，按界面文字修正 [scripts/la_tool.py](../scripts/la_tool.py) 的 `ANALYZER_SPECS`：

| 协议 | analyzer name | settings 键（SPEC 短键 → API 键） |
| --- | --- | --- |
| I2C | `I2C` | `scl`→`SCL`、`sda`→`SDA` |
| SPI | `SPI` | `clk`→`Clock`、`mosi`→`MOSI`、`miso`→`MISO`、`cs`→`Enable`（未提供的省略） |
| UART | `Async Serial` | `rx`→`Input Channel`、`baud`→`Bit Rate (Bits/s)` |
| CAN | `CAN` | `can`→`CAN`、`baud`→`Bit Rate (Bits/s)` |

### 扩展新协议

在 `ANALYZER_NAMES` 加协议名映射，并在 `ANALYZER_SPECS` 加一条 `{协议: {"keys": {短键: API键}, "required": [必填短键]}}`，
解析、采集、导出逻辑自动复用，无需改其它代码。

## 前置条件

1. 打开 Logic 2 桌面软件。
2. 开启 automation server：Settings/Preferences → Automation，或点底部状态栏的 Automation 按钮；
   也可命令行 `"C:\Program Files\Logic\Logic.exe" --automation` 启动（默认端口 10430）。
3. 连接 Saleae 设备，或用 `--include-sim` 走仿真设备。

> `--launch` 自动启动 Logic 2 为实验性功能：在部分环境（如从 git bash 后台启动 GUI）下进程无法维持、端口起不来。默认仍建议手动打开 Logic 2 并用普通连接模式。

## 自然语言提示词模板（供 AI 调用）

通道映射是必须说清的物理接线信息，AI 无法探测，须明确每条线接在哪个通道：

| 协议 | 提示词骨架 |
| --- | --- |
| I2C | `抓 I2C，SCL=__，SDA=__，采集__秒` |
| SPI | `抓 SPI，CLK=__，MOSI=__，MISO=__，CS=__，采集__秒` |
| UART | `抓 UART，RX=__，波特率__，采集__秒` |
| CAN | `抓 CAN，信号接通道__，波特率__，采集__秒` |
| 多协议 | `同时抓 I2C(SCL=5,SDA=6) 和 UART(RX=2,波特率115200)，采集15秒` |

可省略（用默认）：采样率、时长（5 秒）、端口/地址。采集期间务必让总线有通信，否则解出空表。

## 返回码

- `0`：操作成功
- `1`：包未安装、连接失败、无设备、采集或解码失败
