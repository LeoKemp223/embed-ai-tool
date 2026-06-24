#!/usr/bin/env python3
"""SEGGER J-Link 烧录工具。

为 `flash-jlink` skill 提供可重复调用的执行入口，支持：

- 探测 JLinkExe 环境和已连接设备
- 扫描工作区中的 J-Link 配置线索
- 生成 J-Link Commander 脚本并执行烧录
- 支持 ELF/HEX/BIN 烧录和 RTT 日志捕获
- 输出结构化的烧录结果报告
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _SCRIPT_DIR.parent.parent
for _candidate in [_SKILLS_DIR / "shared", _SKILLS_DIR.parent / "shared"]:
    if (_candidate / "tool_config.py").exists():
        sys.path.insert(0, str(_candidate))
        break
from tool_config import get_tool_path, set_tool_path
from profile_store import (
    add_profile_args,
    handle_profile_actions,
    print_resume_hint,
    resume_profile,
    resolve_profile_workspace,
    save_profile,
    update_project_profile,
)


ARTIFACT_EXTENSIONS = {".elf": "elf", ".hex": "hex", ".bin": "bin", ".axf": "elf"}
SKILL_NAME = "flash-jlink"
ARTIFACT_PRIORITY = {"elf": 1, "hex": 2, "bin": 3}


@dataclass
class FlashResult:
    status: str  # success, failure, blocked
    summary: str
    command: str | None = None
    device: str | None = None
    interface: str | None = None
    speed: int | None = None
    artifact_path: str | None = None
    artifact_kind: str | None = None
    verified: bool = False
    failure_category: str | None = None
    evidence: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# JLinkExe 探测
# ---------------------------------------------------------------------------

def _jlink_exe_candidates(workspace: str | Path | None = None) -> list[str]:
    candidates = []
    configured = get_tool_path("jlink", workspace)
    if configured:
        candidates.append(configured)

    if platform.system() == "Windows":
        candidates.append("JLink.exe")
        for prog_dir in [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]:
            if prog_dir:
                candidates.append(str(Path(prog_dir) / "SEGGER" / "JLink" / "JLink.exe"))
    else:
        candidates.append("JLinkExe")
        candidates.append("/opt/SEGGER/JLink/JLinkExe")

    return candidates


def find_jlink_exe(workspace: str | Path | None = None) -> str | None:
    for candidate in _jlink_exe_candidates(workspace):
        path = shutil.which(candidate)
        if path:
            return path
        if Path(candidate).is_file():
            return candidate
    return None


def check_jlink(workspace: str | Path | None = None) -> tuple[bool, str | None, str | None]:
    jlink = find_jlink_exe(workspace)
    if not jlink:
        return False, None, None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jlink", delete=False, encoding="utf-8",
        ) as f:
            f.write("exit\n")
            script_path = f.name

        result = subprocess.run(
            [jlink, "-CommandFile", script_path],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout + "\n" + result.stderr
        version = None
        for line in output.split("\n"):
            if "SEGGER J-Link" in line and ("V" in line or "v" in line):
                version = line.strip()
                break
        return True, jlink, version
    except Exception:
        return True, jlink, None
    finally:
        Path(script_path).unlink(missing_ok=True)


def detect_connected_devices(jlink: str) -> list[str]:
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jlink", delete=False, encoding="utf-8",
        ) as f:
            f.write("ShowEmuList\nexit\n")
            script_path = f.name

        result = subprocess.run(
            [jlink, "-CommandFile", script_path],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout + "\n" + result.stderr
        devices = []
        for line in output.split("\n"):
            line = line.strip()
            if re.match(r"J-Link\[", line) or "Serial number" in line or "S/N" in line:
                devices.append(line)
        return devices
    except Exception:
        return []
    finally:
        Path(script_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 产物验证
# ---------------------------------------------------------------------------

def identify_artifact(artifact_path: str) -> tuple[str | None, int]:
    p = Path(artifact_path)
    if not p.exists():
        return None, 0
    ext = p.suffix.lower()
    kind = ARTIFACT_EXTENSIONS.get(ext)
    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    return kind, size


# ---------------------------------------------------------------------------
# 工作区配置扫描
# ---------------------------------------------------------------------------

def scan_jlink_configs(workspace: Path) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    for root, _dirs, files in os.walk(workspace):
        depth = str(root).replace(str(workspace), "").count(os.sep)
        if depth > 3:
            continue
        for fname in files:
            if fname.endswith(".jlink"):
                fpath = Path(root) / fname
                results.append({"source": "jlink-script", "path": str(fpath)})

    launch_json = workspace / ".vscode" / "launch.json"
    if launch_json.exists():
        try:
            data = json.loads(launch_json.read_text(encoding="utf-8", errors="ignore"))
            for config in data.get("configurations", []):
                server_type = config.get("servertype", "")
                device = config.get("device", "")
                if server_type == "jlink" or "jlink" in str(config).lower():
                    info = f"device={device}" if device else "J-Link config"
                    results.append({"source": "launch.json", "path": info})
        except Exception:
            pass

    return results


# ---------------------------------------------------------------------------
# 烧录命令组装与执行
# ---------------------------------------------------------------------------

def build_jlink_script(
    device: str,
    artifact: str,
    artifact_kind: str,
    interface: str,
    speed: int,
    base_address: str | None,
) -> str:
    artifact_posix = artifact.replace("\\", "/")
    lines = [
        f"si {interface}",
        f"speed {speed}",
        f"device {device}",
        "connect",
        f"loadfile {artifact_posix}" + (f" {base_address}" if artifact_kind == "bin" and base_address else ""),
        "verifybin" if artifact_kind == "bin" and base_address else "verify",
        "r",
        "go",
        "exit",
    ]
    return "\n".join(lines) + "\n"


def run_flash(jlink: str, script_content: str, verbose: bool) -> tuple[bool, list[str]]:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jlink", delete=False, encoding="utf-8",
    ) as f:
        f.write(script_content)
        script_path = f.name

    cmd = [jlink, "-CommandFile", script_path]
    cmd_str = " ".join(cmd)
    print(f"⚡ 烧录命令: {cmd_str}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, ["❌ J-Link 烧录超时（60 秒）"]
    except FileNotFoundError:
        return False, [f"❌ 未找到 JLinkExe: {jlink}"]
    finally:
        Path(script_path).unlink(missing_ok=True)

    combined = result.stdout + "\n" + result.stderr
    evidence: list[str] = []

    if verbose:
        for line in combined.strip().split("\n")[-30:]:
            if line.strip():
                evidence.append(line.strip())

    combined_lower = combined.lower()
    if "o.k." in combined_lower or ("verified" in combined_lower and "error" not in combined_lower):
        print("✅ 烧录成功，校验通过")
        return True, evidence

    if result.returncode == 0 and "error" not in combined_lower:
        print("✅ 烧录成功")
        return True, evidence

    last_lines = combined.strip().split("\n")[-15:]
    evidence.extend(last_lines)

    if "could not find" in combined_lower or "no j-link" in combined_lower:
        evidence.insert(0, "failure_hint: connection-failure (J-Link 探针未连接)")
    elif "unknown device" in combined_lower or "unknown command" in combined_lower:
        evidence.insert(0, "failure_hint: project-config-error (设备名无效)")
    elif "failed to" in combined_lower:
        evidence.insert(0, "failure_hint: target-response-abnormal")

    return False, evidence


# ---------------------------------------------------------------------------
# RTT 日志捕获
# ---------------------------------------------------------------------------

def run_rtt(jlink: str, device: str, interface: str, speed: int, duration: int) -> list[str]:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jlink", delete=False, encoding="utf-8",
    ) as f:
        f.write(f"si {interface}\nspeed {speed}\ndevice {device}\nconnect\n")
        f.write("r\ngo\n")
        f.write("JTAGConf -1,-1\n")
        f.write("exec SetRTTAddr 0\n")
        f.write("exec SetRTTSearchRanges 0x20000000 0x10000\n")
        script_path = f.name

    print(f"📡 启动 RTT 日志捕获（{duration} 秒）...")
    try:
        result = subprocess.run(
            [jlink, "-CommandFile", script_path],
            capture_output=True, text=True, timeout=duration + 10,
        )
        output = result.stdout + "\n" + result.stderr
        rtt_lines = []
        for line in output.split("\n"):
            line = line.strip()
            if line and not line.startswith("J-Link") and not line.startswith("SEGGER"):
                rtt_lines.append(line)
        return rtt_lines
    except subprocess.TimeoutExpired:
        return ["RTT 捕获超时"]
    except Exception as e:
        return [f"RTT 捕获失败: {e}"]
    finally:
        Path(script_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------

def print_detect_report(available: bool, jlink: str | None, version: str | None, devices: list[str]) -> None:
    print("\n📊 J-Link 环境探测结果：")
    status = "✅" if available else "❌"
    ver = f" ({version})" if version else ""
    path = f" @ {jlink}" if jlink else ""
    print(f"  {status} JLinkExe{ver}{path}")

    if devices:
        print(f"\n  已连接设备:")
        for d in devices:
            print(f"    - {d}")
    elif available:
        print("\n  ⚠️ 未检测到已连接的 J-Link 设备")


def print_flash_report(result: FlashResult) -> None:
    icon = {"success": "✅", "failure": "❌", "blocked": "⚠️"}.get(result.status, "❓")
    print(f"\n📊 烧录结果: {icon} {result.summary}")

    if result.command:
        print(f"\n  烧录命令:   {result.command}")
    if result.device:
        print(f"  目标设备:   {result.device}")
    if result.interface:
        print(f"  调试接口:   {result.interface}")
    if result.speed:
        print(f"  烧录速度:   {result.speed} kHz")
    if result.artifact_path:
        print(f"  固件产物:   {result.artifact_path} [{result.artifact_kind or '?'}]")
    print(f"  校验: {'是' if result.verified else '否'}")

    if result.evidence:
        print("\n📝 证据:")
        for line in result.evidence[:15]:
            print(f"  {line}")

    if result.failure_category:
        print(f"\n  失败分类: {result.failure_category}")


def print_scan_report(configs: list[dict[str, str]]) -> None:
    if not configs:
        print("❌ 未找到 J-Link 配置线索")
        return
    print(f"\n📋 找到 {len(configs)} 个 J-Link 配置线索：")
    for i, c in enumerate(configs, 1):
        print(f"  {i}. [{c['source']}] {c['path']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SEGGER J-Link 烧录工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --detect
  %(prog)s --scan-configs /repo/fw
  %(prog)s --artifact build/app.elf --device STM32F407VG
  %(prog)s --artifact build/app.hex --device STM32F103C8 --interface JTAG
  %(prog)s --artifact build/fw.bin --device STM32F407VG --base-address 0x08000000
  %(prog)s --rtt --device STM32F407VG
        """,
    )
    parser.add_argument("--detect", action="store_true", help="探测 J-Link 环境和已连接设备")
    parser.add_argument("--artifact", help="固件产物路径")
    parser.add_argument("--device", help="目标芯片型号（如 STM32F407VG）")
    parser.add_argument("--interface", choices=["SWD", "JTAG"], default="SWD", help="调试接口（默认 SWD）")
    parser.add_argument("--speed", type=int, default=4000, help="烧录速度 kHz（默认 4000）")
    parser.add_argument("--base-address", help="BIN 文件烧录基地址（十六进制）")
    parser.add_argument("--scan-configs", help="扫描指定目录中的 J-Link 配置线索")
    parser.add_argument("--rtt", action="store_true", help="启动 RTT 日志捕获")
    parser.add_argument("--rtt-duration", type=int, default=10, help="RTT 捕获时长（秒，默认 10）")
    parser.add_argument("--save-config", action="store_true", help="探测成功后保存工具路径到配置")
    add_profile_args(parser)
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    profile_workspace = resolve_profile_workspace(args, __file__)
    handle_profile_actions(args, profile_workspace, SKILL_NAME)
    resume_profile(args, profile_workspace, SKILL_NAME, {"artifact": "artifact", "device": "device", "interface": "interface", "speed": "speed", "base_address": "base_address"})

    # 探测模式
    if args.detect:
        available, jlink, version = check_jlink(profile_workspace)
        devices = detect_connected_devices(jlink) if available and jlink else []
        print_detect_report(available, jlink, version, devices)
        if args.save_config and available and jlink:
            cfg_path = set_tool_path("jlink", jlink, workspace=profile_workspace)
            print(f"  💾 已保存到 {cfg_path}")
        return 0 if available else 1

    # 扫描配置模式
    if args.scan_configs:
        configs = scan_jlink_configs(Path(args.scan_configs).resolve())
        print_scan_report(configs)
        return 0 if configs else 1

    # RTT 模式
    if args.rtt:
        if not args.device:
            print("❌ RTT 模式需要 --device 参数。")
            return 1
        jlink = find_jlink_exe(profile_workspace)
        if not jlink:
            print("❌ 未找到 JLinkExe，请先安装 SEGGER J-Link。")
            return 1
        rtt_output = run_rtt(jlink, args.device, args.interface, args.speed, args.rtt_duration)
        print("\n📡 RTT 输出:")
        for line in rtt_output:
            print(f"  {line}")
        return 0

    # 烧录模式
    if not args.artifact:
        print("❌ 请提供 --artifact（固件产物路径）。")
        return 1

    if not args.device:
        print("❌ J-Link 烧录需要 --device 参数（如 STM32F407VG）。")
        print("   J-Link Commander 需要明确的设备名，无法安全推断。")
        result = FlashResult(
            status="blocked",
            summary="缺少设备名（--device）",
            artifact_path=args.artifact,
            failure_category="ambiguous-context",
        )
        print_flash_report(result)
        return 1

    # 检查 JLinkExe
    jlink = find_jlink_exe(profile_workspace)
    if not jlink:
        print("❌ 未找到 JLinkExe，请先安装 SEGGER J-Link。")
        return 1

    # 验证产物
    artifact_path = str(Path(args.artifact).resolve())
    kind, size = identify_artifact(artifact_path)
    if kind is None:
        print(f"❌ 产物不存在或类型无法识别: {artifact_path}")
        return 1
    print(f"📦 固件产物: {artifact_path} [{kind.upper()}, {size / 1024:.1f} KB]")

    # BIN 需要基地址
    if kind == "bin" and not args.base_address:
        print("❌ BIN 文件必须提供 --base-address（烧录基地址）。")
        result = FlashResult(
            status="blocked",
            summary="BIN 文件缺少烧录基地址",
            artifact_path=artifact_path,
            artifact_kind=kind,
            failure_category="artifact-missing",
        )
        print_flash_report(result)
        return 1

    # 生成 J-Link 脚本
    script = build_jlink_script(
        device=args.device,
        artifact=artifact_path,
        artifact_kind=kind,
        interface=args.interface,
        speed=args.speed,
        base_address=args.base_address,
    )

    # 执行烧录
    ok, evidence = run_flash(jlink, script, verbose=args.verbose)

    failure_category = None
    if not ok:
        for line in evidence:
            if "connection-failure" in line:
                failure_category = "connection-failure"
                break
            if "project-config-error" in line:
                failure_category = "project-config-error"
                break
            if "target-response-abnormal" in line:
                failure_category = "target-response-abnormal"
                break
        if not failure_category:
            failure_category = "connection-failure"

    result = FlashResult(
        status="success" if ok else "failure",
        summary="烧录成功" if ok else "烧录失败",
        command=f"{jlink} -CommandFile <script>",
        device=args.device,
        interface=args.interface,
        speed=args.speed,
        artifact_path=artifact_path,
        artifact_kind=kind,
        verified=ok,
        failure_category=failure_category,
        evidence=evidence,
    )
    print_flash_report(result)
    if ok and not args.no_save_profile:
        set_tool_path("jlink", jlink, workspace=profile_workspace)
        update_project_profile(profile_workspace, {
            "artifact_path": artifact_path,
            "artifact_kind": kind,
            "probe": "jlink",
            "target_mcu": args.device,
            "jlink_device": args.device,
            "jlink_interface": args.interface,
            "jlink_speed": args.speed,
            "jlink_path": jlink,
            "base_address": args.base_address,
        })
        cfg_path = save_profile(profile_workspace, SKILL_NAME, args.profile, {
            "artifact": artifact_path,
            "artifact_kind": kind,
            "device": args.device,
            "interface": args.interface,
            "speed": args.speed,
            "base_address": args.base_address,
            "jlink_path": jlink,
        })
        print_resume_hint(__file__, cfg_path, SKILL_NAME, args.profile)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
