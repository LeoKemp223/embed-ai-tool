#!/usr/bin/env python
"""PlatformIO 烧录工具。

为 `flash-platformio` skill 提供可重复调用的执行入口，支持：

- 探测 PlatformIO 环境和已连接设备
- 解析 platformio.ini 中的上传配置
- 执行 pio run -t upload 烧录固件
- 输出结构化的烧录结果报告
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
_BUILD_PIO_SCRIPTS = _SKILLS_DIR / "build-platformio" / "scripts"
if _BUILD_PIO_SCRIPTS.is_dir():
    sys.path.insert(0, str(_BUILD_PIO_SCRIPTS))
for _candidate in [_SKILLS_DIR / "shared", _SKILLS_DIR.parent / "shared"]:
    if (_candidate / "tool_config.py").exists():
        sys.path.insert(0, str(_candidate))
        break

from platformio_builder import (
    find_pio, get_pio_version, detect_environment,
    parse_platformio_ini, PIOEnvironment,
    scan_artifacts, resolve_build_dir, run_pio_device_list,
)
from tool_config import set_tool_path
from profile_store import (
    add_profile_args,
    handle_profile_actions,
    print_resume_hint,
    resume_profile,
    resolve_profile_workspace,
    save_profile,
    update_project_profile,
)


SKILL_NAME = "flash-platformio"
@dataclass
class FlashResult:
    status: str  # success, failure, blocked
    summary: str
    command: str | None = None
    project_dir: str | None = None
    env_name: str | None = None
    board: str | None = None
    platform: str | None = None
    upload_protocol: str | None = None
    upload_port: str | None = None
    artifact_path: str | None = None
    failure_category: str | None = None
    evidence: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 烧录执行
# ---------------------------------------------------------------------------

def run_pio_upload(
    pio_path: str,
    project_dir: str,
    env_name: str,
    upload_port: str | None,
    verbose: bool,
) -> tuple[bool, str, list[str], float]:
    cmd = [pio_path, "run", "-d", project_dir, "-e", env_name, "-t", "upload"]
    if upload_port:
        cmd.extend(["--upload-port", upload_port])
    if verbose:
        cmd.append("-v")

    cmd_str = " ".join(cmd)
    print(f"⚡ 烧录命令: {cmd_str}")

    t0 = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, cmd_str, ["❌ 烧录超时（120 秒）"], time.time() - t0
    except FileNotFoundError:
        return False, cmd_str, [f"❌ 未找到 pio: {pio_path}"], 0
    elapsed = time.time() - t0

    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    evidence: list[str] = []

    if verbose:
        for line in combined.strip().split("\n")[-30:]:
            if line.strip():
                evidence.append(line.strip())

    if result.returncode == 0:
        print(f"✅ 烧录成功（耗时 {elapsed:.1f} 秒）")
        return True, cmd_str, evidence, elapsed

    last_lines = combined.strip().split("\n")[-15:]
    evidence.extend([l.strip() for l in last_lines if l.strip()])
    return False, cmd_str, evidence, elapsed


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------

def classify_failure(evidence: list[str]) -> str:
    for line in evidence:
        ll = line.lower()
        if any(kw in ll for kw in ["no device found", "could not open", "serial port", "permission denied"]):
            return "connection-failure"
        if any(kw in ll for kw in ["no such board", "unknown board", "invalid"]):
            return "project-config-error"
    return "upload-failure"


def print_detect_report(env: dict[str, Any], devices: str | None) -> None:
    print("\n📊 PlatformIO 烧录环境探测：")
    pio = env["pio"]
    status = "✅" if pio["available"] else "❌"
    ver = f" ({pio['version']})" if pio.get("version") else ""
    path = f" @ {pio['path']}" if pio.get("path") else ""
    print(f"  {status} pio{ver}{path}")
    if devices:
        print(f"\n  已连接设备:\n{devices}")


def print_flash_report(result: FlashResult) -> None:
    icon = {"success": "✅", "failure": "❌", "blocked": "⚠️"}.get(result.status, "❓")
    print(f"\n📊 烧录结果: {icon} {result.summary}")

    if result.command:
        print(f"\n  烧录命令:     {result.command}")
    if result.project_dir:
        print(f"  工程目录:     {result.project_dir}")
    if result.env_name:
        print(f"  环境:         {result.env_name}")
    if result.board:
        print(f"  板卡:         {result.board}")
    if result.platform:
        print(f"  平台:         {result.platform}")
    if result.upload_protocol:
        print(f"  上传协议:     {result.upload_protocol}")
    if result.upload_port:
        print(f"  上传端口:     {result.upload_port}")
    if result.artifact_path:
        print(f"  固件产物:     {result.artifact_path}")

    if result.evidence:
        print("\n📝 证据:")
        for line in result.evidence[:15]:
            print(f"  {line}")

    if result.failure_category:
        print(f"\n  失败分类: {result.failure_category}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PlatformIO 烧录工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--detect", action="store_true", help="探测 PlatformIO 环境和设备")
    parser.add_argument("--flash", action="store_true", help="执行烧录")
    parser.add_argument("--project-dir", help="PlatformIO 工程目录")
    parser.add_argument("--env", help="构建环境名称")
    parser.add_argument("--upload-port", help="上传端口（如 COM3、/dev/ttyUSB0）")
    parser.add_argument("--list-devices", action="store_true", help="列出已连接设备")
    parser.add_argument("--save-config", action="store_true", help="保存工具路径到配置")
    add_profile_args(parser)
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    profile_workspace = resolve_profile_workspace(args, __file__)
    handle_profile_actions(args, profile_workspace, SKILL_NAME)
    resume_profile(args, profile_workspace, SKILL_NAME, {"project_dir": "project_dir", "env": "env", "upload_port": "upload_port"})

    # 探测模式
    if args.detect:
        env = detect_environment(profile_workspace)
        pio_path = env["pio"]["path"]
        devices = run_pio_device_list(pio_path) if pio_path else None
        print_detect_report(env, devices)
        return 0 if env["pio"]["available"] else 1

    # 列出设备
    if args.list_devices:
        pio_path = find_pio(profile_workspace)
        if not pio_path:
            print("❌ 未找到 pio，请先安装 PlatformIO。")
            return 1
        devices = run_pio_device_list(pio_path)
        if devices:
            print(devices)
        else:
            print("未检测到已连接设备")
        return 0

    # 烧录模式
    if not args.flash:
        parser.print_help()
        return 1

    if not args.project_dir:
        print("❌ 请提供 --project-dir（PlatformIO 工程目录）。")
        return 1

    project_dir = Path(args.project_dir).resolve()
    if not (project_dir / "platformio.ini").exists():
        print(f"❌ 未找到 platformio.ini: {project_dir}")
        return 1

    pio_path = find_pio(profile_workspace)
    if not pio_path:
        print("❌ 未找到 pio，请先安装 PlatformIO。")
        return 1

    envs, default_envs = parse_platformio_ini(project_dir)
    if not envs:
        print("❌ platformio.ini 中未找到环境配置。")
        return 1

    env_name = args.env
    if not env_name:
        env_name = default_envs[0] if default_envs else envs[0].name
        print(f"ℹ️ 未指定环境，使用: {env_name}")

    env_info = next((e for e in envs if e.name == env_name), None)
    if not env_info:
        print(f"❌ 环境 '{env_name}' 不存在。可用: {', '.join(e.name for e in envs)}")
        return 1

    print(f"📦 环境: {env_name} [{env_info.board}] ({env_info.platform})")

    ok, cmd_str, evidence, elapsed = run_pio_upload(
        pio_path, str(project_dir), env_name, args.upload_port, args.verbose,
    )

    artifact_path = None
    build_dir = resolve_build_dir(project_dir, env_name)
    artifacts = scan_artifacts(build_dir)
    if artifacts:
        artifact_path = str(artifacts[0].path)

    failure_category = classify_failure(evidence) if not ok else None

    result = FlashResult(
        status="success" if ok else "failure",
        summary=f"烧录{'成功' if ok else '失败'}（耗时 {elapsed:.1f} 秒）",
        command=cmd_str,
        project_dir=str(project_dir),
        env_name=env_name,
        board=env_info.board,
        platform=env_info.platform,
        upload_protocol=env_info.upload_protocol or None,
        upload_port=args.upload_port,
        artifact_path=artifact_path,
        failure_category=failure_category,
        evidence=evidence,
    )
    print_flash_report(result)
    if ok and not args.no_save_profile:
        set_tool_path("pio", pio_path, workspace=profile_workspace)
        upload_protocol = env_info.upload_protocol or None
        probe = upload_protocol if upload_protocol in {"jlink", "stlink", "cmsis-dap", "daplink"} else None
        update_project_profile(profile_workspace, {
            "build_system": "platformio",
            "project_dir": str(project_dir),
            "target": env_name,
            "board": env_info.board,
            "platform": env_info.platform,
            "probe": probe,
            "upload_protocol": upload_protocol,
            "upload_port": args.upload_port,
            "serial_port": args.upload_port,
            "artifact_path": artifact_path,
            "pio_path": pio_path,
        })
        cfg_path = save_profile(profile_workspace, SKILL_NAME, args.profile, {
            "project_dir": str(project_dir),
            "env": env_name,
            "pio_path": pio_path,
            "board": env_info.board,
            "platform": env_info.platform,
            "upload_protocol": env_info.upload_protocol or None,
            "upload_port": args.upload_port,
            "artifact_path": artifact_path,
        })
        print_resume_hint(__file__, cfg_path, SKILL_NAME, args.profile, "--flash")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
