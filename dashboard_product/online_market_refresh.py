"""Refresh the independent online-market work-order board from a shadow Snapshot."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from data_platform.query.evidence import read_query_result


ROOT = Path(__file__).resolve().parents[1]
QUERY_REGISTRY = Path(__file__).resolve().parent / "config" / "online_market_queries"
QUERY_ID = "online_market_orders"
QUERY_VERSION = "v1"
MONTHS = [f"2026-{month:02d}" for month in range(6, 13)] + [
    f"2027-{month:02d}" for month in range(1, 6)
]
PRIOR_MONTHS = [f"2025-{month:02d}" for month in range(6, 13)] + [
    f"2026-{month:02d}" for month in range(1, 6)
]
GROUPS = ("网络资源", "新媒体")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _empty_series() -> dict[str, list[float]]:
    return {"orders": [0.0] * 12, "passive_orders": [0.0] * 12}


def _add_series(target: dict[str, list[float]], index: int, passive: bool) -> None:
    target["orders"][index] += 1.0
    if passive:
        target["passive_orders"][index] += 1.0


def _empty_period() -> dict:
    return {
        "total": _empty_series(),
        "groups": {group: _empty_series() for group in GROUPS},
        "platforms": {},
        "countries": {},
        "lines": {},
    }


def _empty_line() -> dict:
    return {"series": _empty_series(), "countries": {}}


def _add_dimension(target: dict, key: str, index: int, passive: bool) -> None:
    target.setdefault(key, _empty_series())
    _add_series(target[key], index, passive)


def _aggregate(rows: list[list], months: list[str]) -> dict:
    period = _empty_period()
    month_index = {month: index for index, month in enumerate(months)}
    for row in rows:
        if len(row) != 9:
            raise ValueError(f"unexpected online-market query row: expected 9 columns, got {len(row)}")
        event_date, group, first_channel, second_channel, country, corrected_line, active_type, value, metric = row
        month = str(event_date)[:7]
        index = month_index.get(month)
        if index is None or metric != "work_orders" or not group:
            continue
        passive = str(active_type or "").strip() == "被动"
        _add_series(period["total"], index, passive)
        period["groups"].setdefault(group, _empty_series())
        _add_series(period["groups"][group], index, passive)

        platform = str(second_channel or "").strip() or "二级渠道待确认"
        platform_info = period["platforms"].setdefault(
            platform,
            {
                "first_channels": set(),
                "series": _empty_series(),
                "groups": {group_name: _empty_series() for group_name in GROUPS},
            },
        )
        if first_channel:
            platform_info["first_channels"].add(str(first_channel).strip())
        _add_series(platform_info["series"], index, passive)
        platform_info["groups"].setdefault(group, _empty_series())
        _add_series(platform_info["groups"][group], index, passive)

        country_key = str(country or "").strip() or "国家待确认"
        line_key = str(corrected_line or "").strip() or "条线待确认"
        _add_dimension(period["countries"], country_key, index, passive)
        line_info = period["lines"].setdefault(line_key, _empty_line())
        _add_series(line_info["series"], index, passive)
        _add_dimension(line_info["countries"], country_key, index, passive)

    for platform_info in period["platforms"].values():
        platform_info["first_channels"] = sorted(platform_info["first_channels"])
    return period


def _run_query(
    *, warehouse: Path, snapshot_id: str, run_id: str, output_root: Path, start: str, end: str
) -> dict:
    command = [
        sys.executable,
        "-m",
        "interfaces.data_platform",
        "run-saved-query",
        "--warehouse",
        str(warehouse),
        "--snapshot-id",
        snapshot_id,
        "--run-id",
        run_id,
        "--output-root",
        str(output_root),
        "--registry-root",
        str(QUERY_REGISTRY),
        "--query-id",
        QUERY_ID,
        "--version",
        QUERY_VERSION,
        "--params-json",
        json.dumps([start, end], ensure_ascii=False),
        "--max-rows",
        "100000",
        "--max-result-bytes",
        "50000000",
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    try:
        result = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(completed.stdout or completed.stderr) from exc
    if completed.returncode != 0 or result.get("status") != "passed":
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    result["result"] = read_query_result(result, output_root=output_root)
    return result


def _query_ref(result: dict) -> dict:
    return {
        "run_id": result.get("run_id"),
        "snapshot_id": result.get("snapshot_id"),
        "receipt": result.get("receipt"),
        "row_count": len((result.get("result") or {}).get("rows") or []),
    }


def refresh(
    *,
    warehouse: Path,
    snapshot_id: str,
    output_root: Path,
    run_id: str,
    as_of_date: date | None = None,
) -> dict:
    warehouse = warehouse.resolve()
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    today = as_of_date or date.today()
    current_start = date(2026, 6, 1)
    prior_start = date(2025, 6, 1)
    current_end = today.isoformat()
    prior_end = (prior_start + (today - current_start)).isoformat()

    current = _run_query(
        warehouse=warehouse,
        snapshot_id=snapshot_id,
        run_id=run_id,
        output_root=output_root,
        start=current_start.isoformat(),
        end=current_end,
    )
    prior = _run_query(
        warehouse=warehouse,
        snapshot_id=snapshot_id,
        run_id=f"{run_id}_prior",
        output_root=output_root,
        start=prior_start.isoformat(),
        end=prior_end,
    )

    artifact = {
        "schema_version": "online_market_artifact.v1",
        "artifact_id": f"online_market_{uuid4().hex[:12]}",
        "run_id": run_id,
        "shadow_snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": today.isoformat(),
        "data_through_date": (today.fromordinal(today.toordinal() - 1)).isoformat(),
        "months": MONTHS,
        "prior_months": PRIOR_MONTHS,
        "query_results": [_query_ref(current), _query_ref(prior)],
        "cash": {
            "status": "not_connected",
            "label": "现金数据待接入",
            "actual": None,
            "target": None,
        },
        "targets": _read(Path(__file__).resolve().parent / "config" / "online_market_targets.json"),
        "study_abroad": {
            "current": _aggregate(current["result"]["rows"], MONTHS),
            "prior": _aggregate(prior["result"]["rows"], PRIOR_MONTHS),
            "scope": {
                "line": "留学线上",
                "channel_roots": list(GROUPS),
                "cash": "not_connected",
            },
        },
    }
    artifact_path = output_root / "online_market_artifact.json"
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "artifact_created", "artifact": str(artifact_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--as-of-date", default=None)
    args = parser.parse_args()
    try:
        result = refresh(
            warehouse=args.warehouse,
            snapshot_id=args.snapshot_id,
            output_root=args.output_root,
            run_id=args.run_id,
            as_of_date=date.fromisoformat(args.as_of_date) if args.as_of_date else None,
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
