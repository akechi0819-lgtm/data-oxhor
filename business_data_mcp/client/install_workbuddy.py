#!/usr/bin/env python3
"""Install the packaged Business Data MCP connection and Skill for WorkBuddy."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional


class InstallError(Exception):
    """A safe, user-facing installation error."""


def _lexists(path: Path) -> bool:
    return os.path.lexists(str(path))


def _read_json_object(path: Path, missing_ok: bool = False) -> dict[str, Any]:
    if not _lexists(path):
        if missing_ok:
            return {}
        raise InstallError("打包文件 connection.json 不存在。")
    if path.is_symlink() or not path.is_file():
        raise InstallError("JSON 路径不是普通文件。")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        if missing_ok:
            raise InstallError("现有 mcp.json 无效，未覆盖任何配置。") from exc
        raise InstallError("打包文件 connection.json 无效。") from exc
    if not isinstance(value, dict):
        if missing_ok:
            raise InstallError("现有 mcp.json 顶层必须是 JSON 对象，未覆盖任何配置。")
        raise InstallError("打包文件 connection.json 顶层必须是 JSON 对象。")
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError("非标准 JSON 常量")


def _validate_package(package_dir: Path) -> tuple[dict[str, Any], bytes]:
    connection_path = package_dir / "connection.json"
    package = _read_json_object(connection_path)
    servers = package.get("mcpServers")
    if not isinstance(servers, dict) or not isinstance(servers.get("business-data"), dict):
        raise InstallError("connection.json 缺少 mcpServers.business-data 对象。")

    skill_dir = package_dir / "business-data-query"
    skill_path = skill_dir / "SKILL.md"
    if skill_dir.is_symlink() or not skill_dir.is_dir() or skill_path.is_symlink() or not skill_path.is_file():
        raise InstallError("打包的 business-data-query/SKILL.md 不存在或不是普通文件。")
    try:
        skill_bytes = skill_path.read_bytes()
    except OSError as exc:
        raise InstallError("无法读取打包的 Skill 文件。") from exc
    return servers["business-data"], skill_bytes


def _existing_config(config_path: Path) -> dict[str, Any]:
    existing = _read_json_object(config_path, missing_ok=True)
    servers = existing.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise InstallError("现有 mcp.json 的 mcpServers 必须是对象，未覆盖任何配置。")
    return existing


def _assert_safe_directory(path: Path, label: str) -> None:
    if _lexists(path) and (path.is_symlink() or not path.is_dir()):
        raise InstallError("{} 路径不是普通目录。".format(label))


def _assert_safe_file(path: Path, label: str) -> None:
    if _lexists(path) and (path.is_symlink() or not path.is_file()):
        raise InstallError("{} 路径不是普通文件。".format(label))


def _stage_file(path: Path, content: bytes, mode: int) -> Path:
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        if os.name == "posix":
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
    return temp_path


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _merge_config(existing: dict[str, Any], connector: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    servers = dict(existing.get("mcpServers", {}))
    servers["business-data"] = connector
    merged["mcpServers"] = servers
    return merged


def install(config_dir: Path) -> None:
    package_dir = Path(__file__).resolve().parent
    connector, skill_bytes = _validate_package(package_dir)
    config_dir = config_dir.expanduser().resolve()
    _assert_safe_directory(config_dir, "配置目录")

    config_path = config_dir / "mcp.json"
    existing = _existing_config(config_path)
    merged = _merge_config(existing, connector)
    try:
        config_bytes = (json.dumps(merged, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InstallError("无法生成有效的 WorkBuddy JSON 配置。") from exc

    skills_dir = config_dir / "skills"
    installed_skill_dir = skills_dir / "business-data-query"
    installed_skill_path = installed_skill_dir / "SKILL.md"
    _assert_safe_directory(skills_dir, "Skill 目录")
    _assert_safe_directory(installed_skill_dir, "business-data-query")
    _assert_safe_file(installed_skill_path, "已安装的 SKILL.md")

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        skills_dir.mkdir(parents=True, exist_ok=True)
        installed_skill_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallError("无法创建 WorkBuddy 配置或 Skill 目录。") from exc

    config_temp: Optional[Path] = None
    skill_temp: Optional[Path] = None
    try:
        config_temp = _stage_file(config_path, config_bytes, 0o600)
        skill_temp = _stage_file(installed_skill_path, skill_bytes, 0o644)
        os.replace(str(config_temp), str(config_path))
        config_temp = None
        _fsync_directory(config_dir)
        os.replace(str(skill_temp), str(installed_skill_path))
        skill_temp = None
        _fsync_directory(installed_skill_dir)
    except OSError as exc:
        raise InstallError("写入 WorkBuddy 配置或 Skill 失败。") from exc
    finally:
        for temp_path in (config_temp, skill_temp):
            if temp_path is not None and _lexists(temp_path):
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    try:
        actual_config = _read_json_object(config_path)
        actual_skill = installed_skill_path.read_bytes()
        private_mode_valid = True
        if os.name == "posix":
            private_mode_valid = stat.S_IMODE(config_path.stat().st_mode) == 0o600
    except (InstallError, OSError) as exc:
        raise InstallError("写入后读回验证失败。") from exc
    if actual_config != merged or actual_skill != skill_bytes or not private_mode_valid:
        raise InstallError("写入后读回验证失败。")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="安装已打包的 WorkBuddy MCP 连接与 Skill。")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path.home() / ".workbuddy-ai",
        help="WorkBuddy 配置根目录；默认 ~/.workbuddy-ai。",
    )
    args = parser.parse_args(argv)
    try:
        install(args.config_dir)
    except InstallError as exc:
        print("安装失败：{}".format(exc), file=sys.stderr)
        return 1
    except OSError:
        print("安装失败：本地文件读写错误。", file=sys.stderr)
        return 1
    print("WorkBuddy MCP 配置与 Skill 已安装并验证。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
