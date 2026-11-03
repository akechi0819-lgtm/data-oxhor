from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCER = PROJECT_ROOT / "data_acquisition" / "deploy" / "run_daily_warehouses.sh"
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


def _base_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    runtime, python = _fake_runtime(tmp_path)
    trace = tmp_path / "python argv trace.jsonl"
    trace.write_text("", encoding="utf-8")
    env = os.environ.copy()
    for name in ("TENCENT_DOC_ID", "TENCENT_DOC_URL", "TENCENT_COOKIE_FILE", "TENCENT_CA_FILE"):
        env.pop(name, None)
    env.update(
        PYTHON=str(python),
        PROJECT_ROOT=str(PROJECT_ROOT),
        TRACE_FILE=str(trace),
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


def test_producer_passes_explicit_source_identity_without_legacy_credentials(tmp_path: Path) -> None:
    env, trace = _base_env(tmp_path)
    workspace = tmp_path / "customer workspace"
    run_id = "run_daily_sources_test_001"
    bi_snapshot_id = "snapshot_bi_operations_test_001"
    study_snapshot_id = "snapshot_study_abroad_test_001"
    env.update(
        WORKSPACE=str(workspace),
        AS_OF_DATE=AS_OF_DATE,
        RUN_ID=run_id,
        BI_SNAPSHOT_ID=bi_snapshot_id,
        STUDY_SNAPSHOT_ID=study_snapshot_id,
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
    ]
    assert len({run_id, bi_snapshot_id, study_snapshot_id}) == 3
    assert not {"TENCENT_DOC_ID", "TENCENT_DOC_URL", "TENCENT_COOKIE_FILE", "TENCENT_CA_FILE"} & env.keys()


def test_producer_rejects_each_missing_required_environment_value(tmp_path: Path) -> None:
    required = ["WORKSPACE", "PYTHON"]
    for missing in required:
        env, trace = _base_env(tmp_path / missing)
        env["WORKSPACE"] = str(tmp_path / "customer workspace")
        if missing == "PYTHON":
            env.pop("PYTHON")
        else:
            env.pop(missing)

        result = _run(PRODUCER, env)

        assert result.returncode != 0, missing
        assert missing in result.stderr
        assert _records(trace) == []
