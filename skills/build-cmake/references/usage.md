# CMake 构建 Skill 用法

这个 skill 自带了一个可执行脚本 [scripts/cmake_builder.py](../scripts/cmake_builder.py)，适合在需要自动探测工程配置、执行 CMake 构建、定位固件产物时直接调用。

## 能力概览

- 自动探测 cmake、ninja/make 等构建工具是否可用
- 扫描 CMakePresets.json 并列出可用预设
- 扫描 CMakeLists.txt 提取工程名和工具链文件线索
- 自动选择生成器（优先 Ninja）
- 执行 cmake configure + build 全流程
- 在构建目录中搜索 ELF、HEX、BIN 产物并按优先级排序
- 输出结构化的构建结果和分析报告
- 成功构建后把可复用参数写入工程根目录 `.em_skill.json`，新对话可用 `--resume` 快速复用

## 基础用法

```bash
# 新会话优先尝试复用上次成功构建
python3 skills/build-cmake/scripts/cmake_builder.py --resume

# 探测构建环境
python3 skills/build-cmake/scripts/cmake_builder.py --detect

# 列出可用预设
python3 skills/build-cmake/scripts/cmake_builder.py --list-presets --source /path/to/project

# 使用预设构建
python3 skills/build-cmake/scripts/cmake_builder.py --source /path/to/project --preset debug

# 手动指定构建目录和类型
python3 skills/build-cmake/scripts/cmake_builder.py \
  --source /path/to/project \
  --build-dir /path/to/project/build \
  --build-type Debug
```

## 常见模式

### 1. 缓存自动复用（新会话）

```bash
# 直接运行目标动作即可，缓存命中时参数自动补全
python3 skills/build-cmake/scripts/cmake_builder.py
# 如需断言缓存必须存在（无缓存则非零退出）：
python3 skills/build-cmake/scripts/cmake_builder.py --resume
```

脚本启动即自动从工程根目录 `.em_skill.json` 读取 `skill_profiles.build-cmake.default`，复用上次成功构建的源码目录、构建目录、预设、生成器、构建类型、工具链和目标名（显式参数优先，无需先手动传 `--resume`）。无缓存时脚本自动回退到环境探测或工程扫描；`--resume` 仅用于断言缓存必须存在，无缓存则非零退出。

查看或清理缓存：

```bash
python3 skills/build-cmake/scripts/cmake_builder.py --show-profile
python3 skills/build-cmake/scripts/cmake_builder.py --clear-profile
```

需要区分多个固件目标时使用命名 profile：

```bash
python3 skills/build-cmake/scripts/cmake_builder.py --source /repo/fw --preset debug --profile bootloader
python3 skills/build-cmake/scripts/cmake_builder.py --resume --profile bootloader
```

### 2. 环境探测

```bash
python3 skills/build-cmake/scripts/cmake_builder.py --detect
```

输出 cmake 版本、可用生成器、工具链编译器等信息，适合在构建前确认环境就绪。

### 3. 使用预设构建

```bash
python3 skills/build-cmake/scripts/cmake_builder.py \
  --source /repo/fw \
  --preset debug
```

自动读取 CMakePresets.json，使用指定预设完成配置和构建。

### 4. 手动配置构建

```bash
python3 skills/build-cmake/scripts/cmake_builder.py \
  --source /repo/fw \
  --build-dir /repo/fw/build/debug \
  --generator Ninja \
  --build-type Debug \
  --toolchain /repo/fw/cmake/arm-none-eabi.cmake
```

### 5. 指定构建目标

```bash
python3 skills/build-cmake/scripts/cmake_builder.py \
  --source /repo/fw \
  --preset debug \
  --target app
```

### 6. 仅搜索已有产物

```bash
python3 skills/build-cmake/scripts/cmake_builder.py \
  --scan-artifacts /repo/fw/build/debug
```

不执行构建，仅在指定目录中搜索 ELF/HEX/BIN 产物。

### 7. 清理后重新构建

```bash
python3 skills/build-cmake/scripts/cmake_builder.py \
  --source /repo/fw \
  --preset debug \
  --clean
```

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `--detect` | 探测构建环境（cmake、生成器、编译器） |
| `--source` | CMake 源码目录（包含 CMakeLists.txt） |
| `--build-dir` | 构建输出目录 |
| `--preset` | 使用 CMakePresets.json 中的预设名 |
| `--list-presets` | 列出可用的 CMake 预设 |
| `--generator` | CMake 生成器，例如 `Ninja`、`Unix Makefiles` |
| `--build-type` | 构建类型：`Debug`、`Release`、`RelWithDebInfo`、`MinSizeRel` |
| `--toolchain` | 工具链文件路径 |
| `--target` | 构建目标名称 |
| `--clean` | 构建前清理构建目录 |
| `--scan-artifacts` | 仅扫描指定目录中的固件产物 |
| `--extra-args` | 传递给 cmake configure 的额外参数，可重复 |
| `--resume` | 从工程根目录 `.em_skill.json` 的缓存 profile 恢复上次成功构建参数 |
| `--profile` | 指定缓存 profile 名，默认 `default` |
| `--workspace` | 指定工程根目录，profile 固定读写该目录下的 `.em_skill.json` |
| `--show-profile` | 输出当前缓存 profile |
| `--clear-profile` | 删除当前缓存 profile |
| `--no-save-profile` | 成功构建后不更新缓存 profile |
| `-v`, `--verbose` | 输出详细构建日志 |
| `-j`, `--jobs` | 并行构建任务数 |

## 返回码

- `0`：构建成功并找到产物，或探测/列表操作成功
- `1`：参数非法、依赖缺失、配置失败、构建失败、或未找到产物

## 与 Skill 的配合方式

在 `build-cmake` skill 中，推荐工作流是：

1. 直接运行目标动作即可——脚本启动时自动复用工程根目录 `.em_skill.json` 中上次成功构建的 profile（显式参数优先）；仅当需要断言缓存必须存在时才加 `--resume`
2. 若无缓存或用户要求重新配置，根据用户输入或 `Project Profile` 决定源码目录、构建类型和预设
3. 若不确定环境是否就绪，先用 `--detect` 确认
4. 选择合适的构建模式（预设 vs 手动配置）
5. 将脚本输出的产物路径和构建信息整理成简洁摘要
6. 用产物路径更新 `Project Profile`，交给 `flash-openocd` 或 `debug-gdb-openocd`
