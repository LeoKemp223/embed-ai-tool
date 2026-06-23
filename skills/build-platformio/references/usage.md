# PlatformIO 构建 Skill 用法

这个 skill 自带了一个可执行脚本 [scripts/platformio_builder.py](../scripts/platformio_builder.py)，适合在需要探测 PlatformIO 环境、解析 `platformio.ini` 配置、执行构建并定位固件产物时直接调用。

## 能力概览

- 探测 PlatformIO CLI (`pio`) 是否可用及版本
- 解析 `platformio.ini` 中的环境列表（platform、board、framework）
- 识别默认环境（`default_envs`）
- 执行 `pio run` 构建、清理和上传
- 列出已连接的设备（`pio device list`）
- 在 `.pio/build/<env>/` 中搜索 firmware.elf/hex/bin 产物并按优先级排序
- 输出结构化的构建结果报告

## 基础用法

```bash
# 探测 PlatformIO 环境
python3 skills/build-platformio/scripts/platformio_builder.py --detect

# 列出可用环境
python3 skills/build-platformio/scripts/platformio_builder.py --list-envs --project-dir /path/to/project

# 构建默认环境
python3 skills/build-platformio/scripts/platformio_builder.py --project-dir /path/to/project

# 构建指定环境
python3 skills/build-platformio/scripts/platformio_builder.py --project-dir /path/to/project --env esp32dev

# 清理
python3 skills/build-platformio/scripts/platformio_builder.py --project-dir /path/to/project --clean

# 上传固件
python3 skills/build-platformio/scripts/platformio_builder.py --project-dir /path/to/project --upload

# 列出设备
python3 skills/build-platformio/scripts/platformio_builder.py --list-devices
```

## 常见模式

### 0. 新会话恢复

```bash
python3 skills/build-platformio/scripts/platformio_builder.py --resume
```

成功构建后缓存 `project-dir`、`env` 和首选产物；脚本启动即自动复用这些缓存参数（显式参数优先）；无缓存或缓存失效时自动回退，例如 `--detect`、`--list-envs` 或重新扫描。


### 1. 环境探测

```bash
python3 skills/build-platformio/scripts/platformio_builder.py --detect
```

输出 PlatformIO CLI 版本和路径。

### 2. 列出工程环境

```bash
python3 skills/build-platformio/scripts/platformio_builder.py \
  --list-envs \
  --project-dir /path/to/project
```

### 3. 构建指定环境

```bash
python3 skills/build-platformio/scripts/platformio_builder.py \
  --project-dir /path/to/project \
  --env nucleo_f429zi \
  --verbose
```

### 4. 清理后重新构建

```bash
python3 skills/build-platformio/scripts/platformio_builder.py \
  --project-dir /path/to/project \
  --env esp32dev \
  --clean

python3 skills/build-platformio/scripts/platformio_builder.py \
  --project-dir /path/to/project \
  --env esp32dev
```

### 5. 仅扫描已有产物

```bash
python3 skills/build-platformio/scripts/platformio_builder.py \
  --scan-artifacts /path/to/project/.pio/build/esp32dev
```

### 6. 上传固件到设备

```bash
python3 skills/build-platformio/scripts/platformio_builder.py \
  --project-dir /path/to/project \
  --env nucleo_f429zi \
  --upload
```

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `--detect` | 探测 PlatformIO 环境 |
| `--project-dir` | PlatformIO 工程目录（包含 `platformio.ini`） |
| `--env` | 构建环境名称 |
| `--list-envs` | 列出工程中的所有环境 |
| `--clean` | 清理构建产物 |
| `--upload` | 构建并上传固件到设备 |
| `--list-devices` | 列出已连接的设备 |
| `--scan-artifacts` | 仅扫描指定目录中的固件产物 |
| `--resume` | 从工程根目录 `.em_skill.json` 的缓存 profile 恢复上次成功参数 |
| `--profile` | 指定缓存 profile 名，默认 `default` |
| `--workspace` | 指定工程根目录，profile 固定读写该目录下的 `.em_skill.json` |
| `--show-profile` | 输出当前缓存 profile 并退出 |
| `--clear-profile` | 删除当前缓存 profile 并退出 |
| `--no-save-profile` | 成功后不更新缓存 profile |
| `-v`, `--verbose` | 输出详细构建日志 |
| `-j`, `--jobs` | 并行构建任务数 |

## 返回码

- `0`：构建成功并找到产物，或探测/列表操作成功
- `1`：参数非法、PlatformIO 未安装、配置无效、构建失败、或未找到产物

## 与 Skill 的配合方式

在 `build-platformio` skill 中，推荐工作流是：

1. 先根据用户输入或 `Project Profile` 确定工程目录和环境
2. 若不确定环境是否就绪，先用 `--detect` 确认
3. 用 `--list-envs` 确认可用环境，再执行构建
4. 将脚本输出的产物路径和构建信息整理成简洁摘要
5. 用产物路径更新 `Project Profile`，交给 `flash-openocd` 或 `debug-gdb-openocd`
