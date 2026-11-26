"""Merge monthly study-abroad workbook exports while preserving file lineage."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re

from data_acquisition.connectors.study_abroad_source import read_sources


_SCHEMA = "study_abroad_monthly_history.v1"
_DATE_FIELDS = {
    "resources": "date",
    "contracts": "archive_date",
    "languages": "date",
}


def _month(value: object, *, kind: str, row_number: object, filename: str) -> str:
    if isinstance(value, datetime):
        return value.date().strftime("%Y-%m")
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{filename} 的 {kind} 第 {row_number} 行缺少业务日期")

    text = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}", text):
            return date.fromisoformat(f"{text}-01").strftime("%Y-%m")
        return date.fromisoformat(text[:10]).strftime("%Y-%m")
    except ValueError as exc:
        raise ValueError(f"{filename} 的 {kind} 第 {row_number} 行日期无效") from exc


def _normalize_refresh_months(refresh_months: list[str]) -> list[str]:
    result = set()
    for value in refresh_months:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
            raise ValueError("refresh_months 必须使用 YYYY-MM 格式")
        try:
            date.fromisoformat(f"{value}-01")
        except ValueError as exc:
            raise ValueError("refresh_months 包含无效月份") from exc
        result.add(value)
    return sorted(result)


def _load_sources(source_file: Path, history_files: list[Path]) -> list[tuple[Path, dict]]:
    ordered_paths = [Path(path) for path in history_files] + [Path(source_file)]
    loaded = []
    for path in ordered_paths:
        source = read_sources(path)
        source_path = Path(source.get("source_path", path))
        filename = path.name
        source_sha256 = source.get("source_sha256")
        source_sheets = source.get("source_sheets")
        if not isinstance(source_sha256, str) or not source_sha256:
            raise ValueError(f"{filename} 缺少原始来源 SHA-256")
        if not isinstance(source_sheets, dict):
            raise ValueError(f"{filename} 缺少 reader 返回的工作表元数据")
        for kind in _DATE_FIELDS:
            if not isinstance(source.get(kind), list):
                raise ValueError(f"{filename} 缺少 {kind} 来源行")
            if not isinstance(source_sheets.get(kind), str) or not source_sheets[kind]:
                raise ValueError(f"{filename} 缺少 {kind} 的实际工作表名称")
        loaded.append((path, {
            **source,
            "source_path": str(source_path),
            "filename": filename,
            "source_sha256": source_sha256,
            "source_sheets": dict(source_sheets),
        }))
    return loaded


def _with_origin(row: dict, *, source: dict, kind: str) -> dict:
    row_number = row.get("source_row_number")
    if not isinstance(row_number, int) or isinstance(row_number, bool) or row_number < 1:
        raise ValueError(f"{source['filename']} 的 {kind} 行缺少有效 Excel 行号")
    return {
        **row,
        "origin_sha256": source["source_sha256"],
        "origin_filename": source["filename"],
        "origin_sheet": source["source_sheets"][kind],
        "origin_row_number": row_number,
    }


def _composite_sha256(loaded: list[tuple[Path, dict]], refresh_months: list[str]) -> str:
    identity = {
        "schema": _SCHEMA,
        "ordered_input_sha256": [source["source_sha256"] for _path, source in loaded],
        "refresh_months": refresh_months,
    }
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_retained_sources(
    source_file: Path,
    history_files: list[Path],
    refresh_months: list[str],
) -> dict:
    """Read history oldest-to-newest, then replace months observed in each later file.

    The current source additionally clears requested months with no current rows,
    allowing an explicit empty monthly export to remove a prior partition.
    """
    months_to_refresh = _normalize_refresh_months(refresh_months)
    loaded = _load_sources(Path(source_file), list(history_files))
    current_path, current = loaded[-1]

    partitions: dict[str, dict[str, list[dict]]] = {kind: {} for kind in _DATE_FIELDS}
    for source_index, (_path, source) in enumerate(loaded):
        incoming_by_month: dict[str, dict[str, list[dict]]] = {kind: {} for kind in _DATE_FIELDS}
        for kind, date_field in _DATE_FIELDS.items():
            for row in source[kind]:
                if not isinstance(row, dict):
                    raise ValueError(f"{source['filename']} 的 {kind} 包含无效来源行")
                row_number = row.get("source_row_number")
                month = _month(row.get(date_field), kind=kind, row_number=row_number, filename=source["filename"])
                incoming_by_month[kind].setdefault(month, []).append(
                    _with_origin(row, source=source, kind=kind)
                )

        is_current = source_index == len(loaded) - 1
        for kind in _DATE_FIELDS:
            if is_current:
                for month in months_to_refresh:
                    if month not in incoming_by_month[kind]:
                        partitions[kind].pop(month, None)
            partitions[kind].update(incoming_by_month[kind])

    merged = {
        kind: [row for month in sorted(partitions[kind]) for row in partitions[kind][month]]
        for kind in _DATE_FIELDS
    }
    source_files = [
        {
            "path": source["source_path"],
            "sha256": source["source_sha256"],
            "filename": source["filename"],
            "source_sheets": dict(source["source_sheets"]),
        }
        for _path, source in loaded
    ]
    current_sha256 = current["source_sha256"]
    source_sha256 = (
        current_sha256 if len(loaded) == 1 else _composite_sha256(loaded, months_to_refresh)
    )
    return {
        **merged,
        "group_mapping": current["group_mapping"],
        "source_sheets": dict(current["source_sheets"]),
        "source_path": str(current_path),
        "current_source_sha256": current_sha256,
        "source_sha256": source_sha256,
        "source_files": source_files,
        "retained_months": {
            kind: sorted(partitions[kind])
            for kind in _DATE_FIELDS
        },
        "update_mode": "replace_observed_months_preserve_history",
    }
