---
name: build-cmake
description: 当需要配置或构建基于 CMake 的嵌入式固件工程，调用自带脚本执行构建并定位固件产物时使用。
---

# 构建 CMake 工程

## 适用场景

- `Project Profile` 中标明 `build_system: cmake`。
- 用户希望对 CMake MCU 工程执行配置、重编译或确认固件产物。
- 烧录或调试流程需要新的 `ELF`、`HEX` 或 `BIN`。
- 需要在构建前确认环境是否就绪（cmake、生成器、工具链）。

## 必要输入

- 工作区路径，或一份已有的 `Project Profile`。
- 可选的构建预设、构建目录、目标名、生成器、构建类型和工具链文件。

## 自动探测

- 若存在 `CMakePresets.json`，优先使用脚本的 `--list-presets` 列出并选择预设。
- 否则检查 `CMakeLists.txt`、已有构建目录和工具链文件。
- 若已有成功的构建目录且与当前意图一致，优先复用。
- 脚本启动即自动读取 `.em_skill.json` 中的 `skill_profiles.build-cmake`，把上次成功构建参数作为默认值复用（显式参数优先，无需先手动传 `--resume`）；`--resume` 仅用于断言缓存必须存在，无缓存则非零退出。无缓存或用户要求重新探测时，脚本自动回退到 `--detect`、`--list-presets` 或手动参数探索。
- 生成器由脚本自动探测，优先 `Ninja`，其次是宿主机上已安装的 Make 工具。
- 对调试导向请求默认使用 `Debug`，否则默认使用 `RelWithDebInfo`。

## 执行步骤

1. 先阅读 [references/usage.md](references/usage.md)，确认本次是执行构建、环境探测、列出预设，还是仅扫描产物。
2. 直接运行目标动作即可——脚本启动时会自动复用工程根目录 `.em_skill.json` 中上次成功构建的源码目录、构建目录、预设、目标和产物信息（显式参数优先）。仅当需要断言缓存必须存在时才加 `--resume --profile default`。
3. 若无缓存或用户要求重新探测，脚本自动回退到 `--detect`、`--list-presets` 或手动参数探索。
4. 若存在 CMakePresets.json，使用 `--list-presets` 列出预设，再用 `--preset <name>` 构建。
5. 若无预设，使用 `--source`、`--build-dir`、`--generator`、`--build-type`、`--toolchain` 手动配置构建。
6. 读取脚本输出的构建结果和产物扫描报告，重点关注首选产物（ELF > HEX > BIN）和失败分类。
7. 成功构建后脚本会自动更新工程根目录 `.em_skill.json` 的 `skill_profiles.build-cmake.default`；将构建目录、产物路径、产物类型和生成器信息同步到 `Project Profile`，并在需要时交给下游 skill。

## 失败分流

- 当缺少 `cmake` 或所需生成器时，返回 `environment-missing`。
- 当配置或构建因预设损坏、缺失工具链文件或目标名无效而失败时，返回 `project-config-error`。
- 当构建看似成功但未找到可烧录或可调试产物时，返回 `artifact-missing`。
- 当存在多个同样合理的预设或固件目标，且任意选择都不安全时，返回 `ambiguous-context`。

## 平台说明

- 在 Windows 上，除非工作区明确要求特定 Visual Studio shell，否则优先 `Ninja`，避免依赖特定开发者命令环境。
- 自带脚本使用 Python 标准库和 subprocess 调用 cmake，因此构建调度路径本身是跨平台的。
- 输出中的构建目录应保持为绝对路径，方便下游烧录和调试 skill 直接复用。

## 输出约定

- 输出配置命令、构建命令、构建目录、所选生成器和首选产物路径。
- 成功构建后持久化 `source`、`build_dir`、`preset`、`generator`、`build_type`、`toolchain`、`target` 和首选产物到工程根目录 `.em_skill.json`。
- 用 `artifact_path`、`artifact_kind` 和探测到的工具链细节更新 `Project Profile`。
- 成功后推荐 `flash-openocd` 或 `debug-gdb-openocd`。

## 交接关系

- 当下一步意图是给硬件烧录程序时，将成功构建结果交给 `flash-openocd`。
- 当下一步需要符号信息或调试会话时，将成功构建结果交给 `debug-gdb-openocd`。
