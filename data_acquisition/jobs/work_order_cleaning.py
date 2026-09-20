"""Apply the confirmed study-abroad work-order cleaning overlay before ingest.

The reference workbook is a semantic sample, not a positional column join:

* ``咨询方式一级渠道`` supplies the source path (一级获取渠道-二级获取渠道).
* ``渠道`` supplies the lower-level source signal.
* ``一级获取渠道`` becomes the warehouse 一级渠道.
* The modal ``矫正-渠道`` for the same path/lower-level signal becomes the
  warehouse 二级渠道.
* Country and corrected line are resolved independently from channel.

Only valid rows with an empty source ``团队`` are changed. Existing语培 rows
are left untouched. Among留学 rows, only ``咨询方式一级渠道`` rooted at
``网络资源`` or ``新媒体`` is cleaned in this pass. ``渠道合作`` and ``市场活动``
are explicitly held for the offline pass. ``主被动`` is overwritten from
``资源主被动`` for online targets when the source value is present.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import argparse
import json
from pathlib import Path
import re
from typing import Any, Iterable


REFERENCE_REQUIRED_COLUMNS = (
    "一级获取渠道",
    "二级获取渠道",
    "三级获取渠道",
    "矫正-渠道",
    "矫正-条线",
    "矫正-意向国家",
)
OUTPUT_COLUMNS = ("意向国家", "矫正条线")
AUDIT_COLUMNS = ("留学渠道清洗状态", "意向国家归属方式")
ONLINE_ROOTS = frozenset({"网络资源", "新媒体"})
OFFLINE_ROOTS = frozenset({"渠道合作", "市场活动"})
EURASIA_PATH_MARK = "欧亚总部在线"
SPECIAL_CHANNEL_RULES = {
    "新媒体-其他": ("新媒体", "SSC"),
}
COUNTRY_LINE_FALLBACKS = {
    "哈萨克斯坦": "欧亚条线",
    "葡萄牙": "欧亚条线",
}
LANGUAGE_COUNTRY_RULES = (
    ("西班牙语", "西班牙"),
    ("西语", "西班牙"),
    ("葡萄牙语", "葡萄牙"),
    ("意大利语", "意大利"),
    ("荷兰语", "荷兰"),
    ("瑞典语", "瑞典"),
    ("芬兰语", "芬兰"),
    ("匈牙利语", "匈牙利"),
    ("俄罗斯语", "俄罗斯"),
    ("俄语", "俄罗斯"),
    ("法语", "法国"),
    ("德语", "德国"),
    ("韩语", "韩国"),
    ("日语", "日本"),
)
COUNTRY_TEXT_RULES = (
    "中国香港", "中国澳门", "澳大利亚", "澳洲", "新加坡", "加拿大", "美国", "英国",
    "日本", "韩国", "俄罗斯", "法国", "德国", "西班牙", "意大利", "葡萄牙",
    "荷兰", "瑞士", "瑞典", "芬兰", "匈牙利",
)
_COUNTRY_SPLIT = re.compile(r"[,，、/]+")
_COUNTRY_FROM_TEXT = re.compile(r"(?:意向国家(?:或地区)?|国家(?:或地区)?)\s*[:：]\s*([^\s，,；;。]+)")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _tokens(value: str) -> list[str]:
    return [token.strip() for token in _COUNTRY_SPLIT.split(value) if token.strip()]


@dataclass(frozen=True)
class WorkOrderReference:
    path_to_first_channel: dict[str, str]
    path_channel_to_corrected_channel: dict[tuple[str, str], str]
    country_to_line: dict[str, str]
    path_channel_counts: dict[tuple[str, str], dict[str, int]]
    country_line_counts: dict[str, dict[str, int]]


def _read_reference_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if not workbook.sheetnames:
            raise ValueError("reference workbook has no sheets")
        sheet = workbook[workbook.sheetnames[0]]
        iterator = sheet.iter_rows(values_only=True)
        header_row = next(iterator, None)
        if not header_row:
            raise ValueError("reference workbook has no header row")
        columns = [_text(value) for value in header_row]
        missing = [column for column in REFERENCE_REQUIRED_COLUMNS if column not in columns]
        if missing:
            raise ValueError(f"reference workbook missing required columns: {missing}")
        rows = []
        for values in iterator:
            if values is None or all(value is None or _text(value) == "" for value in values):
                continue
            rows.append({columns[index]: values[index] if index < len(values) else None for index in range(len(columns))})
        return columns, rows
    finally:
        workbook.close()


def load_work_order_reference(path: Path) -> WorkOrderReference:
    """Build deterministic semantic vocabularies from the business reference."""

    _, rows = _read_reference_rows(path)
    path_to_first: dict[str, str] = {}
    path_channel_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    country_line_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        first = _text(row.get("一级获取渠道"))
        second = _text(row.get("二级获取渠道"))
        third = _text(row.get("三级获取渠道"))
        corrected_channel = _text(row.get("矫正-渠道"))
        corrected_line = _text(row.get("矫正-条线"))
        if first and second:
            path_key = f"{first}-{second}"
            path_to_first[path_key] = first
            if third and corrected_channel:
                path_channel_counts[(path_key, third)][corrected_channel] += 1
        corrected_countries = _text(row.get("矫正-意向国家"))
        if corrected_line:
            for country in _tokens(corrected_countries):
                country_line_counts[country][corrected_line] += 1

    channel_mode: dict[tuple[str, str], str] = {}
    for key, counts in path_channel_counts.items():
        ordered = counts.most_common()
        if len(ordered) == 1 or ordered[0][1] > ordered[1][1]:
            channel_mode[key] = ordered[0][0]

    line_mode: dict[str, str] = {}
    for country, counts in country_line_counts.items():
        ordered = counts.most_common()
        if len(ordered) == 1 or ordered[0][1] > ordered[1][1]:
            line_mode[country] = ordered[0][0]

    return WorkOrderReference(
        path_to_first_channel=path_to_first,
        path_channel_to_corrected_channel=channel_mode,
        country_to_line=line_mode,
        path_channel_counts={key: dict(value) for key, value in path_channel_counts.items()},
        country_line_counts={key: dict(value) for key, value in country_line_counts.items()},
    )


def _first_country(value: str) -> str:
    tokens = _tokens(value)
    return tokens[0] if tokens else _text(value)


def _extract_country_with_source(row: dict[str, Any]) -> tuple[str, str]:
    direct = _text(row.get("意向国家/地区")) or _text(row.get("意向国家"))
    if direct:
        return _first_country(direct), "字段首国"
    description = _text(row.get("资源描述"))
    match = _COUNTRY_FROM_TEXT.search(description)
    if match:
        return _first_country(match.group(1)), "资源描述国家"
    for keyword in COUNTRY_TEXT_RULES:
        if keyword in description:
            return keyword, "资源描述国家"
    for keyword, country in LANGUAGE_COUNTRY_RULES:
        if keyword in description:
            return country, "资源描述语种推断"
    return "", "未命中"


def _extract_country(row: dict[str, Any]) -> str:
    return _extract_country_with_source(row)[0]


def _resolve_line(country: str, source_path: str, reference: WorkOrderReference) -> str:
    if EURASIA_PATH_MARK in source_path:
        return "欧亚条线"
    lines = {reference.country_to_line[token] for token in _tokens(country) if token in reference.country_to_line}
    if len(lines) == 0:
        fallback_lines = {COUNTRY_LINE_FALLBACKS[token] for token in _tokens(country) if token in COUNTRY_LINE_FALLBACKS}
        if len(fallback_lines) == 1:
            return next(iter(fallback_lines))
    return next(iter(lines)) if len(lines) == 1 else ""


def _is_study_abroad_target(row: dict[str, Any]) -> bool:
    return bool(_text(row.get("ID"))) and not _text(row.get("团队"))


def channel_scope(source_path: str) -> str:
    root = _text(source_path).split("-", 1)[0]
    if root in ONLINE_ROOTS:
        return "online"
    if root in OFFLINE_ROOTS:
        return "offline"
    return "other"


def clean_work_order_rows(
    rows: list[dict[str, Any]],
    reference: WorkOrderReference,
    *,
    include_audit: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Apply the overlay in place and return rows plus auditable counters."""

    stats = Counter(
        total_rows=len(rows),
        target_rows=0,
        online_target_rows=0,
        offline_target_rows=0,
        other_target_rows=0,
        main_active_overrides=0,
        first_channel_updates=0,
        second_channel_updates=0,
        country_filled=0,
        line_filled=0,
        unresolved_country=0,
        unresolved_line=0,
        unresolved_channel=0,
    )
    for row in rows:
        row.setdefault("意向国家", "")
        row.setdefault("矫正条线", "")
        if include_audit:
            row.setdefault("留学渠道清洗状态", "")
            row.setdefault("意向国家归属方式", "")
        if not _is_study_abroad_target(row):
            if include_audit and _text(row.get("团队")):
                row["留学渠道清洗状态"] = "语培原值"
                row["意向国家归属方式"] = "不适用"
            continue
        stats["target_rows"] += 1

        source_path = _text(row.get("咨询方式一级渠道"))
        scope = channel_scope(source_path)
        if scope == "offline":
            stats["offline_target_rows"] += 1
            if include_audit:
                row["留学渠道清洗状态"] = "线下范围外"
                row["意向国家归属方式"] = "不适用"
            continue
        if scope != "online":
            stats["other_target_rows"] += 1
            if include_audit:
                row["留学渠道清洗状态"] = "当前规则未命中"
                row["意向国家归属方式"] = "不适用"
            continue
        stats["online_target_rows"] += 1

        resource_active = _text(row.get("资源主被动"))
        if resource_active:
            if _text(row.get("主被动")) != resource_active:
                stats["main_active_overrides"] += 1
            row["主被动"] = resource_active

        country, country_source = _extract_country_with_source(row)
        row["意向国家"] = country
        if include_audit:
            row["意向国家归属方式"] = country_source
        if country:
            stats["country_filled"] += 1
        else:
            stats["unresolved_country"] += 1
        line = _resolve_line(country, source_path, reference)
        row["矫正条线"] = line
        if line:
            stats["line_filled"] += 1
        else:
            stats["unresolved_line"] += 1

        source_channel = _text(row.get("渠道"))
        special_channel = SPECIAL_CHANNEL_RULES.get(source_path)
        first_channel = special_channel[0] if special_channel else reference.path_to_first_channel.get(source_path)
        corrected_channel = special_channel[1] if special_channel else reference.path_channel_to_corrected_channel.get((source_path, source_channel))
        if first_channel:
            if _text(row.get("一级渠道")) != first_channel:
                stats["first_channel_updates"] += 1
            row["一级渠道"] = first_channel
        if corrected_channel:
            if _text(row.get("二级渠道")) != corrected_channel:
                stats["second_channel_updates"] += 1
            row["二级渠道"] = corrected_channel
        else:
            stats["unresolved_channel"] += 1
        if include_audit:
            row["留学渠道清洗状态"] = "已命中" if first_channel and corrected_channel else "当前规则未命中"

    return rows, dict(stats)


__all__ = [
    "OUTPUT_COLUMNS",
    "AUDIT_COLUMNS",
    "WorkOrderReference",
    "channel_scope",
    "clean_work_order_rows",
    "load_work_order_reference",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="merged work-order workbook")
    parser.add_argument("--output", type=Path, required=True, help="cleaned workbook output")
    parser.add_argument("--mapping", type=Path, required=True, help="留学-FY26-资源表.xlsx")
    args = parser.parse_args()

    from data_acquisition.jobs.bi_window_merge import _read_xlsx_rows, _write_xlsx

    sheet_name, columns, rows = _read_xlsx_rows(args.input)
    cleaned, stats = clean_work_order_rows(rows, load_work_order_reference(args.mapping))
    for column in OUTPUT_COLUMNS:
        if column not in columns:
            columns.append(column)
    _write_xlsx(args.output, columns, cleaned, sheet_name)
    print(json.dumps({"status": "cleaned", "output": str(args.output), **stats}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
