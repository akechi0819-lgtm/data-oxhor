from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import dashboard_product
import monitoring_product


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCER = PROJECT_ROOT / "data_acquisition" / "deploy" / "run_daily_warehouses.sh"
DASHBOARD_PACKAGE = Path(dashboard_product.__file__).resolve().parent
MONITORING_PACKAGE = Path(monitoring_product.__file__).resolve().parent
CONSUMERS = [
    DASHBOARD_PACKAGE / "deploy" / "run_management_daily.sh",
    MONITORING_PACKAGE / "deploy" / "deliver_management_batch.sh",
]
CHECK_ARGS = ["-m", "data_acquisition.jobs.daily_warehouses", "check"]
AS_OF_DATE = "2026-10-09"


def _fake_runtime(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "fake runtime"
    runtime.mkdir(parents=True)
    python = runtime / "python"
    python.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
record = {"argv": args, "stdin": sys.stdin.read(), "cwd": os.getcwd()}
with open(os.environ["TRACE_FILE"], "a", encoding="utf-8") as trace:
    trace.write(json.dumps(record) + "\\n")

mode = os.environ.get("FAKE_MODE", "success")
is_check = args[:3] == ["-m", "data_acquisition.jobs.daily_warehouses", "check"]
if mode == "fail-check":
    raise SystemExit(29 if is_check else 70)
if mode == "fail-body":
    if is_check:
        raise SystemExit(0)
    raise SystemExit(31 if args and args[0] == "-" else 70)
""",
        encoding="utf-8",
    )
    python.chmod(0o755)

    date = runtime / "date"
    date.write_text(
        """#!/bin/sh
case "$1" in
  +%F) printf '%s\\n' '2026-10-09' ;;
  +%H%M%S) printf '%s\\n' '121314' ;;
  *) exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    date.chmod(0o755)
    return runtime, python


def _base_env(tmp_path: Path, mode: str = "success") -> tuple[dict[str, str], Path]:
    runtime, python = _fake_runtime(tmp_path)
    trace = tmp_path / "python argv trace.jsonl"
    trace.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        PYTHON=str(python),
        TRACE_FILE=str(trace),
        FAKE_MODE=mode,
        PATH=f"{runtime}{os.pathsep}{env.get('PATH', '')}",
    )
    return env, trace


def _records(trace: Path) -> list[dict[str, str | list[str]]]:
    return [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]


def _run(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        cwd=PROJECT_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _seed_existing_artifacts(workspace: Path, run_id: str) -> dict[Path, bytes]:
    markers = {
        workspace / "Work" / "ManagementDelivery" / "batch.json": b'{"sentinel":"batch"}\n',
        workspace / "Output" / "DashboardManagement" / run_id / "shared_result.json": b"sentinel batch output\n",
        workspace / "Output" / "DashboardRelease" / run_id / "manifest.json": b"sentinel website release\n",
    }
    for path, contents in markers.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    return markers


def test_producer_passes_explicit_source_identity_and_literal_values_once(tmp_path: Path) -> None:
    env, trace = _base_env(tmp_path)
    workspace = tmp_path / "customer workspace"
    cookie_file = tmp_path / "dummy private cookie file.json"
    marker = tmp_path / "must not be shell-expanded"
    doc_id = f"doc $HOME $(touch {marker}) with spaces"
    doc_url = f"https://docs.example.invalid/export?literal=$TOKEN&value=$(touch {marker})"
    run_id = "run_daily_sources_test_001"
    bi_snapshot_id = "snapshot_bi_operations_test_001"
    study_snapshot_id = "snapshot_study_abroad_test_001"
    env.update(
        WORKSPACE=str(workspace),
        AS_OF_DATE=AS_OF_DATE,
        RUN_ID=run_id,
        BI_SNAPSHOT_ID=bi_snapshot_id,
        STUDY_SNAPSHOT_ID=study_snapshot_id,
        TENCENT_DOC_ID=doc_id,
        TENCENT_DOC_URL=doc_url,
        TENCENT_COOKIE_FILE=str(cookie_file),
    )

    result = _run(PRODUCER, env)

    assert result.returncode == 0, result.stderr
    records = _records(trace)
    assert len(records) == 1
    assert records[0]["argv"] == [
        "-m",
        "data_acquisition.jobs.daily_warehouses",
        "--workspace",
        str(workspace),
        "--as-of-date",
        AS_OF_DATE,
        "--run-id",
        run_id,
        "--bi-snapshot-id",
        bi_snapshot_id,
        "--study-snapshot-id",
        study_snapshot_id,
        "--doc-id",
        doc_id,
        "--page-url",
        doc_url,
        "--cookie-file",
        str(cookie_file),
    ]
    assert len({run_id, bi_snapshot_id, study_snapshot_id}) == 3
    assert not marker.exists()


def test_producer_rejects_each_missing_required_environment_value(tmp_path: Path) -> None:
    required = ["WORKSPACE", "PYTHON", "TENCENT_DOC_ID", "TENCENT_DOC_URL", "TENCENT_COOKIE_FILE"]
    for missing in required:
        env, trace = _base_env(tmp_path / missing)
        env.update(
            WORKSPACE=str(tmp_path / "customer workspace"),
            TENCENT_DOC_ID="dummy-doc-id",
            TENCENT_DOC_URL="https://docs.example.invalid/dummy",
            TENCENT_COOKIE_FILE=str(tmp_path / "dummy-cookie-file"),
        )
        if missing == "PYTHON":
            env.pop("PYTHON")
        else:
            env.pop(missing)

        result = _run(PRODUCER, env)

        assert result.returncode != 0, missing
        assert missing in result.stderr
        assert _records(trace) == []


@pytest.mark.parametrize("script", CONSUMERS, ids=["dashboard-build", "management-delivery"])
def test_consumers_stop_on_unready_sources_before_build_or_publish(
    tmp_path: Path, script: Path
) -> None:
    env, trace = _base_env(tmp_path, mode="fail-check")
    workspace = tmp_path / "customer workspace"
    run_id = "run_consumer_guard_test"
    markers = _seed_existing_artifacts(workspace, run_id)
    before = {path: path.read_bytes() for path in markers}
    env.update(
        WORKSPACE=str(workspace),
        PROJECT_ROOT=str(PROJECT_ROOT),
        RUN_ID=run_id,
        AS_OF_DATE=AS_OF_DATE,
        ENV_FILE=str(tmp_path / "dummy credential file.env"),
    )

    result = _run(script, env)

    assert result.returncode == 29, result.stderr
    records = _records(trace)
    assert len(records) == 1
    assert records[0]["argv"] == [
        *CHECK_ARGS,
        "--workspace",
        str(workspace),
        "--as-of-date",
        AS_OF_DATE,
    ]
    assert {path: path.read_bytes() for path in markers} == before


def test_delivery_stops_before_send_when_batch_identity_validation_fails(tmp_path: Path) -> None:
    env, trace = _base_env(tmp_path, mode="fail-body")
    workspace = tmp_path / "customer workspace"
    run_id = "run_delivery_body_guard_test"
    markers = _seed_existing_artifacts(workspace, run_id)
    before = {path: path.read_bytes() for path in markers}
    env.update(
        WORKSPACE=str(workspace),
        PROJECT_ROOT=str(PROJECT_ROOT),
        ENV_FILE=str(tmp_path / "dummy credential file.env"),
    )

    result = _run(CONSUMERS[1], env)

    assert result.returncode == 31, result.stderr
    records = _records(trace)
    assert len(records) == 2
    assert records[0]["argv"][:3] == CHECK_ARGS
    validation = records[1]
    assert validation["argv"][0] == "-"
    assert "assert_daily_ready" in validation["stdin"]
    assert "bi_snapshot_id=body['metadata']['snapshot_id']" in validation["stdin"]
    assert "study_snapshot_id=study" in validation["stdin"]
    assert all("monitoring_product.shared_delivery" not in record["argv"] for record in records)
    assert {path: path.read_bytes() for path in markers} == before
