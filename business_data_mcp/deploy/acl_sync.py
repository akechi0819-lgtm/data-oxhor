"""Grant the service read access to only the current foundation snapshot."""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import pwd
import subprocess
import sys
import tempfile
from typing import Any
from datetime import date
from data_platform.query.service import QueryError
from data_platform.sql_release_query import resolve_sql_release


BASE = Path("/var/lib/shadow-bi")
RELEASES = BASE / "releases"
CURRENT = BASE / "current"
STATE = Path("/var/lib/business-data-mcp-acl/state.json")
SERVICE_USER = "business-mcp"
SETFACL = "/usr/bin/setfacl"
GETFACL = "/usr/bin/getfacl"


class AclSyncError(RuntimeError):
    """The current release cannot be authorized safely."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise AclSyncError("CURRENT_METADATA_UNAVAILABLE") from None
    if not isinstance(value, dict):
        raise AclSyncError("CURRENT_METADATA_INVALID")
    return value


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _regular_file(root: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise AclSyncError("CURRENT_PATH_INVALID")
    path = root
    for part in candidate.parts:
        path = path / part
        if path.is_symlink():
            raise AclSyncError("CURRENT_PATH_INVALID")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise AclSyncError("CURRENT_PATH_UNAVAILABLE") from None
    if not _is_below(resolved, root.resolve(strict=True)) or not resolved.is_file():
        raise AclSyncError("CURRENT_PATH_INVALID")
    return resolved


def _release_allowlist(current_link: Path, releases_root: Path) -> tuple[Path, set[Path], set[Path]]:
    try:
        base = current_link.parent.resolve(strict=True)
        releases = releases_root.resolve(strict=True)
        release = current_link.resolve(strict=True)
    except OSError:
        raise AclSyncError("CURRENT_RELEASE_UNAVAILABLE") from None
    if releases.parent != base or release.parent != releases:
        raise AclSyncError("CURRENT_RELEASE_INVALID")

    try:
        sql_release = resolve_sql_release(release)
    except QueryError as exc:
        raise AclSyncError("CURRENT_SQL_RELEASE_INVALID") from exc
    if sql_release is not None:
        files = {
            sql_release.candidate_path,
            sql_release.release_manifest_path,
            sql_release.warehouse,
            sql_release.landing_description_path,
        }
        directories: set[Path] = {base}
        for file in files:
            parent = file.parent
            while parent != base:
                if not _is_below(parent, base):
                    raise AclSyncError("CURRENT_PATH_INVALID")
                directories.add(parent)
                parent = parent.parent
        return release, directories, files

    prepared_path = _regular_file(release, "prepared.json")
    manifest_path = _regular_file(release, "library/library_manifest.json")
    prepared = _read_json(prepared_path)
    manifest = _read_json(manifest_path)
    batch_id = prepared.get("batch_id")
    if (prepared.get("status") != "prepared" or prepared.get("release") != release.name
            or prepared.get("published") is not False
            or not isinstance(batch_id, str) or not batch_id
            or manifest.get("schema_version") != "business_query_library.v1"
            or manifest.get("batch_id") != batch_id
            or prepared.get("library") != str((release / "library").resolve(strict=True))
            or manifest.get("snapshots") != prepared.get("snapshots")):
        raise AclSyncError("CURRENT_RELEASE_IDENTITY_MISMATCH")

    coverage = manifest.get("coverage")
    data_through = coverage.get("data_through") if isinstance(coverage, dict) else None
    prepared_coverage = prepared.get("coverage")
    if (not isinstance(data_through, str) or not isinstance(prepared_coverage, dict)
            or prepared_coverage.get("data_through") != data_through):
        raise AclSyncError("CURRENT_RELEASE_IDENTITY_MISMATCH")
    try:
        date.fromisoformat(data_through)
    except ValueError:
        raise AclSyncError("CURRENT_RELEASE_IDENTITY_MISMATCH") from None

    foundation = (release / "foundation").resolve(strict=True)
    try:
        prepared_foundation = Path(str(prepared["foundation"])).resolve(strict=True)
    except (KeyError, OSError):
        raise AclSyncError("CURRENT_FOUNDATION_INVALID") from None
    if prepared_foundation != foundation or foundation.parent != release:
        raise AclSyncError("CURRENT_FOUNDATION_INVALID")

    workspace_path = _regular_file(foundation, "Work/workspace.json")
    study_path = _regular_file(foundation, "Work/StudyAbroad/current.json")
    workspace = _read_json(workspace_path)
    study = _read_json(study_path)
    coverage = prepared.get("coverage")
    study_coverage = coverage.get("study_abroad_source") if isinstance(coverage, dict) else None
    snapshots = manifest.get("snapshots")
    if (not isinstance(snapshots, dict) or set(snapshots) != {"training", "abroad"}
            or workspace.get("current_snapshot_id") != snapshots.get("training")
            or study.get("snapshot_id") != snapshots.get("abroad")
            or workspace.get("company_id") != study.get("company_id")):
        raise AclSyncError("CURRENT_SNAPSHOT_IDENTITY_MISMATCH")

    bi_database = _regular_file(foundation, str(workspace.get("current_warehouse_path", "")))
    study_database = _regular_file(foundation, str(study.get("warehouse", "")))
    if bi_database.suffix != ".duckdb" or study_database.suffix != ".duckdb":
        raise AclSyncError("CURRENT_DATABASE_INVALID")
    bi_manifest = _regular_file(
        foundation, (bi_database.parent.relative_to(foundation) / "snapshot_manifest.json").as_posix()
    )
    study_manifest = _regular_file(
        foundation, (study_database.parent.relative_to(foundation) / "snapshot_manifest.json").as_posix()
    )

    files = {
        prepared_path, manifest_path, workspace_path, study_path,
        bi_database, bi_manifest, study_database, study_manifest,
    }
    directories: set[Path] = {base}
    for file in files:
        parent = file.parent
        while parent != base:
            if not _is_below(parent, base):
                raise AclSyncError("CURRENT_PATH_INVALID")
            directories.add(parent)
            parent = parent.parent
    return release, directories, files


def _state_read(path: Path, releases_root: Path, base: Path) -> tuple[set[Path], set[Path]]:
    if not path.exists():
        return set(), set()
    try:
        stat = path.stat()
        if stat.st_uid != 0 or stat.st_mode & 0o077:
            raise AclSyncError("ACL_STATE_UNSAFE")
        value = json.loads(path.read_text(encoding="utf-8"))
    except AclSyncError:
        raise
    except (OSError, json.JSONDecodeError):
        raise AclSyncError("ACL_STATE_INVALID") from None
    if not isinstance(value, dict) or not isinstance(value.get("directories"), list) or not isinstance(value.get("files"), list):
        raise AclSyncError("ACL_STATE_INVALID")

    def checked(items: list[Any]) -> set[Path]:
        if not all(isinstance(item, str) and Path(item).is_absolute() for item in items):
            raise AclSyncError("ACL_STATE_INVALID")
        output = {Path(item) for item in items}
        if any(path != base and not _is_below(path, releases_root) for path in output):
            raise AclSyncError("ACL_STATE_INVALID")
        return output

    return checked(value["directories"]), checked(value["files"])


def _has_acl(path: Path, username: str) -> bool:
    result = subprocess.run([GETFACL, "-cp", str(path)], capture_output=True, text=True, check=True)
    return any(line.startswith(f"user:{username}:") for line in result.stdout.splitlines())


def _remove_acl(path: Path, username: str) -> None:
    if path.exists() and _has_acl(path, username):
        subprocess.run([SETFACL, "-x", f"u:{username}", "--", str(path)], check=True, capture_output=True)


def _write_state(path: Path, directories: set[Path], files: set[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    data = {"directories": sorted(map(str, directories)), "files": sorted(map(str, files))}
    descriptor, temporary_name = tempfile.mkstemp(prefix=".state.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def sync_for(current_link: Path, releases_root: Path, state_path: Path, username: str) -> tuple[int, int]:
    """Revoke the previous allowlist and grant only the current release files."""
    if os.geteuid() != 0:
        raise AclSyncError("ROOT_REQUIRED")
    try:
        pwd.getpwnam(username)
    except KeyError:
        raise AclSyncError("SERVICE_USER_MISSING") from None
    base = current_link.parent.resolve(strict=True)
    releases = releases_root.resolve(strict=True)
    _, directories, files = _release_allowlist(current_link, releases)
    old_directories, old_files = _state_read(state_path, releases, base)

    # Fail closed during a version switch: revoke the old version first. A query
    # reaching the new current path before grants finish returns a permission
    # error; it never falls back to the prior release.
    for path in sorted(old_files - files, key=lambda item: len(item.parts), reverse=True):
        _remove_acl(path, username)
    for path in sorted(old_directories - directories, key=lambda item: len(item.parts), reverse=True):
        _remove_acl(path, username)
    for path in sorted(directories, key=lambda item: len(item.parts)):
        subprocess.run([SETFACL, "-m", f"u:{username}:--x", "--", str(path)], check=True, capture_output=True)
    for path in sorted(files, key=str):
        subprocess.run([SETFACL, "-m", f"u:{username}:r--", "--", str(path)], check=True, capture_output=True)
    _write_state(state_path, directories, files)
    return len(directories), len(files)


def main() -> int:
    try:
        directories, files = sync_for(CURRENT, RELEASES, STATE, SERVICE_USER)
    except AclSyncError as exc:
        print(f"business-data-mcp-acl-sync: {exc}", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError):
        print("business-data-mcp-acl-sync: ACL_UPDATE_FAILED", file=sys.stderr)
        return 1
    print(f"business-data-mcp-acl-sync: current allowlist ready ({directories} directories, {files} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
