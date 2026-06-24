#!/usr/bin/env python
"""Keil MDK 命令行烧录工具。

为 `flash-keil` skill 提供可重复调用的执行入口，支持：

- 探测 Keil MDK 安装路径和 UV4.exe
- 解析工程文件中的调试器和 Flash 配置
- 通过 UV4.exe -f 命令行执行 Flash Download
- 解析烧录日志，判断成功/失败
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
elif sys.stdout:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
elif sys.stderr:
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _SCRIPT_DIR.parent.parent
for _candidate in [_SKILLS_DIR / "shared", _SKILLS_DIR.parent / "shared"]:
    if (_candidate / "tool_config.py").exists():
        sys.path.insert(0, str(_candidate))
        break

# 复用 build-keil 的核心函数
_BUILD_KEIL_SCRIPTS = _SKILLS_DIR / "build-keil" / "scripts"
if _BUILD_KEIL_SCRIPTS.is_dir():
    sys.path.insert(0, str(_BUILD_KEIL_SCRIPTS))

from keil_builder import find_uv4, detect_environment, parse_project, is_windows
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

SKILL_NAME = "flash-keil"
try:
    import xml.etree.ElementTree as ET
except ImportError:
    ET = None  # type: ignore[assignment,misc]

DRIVER_MAP = {
    "4101": "ST-Link",
    "4100": "ST-Link",
    "8010": "J-Link",
    "8001": "J-Link",
    "5530": "CMSIS-DAP",
    "5500": "CMSIS-DAP",
    "0": "ULINK",
}


@dataclass
class FlashResult:
    status: str  # success, failure
    summary: str
    flash_cmd: str | None = None
    project_file: str | None = None
    target_name: str | None = None
    device: str | None = None
    debugger: str | None = None
    artifact_path: str | None = None
    artifact_size: int | None = None
    flash_time: str | None = None
    failure_category: str | None = None
    evidence: list[str] = field(default_factory=list)


def parse_debugger_config(project_path: Path, target_name: str | None = None) -> str | None:
    if ET is None:
        return None
    try:
        tree = ET.parse(project_path)
    except ET.ParseError:
        return None

    for target_elem in tree.getroot().iter("Target"):
        name_elem = target_elem.find("TargetName")
        if target_name and name_elem is not None and name_elem.text:
            if name_elem.text.strip() != target_name:
                continue
        driver_elem = target_elem.find(".//DriverSelection")
        if driver_elem is not None and driver_elem.text:
            code = driver_elem.text.strip()
            return DRIVER_MAP.get(code, f"Unknown({code})")
    return None


def parse_flash_log(log_path: Path) -> tuple[bool, list[str], str | None, str | None]:
    """解析烧录日志，返回 (success, evidence, loaded_file, flash_time)"""
    if not log_path.exists():
        return False, ["烧录日志文件不存在"], None, None

    try:
        for encoding in ["utf-8", "gbk", "latin-1"]:
            try:
                content = log_path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            return False, ["(日志编码无法识别)"], None, None
    except OSError:
        return False, ["无法读取日志文件"], None, None

    evidence: list[str] = []
    has_error = False
    success = False
    loaded_file: str | None = None
    flash_time: str | None = None

    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        evidence.append(stripped)
        if "error" in stripped.lower():
            has_error = True
        if "flash download failed" in stripped.lower():
            has_error = True
        if "application running" in stripped.lower():
            success = True
        if "flash load finished" in stripped.lower():
            success = True
            time_match = re.search(r"at\s+(\S+)", stripped)
            if time_match:
                flash_time = time_match.group(1)
        load_match = re.match(r'Load\s+"(.+)"', stripped)
        if load_match:
            loaded_file = load_match.group(1)

    summary_match = re.search(r"(\d+)\s+Error\(s\)", content)
    if summary_match and int(summary_match.group(1)) > 0:
        has_error = True
    if summary_match and int(summary_match.group(1)) == 0:
        success = True

    return (success and not has_error), evidence, loaded_file, flash_time


def run_keil_flash(
    uv4_path: str,
    project_path: Path,
    target_name: str,
    log_path: Path,
) -> FlashResult:
    cmd = [uv4_path, "-f", str(project_path), "-t", target_name, "-o", str(log_path)]
    cmd_str = " ".join(cmd)
    print(f"🔥 烧录命令: {cmd_str}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return FlashResult("failure", "烧录超时（120 秒）", cmd_str,
                           failure_category="connection-failure",
                           evidence=["❌ UV4 烧录超时"])
    except FileNotFoundError:
        return FlashResult("failure", f"未找到 UV4: {uv4_path}", cmd_str,
                           failure_category="environment-missing",
                           evidence=[f"❌ 未找到 UV4: {uv4_path}"])

    ok, evidence, loaded_file, flash_time = parse_flash_log(log_path)

    artifact_path = None
    artifact_size = None
    if loaded_file:
        candidate = project_path.parent / loaded_file
        if candidate.exists():
            artifact_path = str(candidate.resolve())
            try:
                artifact_size = candidate.stat().st_size
            except OSError:
                pass

    if result.returncode <= 1 and ok:
        print("✅ 烧录成功")
        return FlashResult("success", "烧录成功", cmd_str,
                           artifact_path=artifact_path, artifact_size=artifact_size,
                           flash_time=flash_time, evidence=evidence)

    evidence.insert(0, f"UV4 返回码: {result.returncode}")
    category = "connection-failure" if result.returncode >= 2 else "project-config-error"
    return FlashResult("failure", "烧录失败", cmd_str,
                       failure_category=category,
                       artifact_path=artifact_path, artifact_size=artifact_size,
                       flash_time=flash_time, evidence=evidence)

def print_detect_report(env: dict[str, Any], debugger: str | None = None) -> None:
    print("\n📊 Keil MDK 烧录环境探测：")
    print(f"  平台: {env['platform']}")
    uv4 = env["uv4"]
    status = "✅" if uv4["available"] else "❌"
    path = f" @ {uv4['path']}" if uv4.get("path") else ""
    print(f"  {status} UV4.exe{path}")
    if debugger:
        print(f"  🔌 工程调试器: {debugger}")
    if not env["is_windows"]:
        print("\n  ⚠️ Keil MDK 烧录仅在 Windows 上支持")


def print_flash_report(result: FlashResult) -> None:
    icon = "✅" if result.status == "success" else "❌"
    print(f"\n📊 烧录结果: {icon} {result.summary}")
    if result.flash_cmd:
        print(f"\n  烧录命令:   {result.flash_cmd}")
    if result.project_file:
        print(f"  工程文件:   {result.project_file}")
    if result.target_name:
        print(f"  目标:       {result.target_name}")
    if result.device:
        print(f"  芯片:       {result.device}")
    if result.debugger:
        print(f"  调试器:     {result.debugger}")
    if result.artifact_path:
        size_str = ""
        if result.artifact_size:
            size_str = f" ({result.artifact_size / 1024:.1f} KB)"
        print(f"  烧录固件:   {result.artifact_path}{size_str}")
    if result.flash_time:
        print(f"  完成时间:   {result.flash_time}")
    if result.failure_category:
        print(f"  失败分类:   {result.failure_category}")
    if result.evidence:
        print("\n📝 日志:")
        for line in result.evidence[:15]:
            print(f"  {line}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Keil MDK 命令行烧录工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --detect
  %(prog)s --detect --project app.uvprojx
  %(prog)s --flash --project app.uvprojx --target Debug
        """,
    )
    parser.add_argument("--detect", action="store_true",
                        help="探测 Keil MDK 烧录环境（可与 --project 组合）")
    parser.add_argument("--flash", action="store_true", help="执行烧录")
    parser.add_argument("--project", help=".uvprojx 或 .uvproj 工程文件路径")
    parser.add_argument("--target", help="构建目标名称")
    parser.add_argument("--uv4", help="显式指定 UV4.exe 路径")
    parser.add_argument("--save-config", action="store_true", help="保存工具路径到配置")
    parser.add_argument("--log", help="烧录日志输出路径")
    add_profile_args(parser)
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    profile_workspace = resolve_profile_workspace(args, __file__)
    handle_profile_actions(args, profile_workspace, SKILL_NAME)
    resume_profile(args, profile_workspace, SKILL_NAME, {"project": "project", "target": "target", "uv4": "uv4"})

    if not args.detect and not args.flash:
        if args.project:
            args.flash = True
        else:
            print("❌ 请指定 --detect 或 --flash。")
            return 1

    if args.detect:
        env = detect_environment(args.uv4, profile_workspace)
        debugger = None
        if args.project:
            project_path = Path(args.project).resolve()
            if project_path.exists():
                debugger = parse_debugger_config(project_path, args.target)
        print_detect_report(env, debugger)
        if args.save_config and env["uv4"]["available"]:
            cfg_path = set_tool_path("uv4", env["uv4"]["path"], workspace=profile_workspace)
            print(f"  💾 已保存到 {cfg_path}")
        if not env["uv4"]["available"]:
            return 1
        if not args.flash:
            return 0

    if not args.project:
        print("❌ 请提供 --project（Keil 工程文件路径）。")
        return 1

    project_path = Path(args.project).resolve()
    if not project_path.exists():
        print(f"❌ 工程文件不存在: {project_path}")
        return 1

    targets = parse_project(project_path)
    if not targets:
        print(f"❌ 未能从工程文件中解析出目标: {project_path}")
        return 1

    selected = None
    if args.target:
        for t in targets:
            if t.name == args.target:
                selected = t
                break
        if not selected:
            print(f"❌ 未找到目标 '{args.target}'，可用目标：")
            for t in targets:
                print(f"  - {t.name}")
            return 1
    else:
        selected = targets[0]
        if len(targets) > 1:
            print(f"ℹ️ 未指定目标，默认使用: {selected.name}")

    debugger = parse_debugger_config(project_path, selected.name)
    print(f"📦 目标: {selected.name} ({selected.device})")
    if debugger:
        print(f"🔌 调试器: {debugger}")

    uv4_path = find_uv4(args.uv4, profile_workspace)
    if not uv4_path:
        if not is_windows():
            print("❌ Keil MDK 烧录仅在 Windows 上支持。")
        else:
            print("❌ 未找到 UV4.exe，请安装 Keil MDK 或通过 --uv4 指定路径。")
        return 1

    log_path = Path(args.log) if args.log else project_path.parent / f"{selected.name}_flash.log"

    flash_result = run_keil_flash(uv4_path, project_path, selected.name, log_path)
    flash_result.project_file = str(project_path)
    flash_result.target_name = selected.name
    flash_result.device = selected.device
    flash_result.debugger = debugger

    print_flash_report(flash_result)
    if flash_result.status == "success" and not args.no_save_profile:
        set_tool_path("uv4", uv4_path, workspace=profile_workspace)
        probe = debugger.lower().replace("-", "").replace(" ", "-") if debugger else None
        update_project_profile(profile_workspace, {
            "build_system": "keil",
            "project_file": str(project_path),
            "target": selected.name,
            "target_mcu": selected.device,
            "probe": probe,
            "debugger": debugger,
            "uv4_path": uv4_path,
            "artifact_path": flash_result.artifact_path,
        })
        cfg_path = save_profile(profile_workspace, SKILL_NAME, args.profile, {
            "project": str(project_path),
            "target": selected.name,
            "uv4": uv4_path,
            "uv4_path": uv4_path,
            "artifact_path": flash_result.artifact_path,
            "device": selected.device,
            "debugger": debugger,
        })
        print_resume_hint(__file__, cfg_path, SKILL_NAME, args.profile, "--flash")
    return 0 if flash_result.status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
