from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from data_acquisition.jobs import daily_warehouses, update_tencent_study_abroad


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    _write_json(workspace / "Work/StudyAbroad/current.json", {
        "schema_version": "study_abroad_warehouse.v1",
        "company_id": "company_fixture",
        "run_id": "run_previous",
        "snapshot_id": "snapshot_previous",
        "through_date": "2026-10-08",
        "used_snapshot_ids": [],
    })
    return workspace


def _build_result(**kwargs) -> dict:
    return {
        "company_id": "company_fixture",
        "run_id": kwargs["run_id"],
        "snapshot_id": kwargs["snapshot_id"],
        "through_date": kwargs["through_date"],
    }


def _daily_args(workspace: Path) -> list[str]:
    return [
        "--workspace", str(workspace),
        "--as-of-date", "2026-10-09",
        "--run-id", "run_daily_cli",
        "--bi-snapshot-id", "snapshot_bi_operations_20261009_daily",
        "--study-snapshot-id", "snapshot_study_abroad_20261009_daily",
    ]


def test_daily_cli_rejects_removed_cookie_arguments(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    with patch.object(daily_warehouses, "refresh_daily") as refresh:
        with pytest.raises(SystemExit) as exit_info:
            daily_warehouses.main(_daily_args(workspace) + ["--cookie-file", str(tmp_path / "cookies.json")])

    assert exit_info.value.code == 2
    assert "unrecognized arguments: --cookie-file" in capsys.readouterr().err
    refresh.assert_not_called()


def test_online_update_reads_mcp_config_and_records_download_receipt(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    token_file = tmp_path / "mcp-token.json"
    _write_json(workspace / ".private/tencent-source.json", {
        "file_id": "mcp_file_fixture",
        "token_file": str(token_file),
    })
    run_id = "run_study_mcp_fixture"
    snapshot_id = "snapshot_study_abroad_20261009_fixture"
    through_date = "2026-10-09"
    downloads = workspace / "Work/StudyAbroad/Downloads" / run_id
    capture_path = downloads / "export.xlsx"
    capture_bytes = b"mock MCP export"
    capture_sha256 = hashlib.sha256(capture_bytes).hexdigest()

    def fake_download(**kwargs):
        assert kwargs == {
            "file_id": "mcp_file_fixture",
            "token_file": token_file,
            "output_dir": downloads,
        }
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        capture_path.write_bytes(capture_bytes)
        return SimpleNamespace(
            path=capture_path,
            sha256=capture_sha256,
            size_bytes=len(capture_bytes),
            task_id="mcp_task_fixture",
        )

    with (
        patch.object(update_tencent_study_abroad, "download_tencent_doc_xlsx", side_effect=fake_download) as download,
        patch.object(update_tencent_study_abroad, "build", side_effect=_build_result) as build,
    ):
        result = update_tencent_study_abroad.update(
            workspace=workspace,
            run_id=run_id,
            snapshot_id=snapshot_id,
            through_date=through_date,
            refresh_months=["2026-10"],
        )

    download.assert_called_once()
    build.assert_called_once_with(
        workspace=workspace.resolve(),
        source_file=capture_path,
        run_id=run_id,
        snapshot_id=snapshot_id,
        through_date=through_date,
        refresh_months=["2026-10"],
        history_snapshot_id="snapshot_previous",
    )
    assert result["capture"] == {
        "path": str(capture_path),
        "sha256": capture_sha256,
        "size_bytes": len(capture_bytes),
        "method": "mcp",
        "task_id": "mcp_task_fixture",
    }


def test_offline_source_update_skips_mcp_config_and_download(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source_file = tmp_path / "receiver" / "tencent.xlsx"
    source_file.parent.mkdir(parents=True)
    source_bytes = b"raw receiver input"
    source_file.write_bytes(source_bytes)
    run_id = "run_study_local_fixture"
    snapshot_id = "snapshot_study_abroad_20261009_local"
    through_date = "2026-10-09"
    local_capture = workspace / "Work/StudyAbroad/Downloads" / run_id / source_file.name

    with (
        patch.object(update_tencent_study_abroad, "download_tencent_doc_xlsx") as download,
        patch.object(update_tencent_study_abroad, "build", side_effect=_build_result) as build,
    ):
        result = update_tencent_study_abroad.update(
            workspace=workspace,
            run_id=run_id,
            snapshot_id=snapshot_id,
            through_date=through_date,
            refresh_months=["2026-10"],
            source_file=source_file,
        )

    download.assert_not_called()
    build.assert_called_once_with(
        workspace=workspace.resolve(),
        source_file=local_capture,
        run_id=run_id,
        snapshot_id=snapshot_id,
        through_date=through_date,
        refresh_months=["2026-10"],
        history_snapshot_id="snapshot_previous",
    )
    assert local_capture.read_bytes() == source_bytes
    assert result["capture"] == {
        "path": str(local_capture),
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "size_bytes": len(source_bytes),
        "method": "local_input",
    }
