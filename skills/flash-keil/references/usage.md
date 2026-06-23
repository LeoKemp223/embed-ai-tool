# Keil MDK 烧录 Skill 用法

这个 skill 自带了一个可执行脚本 [scripts/keil_flasher.py](../scripts/keil_flasher.py)，通过 Keil MDK 的 UV4.exe 命令行接口执行 Flash Download，利用工程中已配置的调试器和 Flash 算法烧录固件。

## 能力概览

- 探测 Keil MDK 安装路径和 UV4.exe
- 解析工程文件中的调试器配置（ST-Link、J-Link、CMSIS-DAP、ULINK）
- 通过 `UV4.exe -f` 执行 Flash Download
- 解析烧录日志，判断成功/失败
- 输出结构化的烧录结果报告

## 基础用法

```bash
# 探测烧录环境
python skills/flash-keil/scripts/keil_flasher.py --detect

# 探测环境 + 查看工程调试器配置
python skills/flash-keil/scripts/keil_flasher.py --detect --project path/to/app.uvprojx

# 烧录默认目标
python skills/flash-keil/scripts/keil_flasher.py --flash --project path/to/app.uvprojx

# 烧录指定目标
python skills/flash-keil/scripts/keil_flasher.py --flash --project path/to/app.uvprojx --target "Debug"

# 一次完成探测 + 烧录（推荐）
python skills/flash-keil/scripts/keil_flasher.py --detect --flash --project path/to/app.uvprojx --target "Debug"
```

## 新会话恢复

```bash
python3 skills/flash-keil/scripts/keil_flasher.py --flash --resume
```

成功烧录后缓存工程文件、target、UV4 路径、debugger 和 device；脚本启动即自动复用这些缓存参数（显式参数优先）；无缓存或缓存失效时自动回退，例如 detect。

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `--detect` | 探测 Keil MDK 烧录环境（可与 --flash 组合） |
| `--flash` | 执行烧录 |
| `--project` | `.uvprojx` 或 `.uvproj` 工程文件路径 |
| `--target` | 构建目标名称 |
| `--uv4` | 显式指定 UV4.exe 路径 |
| `--save-config` | 探测成功后保存工具路径到配置 |
| `--log` | 烧录日志输出路径 |
| `--resume` | 从工程根目录 `.em_skill.json` 的缓存 profile 恢复上次成功参数 |
| `--profile` | 指定缓存 profile 名，默认 `default` |
| `--workspace` | 指定工程根目录，profile 固定读写该目录下的 `.em_skill.json` |
| `--show-profile` | 输出当前缓存 profile 并退出 |
| `--clear-profile` | 删除当前缓存 profile 并退出 |
| `--no-save-profile` | 成功后不更新缓存 profile |
| `-v`, `--verbose` | 详细输出 |

## 返回码

- `0`：烧录成功或探测成功
- `1`：参数非法、Keil 未安装、工程文件无效、烧录失败

## 与 build-keil 的配合

推荐工作流：

1. 用 `build-keil` 编译工程，确认编译成功
2. 用 `flash-keil` 烧录同一工程的同一目标
3. 烧录成功后用 `serial-monitor` 查看串口输出

```bash
# 编译
python skills/build-keil/scripts/keil_builder.py --detect --project app.uvprojx --target Debug

# 烧录
python skills/flash-keil/scripts/keil_flasher.py --flash --project app.uvprojx --target Debug
```

## 平台说明

Keil MDK 烧录仅在 Windows 上支持。烧录使用工程中已配置的调试器（在 Keil GUI 的 Options for Target → Debug 中设置），无需额外安装 OpenOCD 或其他工具。
