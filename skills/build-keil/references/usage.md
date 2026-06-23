# Keil MDK 构建 Skill 用法

这个 skill 自带了一个可执行脚本 [scripts/keil_builder.py](../scripts/keil_builder.py)，适合在需要探测 Keil MDK 安装、解析 `.uvprojx` 工程文件、执行命令行编译并定位固件产物时直接调用。

## 能力概览

- 探测 Keil MDK 安装路径和 UV4.exe 命令行工具
- 扫描工作区中的 `.uvprojx` / `.uvproj` 工程文件
- 解析工程文件中的目标（Target）列表、输出目录和芯片信息
- 通过 UV4.exe 命令行执行编译（build / rebuild / clean）
- 在输出目录中搜索 AXF、HEX、BIN 产物并按优先级排序
- 解析编译日志，提取错误和警告统计
- 输出结构化的构建结果报告

## 基础用法

```bash
# 探测 Keil MDK 环境
python skills/build-keil/scripts/keil_builder.py --detect

# 列出工程中的目标
python skills/build-keil/scripts/keil_builder.py --list-targets --project path/to/app.uvprojx

# 编译默认目标
python skills/build-keil/scripts/keil_builder.py --project path/to/app.uvprojx

# 编译指定目标
python skills/build-keil/scripts/keil_builder.py --project path/to/app.uvprojx --target "Debug"

# 重新编译（clean + build）
python skills/build-keil/scripts/keil_builder.py --project path/to/app.uvprojx --rebuild

# 一次完成探测 + 编译（推荐，省掉多次进程启动）
python skills/build-keil/scripts/keil_builder.py --detect --project path/to/app.uvprojx --target "Debug"
```

## 常见模式

### 0. 新会话恢复

```bash
python3 skills/build-keil/scripts/keil_builder.py --resume
```

成功构建后缓存工程文件、target、UV4 路径和首选产物；脚本启动即自动复用这些缓存参数（显式参数优先）；无缓存或缓存失效时自动回退，例如 `--detect` 或 `--scan`。


### 1. 环境探测

```bash
python skills/build-keil/scripts/keil_builder.py --detect
```

输出 Keil MDK 安装路径、UV4.exe 位置、ARMCC/ARMCLANG 编译器版本。

### 2. 扫描工作区工程文件

```bash
python skills/build-keil/scripts/keil_builder.py --scan /path/to/project
```

在工作区中递归搜索 `.uvprojx` 和 `.uvproj` 文件。

### 3. 列出工程目标

```bash
python skills/build-keil/scripts/keil_builder.py \
  --list-targets \
  --project path/to/app.uvprojx
```

### 4. 编译指定目标

```bash
python skills/build-keil/scripts/keil_builder.py \
  --project path/to/app.uvprojx \
  --target "Release" \
  --verbose
```

### 5. 重新编译

```bash
python skills/build-keil/scripts/keil_builder.py \
  --project path/to/app.uvprojx \
  --target "Debug" \
  --rebuild
```

### 6. 仅扫描已有产物

```bash
python skills/build-keil/scripts/keil_builder.py \
  --scan-artifacts path/to/Objects
```

### 7. 指定 UV4 路径

```bash
python skills/build-keil/scripts/keil_builder.py \
  --project path/to/app.uvprojx \
  --uv4 "C:\Keil_v5\UV4\UV4.exe"
```

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `--detect` | 探测 Keil MDK 环境 |
| `--project` | `.uvprojx` 或 `.uvproj` 工程文件路径 |
| `--target` | 构建目标名称（对应工程中的 Target） |
| `--list-targets` | 列出工程中的所有目标 |
| `--rebuild` | 重新编译（等价于 clean + build） |
| `--scan` | 扫描指定目录中的 Keil 工程文件 |
| `--scan-artifacts` | 仅扫描指定目录中的固件产物 |
| `--uv4` | 显式指定 UV4.exe 路径 |
| `--log` | 编译日志输出路径 |
| `--resume` | 从工程根目录 `.em_skill.json` 的缓存 profile 恢复上次成功参数 |
| `--profile` | 指定缓存 profile 名，默认 `default` |
| `--workspace` | 指定工程根目录，profile 固定读写该目录下的 `.em_skill.json` |
| `--show-profile` | 输出当前缓存 profile 并退出 |
| `--clear-profile` | 删除当前缓存 profile 并退出 |
| `--no-save-profile` | 成功后不更新缓存 profile |
| `-v`, `--verbose` | 输出详细编译日志 |

## 返回码

- `0`：编译成功并找到产物，或探测/列表操作成功
- `1`：参数非法、Keil 未安装、工程文件无效、编译失败、或未找到产物

## 平台说明

Keil MDK 仅在 Windows 上原生运行。脚本在非 Windows 平台上仍可执行 `--scan`、`--list-targets`、`--scan-artifacts` 等不依赖 UV4.exe 的操作，但实际编译需要 Windows 环境。

## 与 Skill 的配合方式

在 `build-keil` skill 中，推荐工作流是：

1. 对于单工程、单目标的常见场景，直接一次调用完成探测+编译：
   ```bash
   python scripts/keil_builder.py --detect --project <工程文件> --target <目标名>
   ```
2. 仅在需要交互式选择时（多个工程文件或多个目标），才分步执行 `--scan`、`--list-targets`
3. 将脚本输出的产物路径和构建信息整理成简洁摘要
4. 用产物路径更新 `Project Profile`，交给 `flash-openocd` 或 `debug-gdb-openocd`
