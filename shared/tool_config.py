"""轻量工具路径持久化配置层。

提供 JSON 配置文件的读写，支持工作区级（.em_skill.json）和全局级
（~/.config/em_skill/config.json）两层配置，工作区覆盖全局。

解析优先级（由各脚本自行实现）：
  CLI 参数 → 配置文件 → 环境变量 → 硬编码路径 → PATH
"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any

CONFIG_FILENAME = ".em_skill.json"


def user_config_path() -> Path:
    """返回全局配置文件路径（XDG / APPDATA）。"""
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "em_skill" / "config.json"
    # XDG_CONFIG_HOME 或 ~/.config
    base = os.environ.get("XDG_CONFIG_HOME", "")
    if not base:
        base = str(Path.home() / ".config")
    return Path(base) / "em_skill" / "config.json"


def workspace_config_path(workspace: str | Path | None = None) -> Path:
    """返回工作区级配置文件路径。"""
    ws = Path(workspace) if workspace else Path.cwd()
    return ws / CONFIG_FILENAME


def load_config(path: Path) -> dict[str, Any]:
    """读取 JSON 配置文件，文件不存在或格式错误时返回空字典。"""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(path: Path, data: dict[str, Any]) -> None:
    """将配置写入 JSON 文件，自动创建父目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def get_tool_path(
    tool_name: str,
    workspace: str | Path | None = None,
) -> str | None:
    """合并读取工具路径（工作区优先于全局）。"""
    # 工作区级
    ws_cfg = load_config(workspace_config_path(workspace))
    ws_path = ws_cfg.get("tools", {}).get(tool_name)
    if ws_path:
        return ws_path

    # 全局级
    global_cfg = load_config(user_config_path())
    return global_cfg.get("tools", {}).get(tool_name)


def set_tool_path(
    tool_name: str,
    tool_path: str,
    workspace: str | Path | None = None,
    global_: bool = False,
) -> Path:
    """写入工具路径到指定级别的配置文件，返回写入的文件路径。"""
    cfg_path = user_config_path() if global_ else workspace_config_path(workspace)
    data = load_config(cfg_path)
    tools = data.setdefault("tools", {})
    tools[tool_name] = tool_path
    save_config(cfg_path, data)
    return cfg_path


def remove_tool_path(
    tool_name: str,
    workspace: str | Path | None = None,
    global_: bool = False,
) -> bool:
    """从配置中删除工具路径，返回是否实际删除了条目。"""
    cfg_path = user_config_path() if global_ else workspace_config_path(workspace)
    data = load_config(cfg_path)
    tools = data.get("tools", {})
    if tool_name not in tools:
        return False
    del tools[tool_name]
    save_config(cfg_path, data)
    return True


def list_tools(
    workspace: str | Path | None = None,
) -> dict[str, dict[str, str]]:
    """列出所有已配置的工具，返回 {tool_name: {"path": ..., "source": ...}}。"""
    result: dict[str, dict[str, str]] = {}

    global_cfg = load_config(user_config_path())
    for name, path in global_cfg.get("tools", {}).items():
        result[name] = {"path": path, "source": "global"}

    ws_cfg = load_config(workspace_config_path(workspace))
    for name, path in ws_cfg.get("tools", {}).items():
        result[name] = {"path": path, "source": "workspace"}

    return result


def find_sdk_bundled_openocd_scripts() -> str | None:
    """探测嵌入式 SDK 自带的 OpenOCD scripts 目录。
    
    部分 SDK（如 Raspberry Pi Pico SDK、PlatformIO 等）会安装
    自己的 OpenOCD，包含芯片特定目标配置文件（系统 OpenOCD 可能没有）。
    返回 scripts 目录路径，找不到返回 None。
    
    跨平台：Windows 用 openocd.exe，macOS/Linux 用 bin/openocd。
    """
    import sys as _sys
    sdk_dir = Path.home() / ".pico-sdk" / "openocd"
    if not sdk_dir.exists():
        return None
    for version_dir in sorted(sdk_dir.iterdir(), reverse=True):
        if not version_dir.is_dir():
            continue
        # Binaries can be in root (Windows) or bin/ (Unix)
        ocd = version_dir / "openocd.exe" if _sys.platform == "win32" else version_dir / "bin" / "openocd"
        if not ocd.exists() and _sys.platform != "win32":
            ocd = version_dir / "openocd"
        if not ocd.exists():
            continue
        scripts = version_dir / "scripts"
        if scripts.is_dir():
            return str(scripts)
    return None
