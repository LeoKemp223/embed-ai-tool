# IAR Embedded Workbench 构建 Skill 用法

这个 skill 自带了一个可执行脚本 [scripts/iar_builder.py](../scripts/iar_builder.py)，适合在需要探测 IAR 安装、解析 `.ewp` 工程文件、执行命令行编译并定位固件产物时直接调用。

## 能力概览

- 探测 IAR Embedded Workbench 安装路径和 iarbuild.exe 命令行工具
- 扫描工作区中的 `.ewp` / `.eww` 工程文件
- 解析工程文件中的 configuration 列表、工具链、芯片和输出目录
- 通过 iarbuild.exe 命令行执行编译（make / build / clean）
- 在输出目录中搜索 .out（ELF）、HEX、BIN 产物并按优先级排序
- 输出结构化的构建结果报告

## 基础用法

```bash
# 探测 IAR 环境
python3 skills/build-iar/scripts/iar_builder.py --detect

# 扫描工作区工程文件
python3 skills/build-iar/scripts/iar_builder.py --scan /path/to/project

# 列出工程中的配置
python3 skills/build-iar/scripts/iar_builder.py --list-configs --project path/to/app.ewp

# 编译默认配置
python3 skills/build-iar/scripts/iar_builder.py --project path/to/app.ewp

# 编译指定配置
python3 skills/build-iar/scripts/iar_builder.py --project path/to/app.ewp --config Debug

# 重新编译（clean + build）
python3 skills/build-iar/scripts/iar_builder.py --project path/to/app.ewp --rebuild

# 清理
python3 skills/build-iar/scripts/iar_builder.py --project path/to/app.ewp --config Debug --clean
```

## 常见模式

### 0. 新会话恢复

```bash
python3 skills/build-iar/scripts/iar_builder.py --resume
```

成功构建后缓存工程文件、configuration、iarbuild 路径和首选产物；脚本启动即自动复用这些缓存参数（显式参数优先）；无缓存或缓存失效时自动回退，例如 `--detect` 或 `--scan`。


### 1. 环境探测

```bash
python3 skills/build-iar/scripts/iar_builder.py --detect
```

输出 IAR 安装路径、iarbuild.exe 位置。

### 2. 扫描工作区工程文件

```bash
python3 skills/build-iar/scripts/iar_builder.py --scan /path/to/project
```

在工作区中递归搜索 `.ewp` 和 `.eww` 文件。

### 3. 列出工程配置

```bash
python3 skills/build-iar/scripts/iar_builder.py \
  --list-configs \
  --project path/to/app.ewp
```

### 4. 编译指定配置

```bash
python3 skills/build-iar/scripts/iar_builder.py \
  --project path/to/app.ewp \
  --config "Release"
```

### 5. 重新编译

```bash
python3 skills/build-iar/scripts/iar_builder.py \
  --project path/to/app.ewp \
  --config "Debug" \
  --rebuild
```

### 6. 仅扫描已有产物

```bash
python3 skills/build-iar/scripts/iar_builder.py \
  --scan-artifacts path/to/Debug/Exe
```

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `--detect` | 探测 IAR 环境 |
| `--project` | `.ewp` 工程文件路径 |
| `--config` | 构建配置名称（对应工程中的 configuration） |
| `--list-configs` | 列出工程中的所有配置 |
| `--rebuild` | 重新编译（等价于 clean + build） |
| `--clean` | 清理指定配置 |
| `--scan` | 扫描指定目录中的 IAR 工程文件 |
| `--scan-artifacts` | 仅扫描指定目录中的固件产物 |
| `--iar-root` | 显式指定 IAR 安装根目录 |
| `--parallel` | 并行编译任务数 |
| `--resume` | 从工程根目录 `.em_skill.json` 的缓存 profile 恢复上次成功参数 |
| `--profile` | 指定缓存 profile 名，默认 `default` |
| `--workspace` | 指定工程根目录，profile 固定读写该目录下的 `.em_skill.json` |
| `--show-profile` | 输出当前缓存 profile 并退出 |
| `--clear-profile` | 删除当前缓存 profile 并退出 |
| `--no-save-profile` | 成功后不更新缓存 profile |
| `-v`, `--verbose` | 输出详细编译日志（`-log all`） |

## 返回码

- `0`：编译成功并找到产物，或探测/列表操作成功
- `1`：参数非法、IAR 未安装、工程文件无效、编译失败、或未找到产物

## 平台说明

IAR Embedded Workbench 仅在 Windows 上原生运行。脚本在非 Windows 平台上仍可执行 `--scan`、`--list-configs`、`--scan-artifacts` 等不依赖 iarbuild.exe 的操作，但实际编译需要 Windows 环境。

## 与 Skill 的配合方式

在 `build-iar` skill 中，推荐工作流是：

1. 先根据用户输入或 `Project Profile` 确定工程文件和配置
2. 若不确定环境是否就绪，先用 `--detect` 确认
3. 若不确定工程文件位置，用 `--scan` 搜索工作区
4. 用 `--list-configs` 确认可用配置，再执行编译
5. 将脚本输出的产物路径和构建信息整理成简洁摘要
6. 用产物路径更新 `Project Profile`，交给 `flash-openocd` 或 `debug-gdb-openocd`
