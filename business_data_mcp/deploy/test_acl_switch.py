"""Linux integration probe for ACL scope, fail-closed switching, and path events."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from acl_sync import sync_for


def _write(path: Path, value: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def _release(releases: Path, name: str, suffix: str) -> tuple[Path, list[Path], list[Path]]:
    release = releases / name
    foundation = release / "foundation"
    library = release / "library"
    training_id = f"snapshot_training_{suffix}"
    study_id = f"snapshot_abroad_{suffix}"
    training_rel = f"Work/Runs/training_{suffix}/data/snapshots/{training_id}/warehouse.duckdb"
    study_rel = f"Work/StudyAbroad/Runs/study_{suffix}/data/snapshots/{study_id}/warehouse.duckdb"
    snapshots = {"training": training_id, "abroad": study_id}
    coverage = {"data_through": "2026-11-03"}
    batch_id = f"run_{suffix}"
    manifest = {
        "schema_version": "business_query_library.v1",
        "batch_id": batch_id,
        "snapshots": snapshots,
        "coverage": coverage,
    }
    prepared = {
        "status": "prepared",
        "published": False,
        "release": name,
        "batch_id": batch_id,
        "snapshots": snapshots,
        "coverage": coverage,
        "foundation": str(foundation.resolve()),
        "library": str(library.resolve()),
    }
    _write(release / "prepared.json", json.dumps(prepared))
    _write(library / "library_manifest.json", json.dumps(manifest))
    _write(release / "not-allowlisted.json", b"unused test marker")
    _write(foundation / "Work/workspace.json", json.dumps({
        "company_id": "fixture-company",
        "current_snapshot_id": training_id,
        "current_warehouse_path": training_rel,
    }))
    _write(foundation / "Work/StudyAbroad/current.json", json.dumps({
        "company_id": "fixture-company",
        "snapshot_id": study_id,
        "warehouse": study_rel,
    }))
    training = foundation / training_rel
    study = foundation / study_rel
    for warehouse in (training, study):
        _write(warehouse, b"")
        _write(warehouse.parent / "snapshot_manifest.json", b"{}")
        _write(warehouse.parent / "same-directory-secret.bin", b"unused test marker")
    for directory in sorted((path for path in release.rglob("*") if path.is_dir()),
                            key=lambda path: len(path.parts), reverse=True):
        directory.chmod(0o700)
    release.chmod(0o700)
    return release, [
        release / "prepared.json",
        library / "library_manifest.json",
        foundation / "Work/workspace.json",
        foundation / "Work/StudyAbroad/current.json",
        training,
        training.parent / "snapshot_manifest.json",
        study,
        study.parent / "snapshot_manifest.json",
    ], [
        release / "not-allowlisted.json",
        training.parent / "same-directory-secret.bin",
        study.parent / "same-directory-secret.bin",
    ]


def _readable(path: Path, *, username: str = "nobody") -> bool:
    result = subprocess.run(
        ["runuser", "-u", username, "--", "/usr/bin/test", "-r", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _query_release(current_link: Path) -> tuple[int, str]:
    code = """
from pathlib import Path
import sys
from business_data_mcp.query import BusinessDataQuery, BusinessDataMCPError
query = BusinessDataQuery(Path(sys.argv[1]), Path('/tmp/mcp-acl-probe-results'))
try:
    print(query.describe()['release'])
except BusinessDataMCPError as error:
    print(error.code)
"""
    result = subprocess.run(
        ["runuser", "-u", "nobody", "--", "/srv/business-data-mcp/venv/bin/python", "-c", code, str(current_link)],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip()


def _check(condition: bool, name: str, results: dict[str, bool]) -> None:
    results[name] = bool(condition)
    if not condition:
        raise RuntimeError(name)


def _probe_failure_window(root: Path, results: dict[str, bool]) -> None:
    watched = root / "window"
    releases = watched / "releases"
    state = root / "window-acl-state" / "state.json"
    watched.mkdir(mode=0o700)
    releases.mkdir(mode=0o700)
    first, first_allowed, _ = _release(releases, "daily-20261104_foundation2", "window1")
    second, second_allowed, _ = _release(releases, "daily-20261105_foundation3", "window2")
    current = watched / "current"
    current.symlink_to(first, target_is_directory=True)
    sync_for(current, releases, state, "nobody")

    next_link = watched / "next"
    next_link.symlink_to(second, target_is_directory=True)
    os.replace(next_link, current)
    code, response = _query_release(current)
    _check(code == 0 and response in {"CURRENT_RELEASE_UNAVAILABLE", "CURRENT_RELEASE_INVALID"},
           "unready_new_current_fails_closed", results)
    _check(not any(_readable(path) for path in second_allowed), "unready_new_release_not_readable", results)
    sync_for(current, releases, state, "nobody")
    code, response = _query_release(current)
    _check(code == 0 and response == second.name, "new_current_available_after_acl_sync", results)
    _check(not any(_readable(path) for path in first_allowed), "old_current_revoked_after_switch", results)


def _probe_path_trigger(root: Path, results: dict[str, bool]) -> None:
    watched = root / "automatic"
    releases = watched / "releases"
    state = root / "automatic-acl-state" / "state.json"
    marker = root / "marker.txt"
    watched.mkdir(mode=0o700)
    releases.mkdir(mode=0o700)
    first, first_allowed, _ = _release(releases, "daily-20261104_foundation4", "auto1")
    second, second_allowed, second_denied = _release(releases, "daily-20261105_foundation5", "auto2")
    current = watched / "current"
    current.symlink_to(first, target_is_directory=True)
    sync_for(current, releases, state, "nobody")
    _check(all(_readable(path) for path in first_allowed), "initial_allowlist_readable", results)
    _check(not any(_readable(path) for path in first_allowed + second_allowed if path not in first_allowed),
           "noncurrent_release_not_readable", results)
    _check(not any(_readable(path) for path in [
        first / "not-allowlisted.json",
        first / "foundation" / "Work/Runs/auto1/data/snapshots/snapshot_training_auto1/same-directory-secret.bin",
        first / "foundation/Work/StudyAbroad/Runs/study_auto1/data/snapshots/snapshot_abroad_auto1/same-directory-secret.bin",
    ]), "same_directory_nonallowlist_unreadable", results)

    runner = root / "sync-on-path-change.py"
    deploy_dir = Path(__file__).resolve().parent
    _write(runner, (
        "import sys\n"
        f"sys.path.insert(0, {str(deploy_dir)!r})\n"
        "from pathlib import Path\n"
        "from acl_sync import sync_for\n"
        "current, releases, state, marker = map(Path, sys.argv[1:])\n"
        "counts = sync_for(current, releases, state, 'nobody')\n"
        "marker.write_text(f'{counts[0]} {counts[1]}', encoding='utf-8')\n"
    ))
    unit_name = f"business-data-mcp-acl-probe-{os.getpid()}"
    unit_root = Path("/run/systemd/system")
    service_file = unit_root / f"{unit_name}.service"
    path_file = unit_root / f"{unit_name}.path"
    service_file.write_text(
        "[Unit]\nDescription=Temporary Business Data MCP ACL probe\n"
        "[Service]\nType=oneshot\nExecStart=/usr/bin/python3 "
        f"{runner} {current} {releases} {state} {marker}\n",
        encoding="utf-8",
    )
    path_file.write_text(
        "[Unit]\nDescription=Temporary Business Data MCP ACL path probe\n"
        f"[Path]\nPathChanged={watched}\nUnit={unit_name}.service\n",
        encoding="utf-8",
    )
    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
        subprocess.run(["systemctl", "start", f"{unit_name}.path"], check=True, capture_output=True)
        next_link = watched / "next"
        next_link.symlink_to(second, target_is_directory=True)
        os.replace(next_link, current)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.1)
        _check(marker.exists(), "path_change_triggered_acl_sync", results)
        marker.unlink()
        _check(all(_readable(path) for path in second_allowed), "atomic_new_release_readable", results)
        _check(not any(_readable(path) for path in first_allowed), "atomic_old_release_revoked", results)
        _check(not any(_readable(path) for path in second_denied), "atomic_sibling_files_denied", results)
        code, response = _query_release(current)
        _check(code == 0 and response == second.name, "query_resolves_only_new_current", results)
    finally:
        subprocess.run(["systemctl", "stop", f"{unit_name}.path", f"{unit_name}.service"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        service_file.unlink(missing_ok=True)
        path_file.unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("run as root on the deployment host")
    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="business-data-mcp-acl-test-") as temporary:
        root = Path(temporary)
        root.chmod(0o711)
        _probe_failure_window(root, results)
        _probe_path_trigger(root, results)
    print(json.dumps({"status": "passed", "checks": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
