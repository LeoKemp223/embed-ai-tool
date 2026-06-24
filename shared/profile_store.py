"""Small persistent profile helper for skill scripts.

Profiles are stored in the project-root ``.em_skill.json`` under:

    skill_profiles.<skill_name>.<profile_name>

The helper intentionally stays tiny. Scripts decide which fields are stable
enough to save and when a successful run should update the profile.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tool_config import load_config, save_config, workspace_config_path

PROFILE_SECTION = "skill_profiles"
PROJECT_PROFILE_SECTION = "project_profile"
DEFAULT_PROFILE = "default"


def add_profile_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Require a cached profile; cached profiles are otherwise reused automatically when present.",
    )
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="Profile name, default: default")
    parser.add_argument(
        "--workspace",
        help="Project root for .em_skill.json; defaults to the local skill install root or current directory",
    )
    parser.add_argument("--show-profile", action="store_true", help="Print the cached profile and exit")
    parser.add_argument("--clear-profile", action="store_true", help="Delete the cached profile and exit")
    parser.add_argument(
        "--no-save-profile",
        action="store_true",
        help="Do not update the cached profile after a successful run",
    )


def profile_name(name: str | None) -> str:
    return name or DEFAULT_PROFILE


def resolve_profile_workspace(
    args: argparse.Namespace,
    script_path: str | Path | None = None,
    fallback: str | Path | None = None,
) -> Path:
    """Return the project root that owns ``.em_skill.json``.

    Local project installs live under ``<project>/.claude/skills/...``. When a
    script is run from that layout, infer ``<project>`` automatically. Global
    installs and source-tree execution can use ``--workspace`` explicitly, or
    fall back to the current working directory.
    """
    explicit = getattr(args, "workspace", None)
    if explicit:
        return Path(explicit).resolve()

    if script_path:
        path = Path(script_path).resolve()
        for parent in path.parents:
            if parent.name == "skills" and parent.parent.name == ".claude":
                return parent.parent.parent.resolve()

    return Path(fallback).resolve() if fallback else Path.cwd().resolve()


def load_profile(workspace: str | Path, skill_name: str, name: str | None = None) -> dict[str, Any] | None:
    cfg = load_config(workspace_config_path(workspace))
    profile = cfg.get(PROFILE_SECTION, {}).get(skill_name, {}).get(profile_name(name))
    return profile if isinstance(profile, dict) else None


def save_profile(
    workspace: str | Path,
    skill_name: str,
    name: str | None,
    data: dict[str, Any],
) -> Path:
    cfg_path = workspace_config_path(workspace)
    cfg = load_config(cfg_path)
    skill_profiles = cfg.setdefault(PROFILE_SECTION, {}).setdefault(skill_name, {})
    payload = dict(data)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    skill_profiles[profile_name(name)] = payload
    save_config(cfg_path, cfg)
    return cfg_path


def update_project_profile(workspace: str | Path, data: dict[str, Any]) -> Path:
    """Merge stable cross-skill fields into ``.em_skill.json.project_profile``.

    ``skill_profiles`` remains the per-script resume cache. This helper keeps a
    single project-wide view for tools, probes, target chips, artifacts, and
    serial/debug settings that other skills can reuse without knowing which
    flash skill produced them.
    """
    cfg_path = workspace_config_path(workspace)
    cfg = load_config(cfg_path)
    profile = cfg.setdefault(PROJECT_PROFILE_SECTION, {})
    for key, value in data.items():
        if value is None:
            continue
        if value == [] or value == {}:
            continue
        profile[key] = value
    profile["workspace_root"] = str(Path(workspace).resolve())
    profile["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_config(cfg_path, cfg)
    return cfg_path


def clear_profile(workspace: str | Path, skill_name: str, name: str | None = None) -> bool:
    cfg_path = workspace_config_path(workspace)
    cfg = load_config(cfg_path)
    all_profiles = cfg.get(PROFILE_SECTION, {})
    skill_profiles = all_profiles.get(skill_name, {})
    key = profile_name(name)
    if key not in skill_profiles:
        return False
    del skill_profiles[key]
    if not skill_profiles:
        all_profiles.pop(skill_name, None)
    if not all_profiles:
        cfg.pop(PROFILE_SECTION, None)
    save_config(cfg_path, cfg)
    return True


def show_profile(workspace: str | Path, skill_name: str, name: str | None = None) -> int:
    profile = load_profile(workspace, skill_name, name)
    if not profile:
        print(f"No cached profile '{profile_name(name)}' for {skill_name} in {workspace_config_path(workspace)}")
        return 1
    print(json.dumps(profile, indent=2, ensure_ascii=False))
    return 0


def apply_profile_defaults(args: argparse.Namespace, profile: dict[str, Any], fields: dict[str, str] | list[str]) -> None:
    if isinstance(fields, list):
        pairs = [(field, field) for field in fields]
    else:
        pairs = list(fields.items())
    for attr, key in pairs:
        value = profile.get(key)
        if value is None:
            continue
        current = getattr(args, attr, None)
        if current in (None, "", []):
            setattr(args, attr, value)


def handle_profile_actions(args: argparse.Namespace, workspace: str | Path, skill_name: str) -> bool:
    if getattr(args, "show_profile", False):
        raise SystemExit(show_profile(workspace, skill_name, getattr(args, "profile", None)))
    if getattr(args, "clear_profile", False):
        removed = clear_profile(workspace, skill_name, getattr(args, "profile", None))
        print(
            f"Cleared profile '{profile_name(getattr(args, 'profile', None))}' for {skill_name}"
            if removed
            else f"No cached profile '{profile_name(getattr(args, 'profile', None))}' for {skill_name}"
        )
        raise SystemExit(0 if removed else 1)
    return False


def resume_profile(
    args: argparse.Namespace,
    workspace: str | Path,
    skill_name: str,
    fields: dict[str, str] | list[str],
) -> dict[str, Any] | None:
    """Apply a cached profile as default arg values on every invocation.

    Reading ``.em_skill.json`` is a code-level guarantee, not a prompt hint:
    a cached profile silently fills any args the caller left empty.
    ``--resume`` flips to strict mode: it requires a cache to exist and exits
    non-zero if none is found. With no cache and no ``--resume``, the function
    returns ``None`` and the caller proceeds normally.
    """
    cfg_path = workspace_config_path(workspace)
    profile = load_profile(workspace, skill_name, getattr(args, "profile", None))
    if not profile:
        if getattr(args, "resume", False):
            print(
                f"No cached profile '{profile_name(getattr(args, 'profile', None))}' "
                f"for {skill_name} in {cfg_path}"
            )
            raise SystemExit(1)
        return None
    apply_profile_defaults(args, profile, fields)
    print(f"Reusing profile '{profile_name(getattr(args, 'profile', None))}' for {skill_name} from {cfg_path}")
    return profile


def print_resume_hint(
    script_path: str | Path,
    cfg_path: Path,
    skill_name: str,
    name: str | None = None,
    action_args: list[str] | str | None = None,
) -> None:
    if isinstance(action_args, str):
        action = action_args
    elif action_args:
        action = " ".join(action_args)
    else:
        action = ""
    action_prefix = f"{action} " if action else ""
    print(f"\nSaved profile '{profile_name(name)}' for {skill_name} to {cfg_path}")
    print("Next session can run this first:")
    print(f"  python {Path(script_path).resolve()} {action_prefix}--resume --profile {profile_name(name)}")
