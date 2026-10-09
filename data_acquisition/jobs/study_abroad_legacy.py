"""Read the June-August FY27 study-abroad market exports in their old layouts.

This parser is deliberately limited to the three verified workbook formats. It
keeps source lineage and missing business identifiers so a downstream builder
can apply the current roster and identity rules explicitly.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel


_SCHEMA = "study_abroad_legacy_history.v1"
_JUNE_NAME = "FY27-6月市场绩效（带颜色）.xlsx"
_JULY_NAME = "27财7月资源&签约-市场版.xlsx"
_AUGUST_NAME = "27财8月资源&签约（市场版）.xlsx"
_EXPECTED_MONTH = {6: "2026-06", 7: "2026-07", 8: "2026-08"}

_SHEETS = {
    6: {"resources": ("crm", "91"), "contracts": ("留学签约",), "languages": ("语培签约",)},
    7: {
        "resources": ("crm (核算)", "91 (核算)"),
        "contracts": ("留学签约 (核算)",),
        "languages": ("语培签约 (核算)",),
    },
    8: {"resources": ("资源",), "contracts": ("留学签约",), "languages": ("语培签约",)},
}


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _header_key(value: object) -> str:
    return re.sub(r"\s+", "", _text(value)).casefold()


def _file_month(path: Path, override: int | None = None) -> int:
    detected = None
    if path.name == _JUNE_NAME:
        detected = 6
    elif path.name == _JULY_NAME:
        detected = 7
    elif path.name == _AUGUST_NAME:
        detected = 8
    if detected is not None:
        if override is not None and override != detected:
            raise ValueError("显式月份与留学历史工作簿文件名不一致")
        return detected
    if override in _EXPECTED_MONTH:
        return override
    raise ValueError(f"未支持的留学历史工作簿名称：{path.name}")


def _paths(value: str | Path | Iterable[str | Path], month: int | None = None) -> list[Path]:
    if isinstance(value, (str, Path)):
        result = [Path(value)]
    else:
        result = [Path(item) for item in value]
    if not result:
        raise ValueError("至少需要一个留学历史工作簿")
    if month is not None and (len(result) != 1 or month not in _EXPECTED_MONTH):
        raise ValueError("month 仅可用于单个工作簿，并且必须为 6、7 或 8")
    months = [_file_month(path, month) for path in result]
    if len(months) != len(set(months)):
        raise ValueError("留学历史工作簿月份重复")
    return [path for _, path in sorted(zip(months, result), key=lambda item: item[0])]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _column(headers: list[object], *labels: str, required: bool = False) -> int | None:
    normalized = [_header_key(header) for header in headers]
    for label in labels:
        matches = [index for index, value in enumerate(normalized) if value == _header_key(label)]
        if len(matches) > 1:
            raise ValueError(f"留学历史表头重复：{label}")
        if matches:
            return matches[0]
    if required:
        raise ValueError(f"留学历史工作表缺少关键字段：{' / '.join(labels)}")
    return None


def _header_row(sheet, row_number: int) -> tuple[list[object], int]:
    headers = [cell.value for cell in sheet.iter_rows(
        min_row=row_number, max_row=row_number, values_only=False
    ).__next__()]
    last = max((index for index, value in enumerate(headers, 1) if not _blank(value)), default=0)
    return headers[:last], last


def _fill_signature(fill: object) -> tuple[object, ...] | None:
    pattern = getattr(fill, "patternType", None)
    color = getattr(fill, "fgColor", None)
    color_type = getattr(color, "type", None)
    color_value = getattr(color, "value", None)
    tint = float(getattr(color, "tint", 0.0) or 0.0)
    if not pattern or not color_type or color_value is None:
        return None
    return pattern, color_type, color_value, tint


def _legend(sheet, *, header_width: int) -> dict[tuple[object, ...], str]:
    # The legend may be wider than the header (and some files format thousands
    # of unused columns), so inspect only cells actually stored in row one.
    cells = [cell for (row, _column_number), cell in sheet._cells.items()
             if row == 1 and not _blank(cell.value)]
    cells.sort(key=lambda cell: cell.column)
    signatures: dict[tuple[object, ...], str] = {}
    for cell in cells:
        owner = _text(cell.value)
        signature = _fill_signature(cell.fill)
        if signature is None:
            raise ValueError(f"{sheet.title} 的颜色图例存在未着色项（第1行）")
        prior_owner = signatures.get(signature)
        if prior_owner is not None and prior_owner != owner:
            raise ValueError(f"{sheet.title} 的颜色图例填充无法唯一映射归属人")
        signatures[signature] = owner
    if not signatures:
        raise ValueError(f"{sheet.title} 缺少第1行颜色图例")
    return signatures


def _colored_owner(sheet, row_number: int,
                   signatures: Mapping[tuple[object, ...], str], stats: dict,
                   row_fills: Mapping[int, list[tuple[object, ...]]]) -> str | None:
    owners: set[str] = set()
    # Row fills can extend past the last header cell. Index stored cells once
    # so wide formatted templates do not require scanning thousands of columns.
    for signature in row_fills.get(row_number, []):
        owner = signatures.get(signature)
        if owner is None:
            stats["unknown_color_cells"] += 1
        else:
            owners.add(owner)
    if len(owners) > 1:
        raise ValueError(f"{sheet.title} 第{row_number}行含多个已知归属人颜色")
    if not owners:
        stats["uncolored_or_unknown_owner_rows"] += 1
        return None
    return next(iter(owners))


def _parse_date(value: object, epoch: object) -> date | None:
    if _blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            converted = from_excel(value, epoch)
        except (ValueError, OverflowError):
            return None
        return converted.date() if isinstance(converted, datetime) else converted
    text = _text(value)
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        try:
            converted = from_excel(float(text), epoch)
        except (ValueError, OverflowError):
            converted = None
        if isinstance(converted, datetime):
            return converted.date()
        if isinstance(converted, date):
            return converted
    for candidate in (text[:10], text):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _day_component(value: object, epoch: object) -> int | None:
    if _blank(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.day
    if isinstance(value, (int, float)):
        if value > 31:
            parsed = _parse_date(value, epoch)
            return parsed.day if parsed else None
        return int(value) if int(value) == value else None
    text = _text(value)
    try:
        component = int(text)
        if component > 31:
            parsed = _parse_date(component, epoch)
            return parsed.day if parsed else None
        return component
    except ValueError:
        parsed = _parse_date(text, epoch)
        return parsed.day if parsed else None


def _month_component(value: object, epoch: object) -> int | None:
    if _blank(value):
        return None
    if isinstance(value, (int, float)):
        if int(value) == value and value <= 12:
            return int(value)
        parsed = _parse_date(value, epoch)
        return parsed.month if parsed else None
    match = re.fullmatch(r"\s*(\d{1,2})(?:\.0)?\s*", _text(value))
    if match:
        return int(match.group(1))
    parsed = _parse_date(value, epoch)
    return parsed.month if parsed else None


def _identifier(value: object) -> str | None:
    text = _text(value)
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text if text and text not in {"/", "None", "null"} else None


def _money_decimal(value: object) -> Decimal | None:
    if _blank(value):
        return None
    text = _text(value).replace(",", "").replace("￥", "").replace("¥", "")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _infer_consultation_type(line: object, stage: object, country: object = None) -> str | None:
    line_text, stage_text = _text(line), _text(stage)
    normalized = f"{line_text} {stage_text}"
    language_markers = ("语培", "小语种", "日语", "韩语", "语言培训")
    study_markers = (
        "留学", "申请", "本科", "研究生", "硕士", "博士", "中学", "高中", "预科",
        "英美", "美本", "加本", "澳新", "英国", "美国", "加拿大", "日本", "韩国", "港澳",
        "亚洲", "日韩", "欧亚", "欧洲",
    )
    if any(marker in normalized for marker in language_markers):
        return "小语种"
    if any(marker in normalized for marker in study_markers):
        return "留学"
    if _text(country) == "加拿大":
        return "留学"
    return None


def _record_values(sheet, row_number: int, width: int) -> list[object]:
    return [sheet.cell(row_number, column_number).value for column_number in range(1, width + 1)]


def _value(values: list[object], columns: Mapping[str, int | None], key: str) -> object:
    index = columns.get(key)
    return values[index] if index is not None and index < len(values) else None


def _lineage(*, row: int, sheet_name: str, filename: str, file_hash: str) -> dict:
    return {
        "source_row_number": row,
        "origin_filename": filename,
        "origin_sheet": sheet_name,
        "origin_sha256": file_hash,
        "origin_row_number": row,
        # This identifies a physical workbook row only; it is never a business ID.
        "technical_record_key": f"{file_hash}:{sheet_name}:{row}",
    }


def _identity_fields(identifier: object, name: object) -> dict:
    normalized_id = _identifier(identifier)
    customer_name = _text(name) or None
    return {
        "customer_identity_available": bool(normalized_id),
        "customer_identity_basis": "id" if normalized_id else "name" if customer_name else None,
        "customer_name": customer_name,
    }


def _record_stats() -> dict:
    return {
        "rows": 0,
        "date_missing": 0,
        "date_outside_expected_month": 0,
        "amount_sum": Decimal("0"),
        "amount_missing": 0,
        "amount_invalid": 0,
        "missing_resource_id": 0,
        "missing_contract_id": 0,
        "missing_customer_id": 0,
        "missing_student_id": 0,
        "missing_work_order_id": 0,
        "missing_record_id": 0,
        "uncolored_or_unknown_owner_rows": 0,
        "unknown_color_cells": 0,
        "consultation_type_unresolved": 0,
        "date_pair_conflicts": 0,
        "template_rows_excluded": 0,
        "date_values": [],
        "has_amount": False,
    }


def _summarize_stats(stats: dict) -> dict:
    dates = stats.pop("date_values")
    result = {key: value for key, value in stats.items() if key not in {"amount_sum"}}
    result["amount_sum"] = format(stats["amount_sum"].quantize(Decimal("0.01")), ".2f")
    result["date_min"] = min(dates).isoformat() if dates else None
    result["date_max"] = max(dates).isoformat() if dates else None
    return result


def _append_rows(
    *, kind: str, sheet: object, filename: str, file_hash: str, month: int,
    layout: str, header_row: int, out: list[dict], stats_by_sheet: dict,
    stats_key: str,
) -> None:
    headers, width = _header_row(sheet, header_row)
    headers = headers[:width]
    stats = _record_stats()
    stats_by_sheet[stats_key] = stats

    if layout == "june" and kind in {"resources", "contracts", "languages"}:
        colors = _legend(sheet, header_width=width)
        row_fills: dict[int, list[tuple[object, ...]]] = defaultdict(list)
        for (row_number, _column_number), cell in sheet._cells.items():
            signature = _fill_signature(cell.fill)
            if signature is not None:
                row_fills[row_number].append(signature)
    else:
        colors = None
        row_fills = {}

    def col(*labels: str, required: bool = False) -> int | None:
        return _column(headers, *labels, required=required)

    if layout == "june" and sheet.title == "crm":
        columns = {
            "date": col("创建时间", required=True), "line": col("条线"),
            "stage": col("意向阶段"), "country": col("意向国家或地区"),
            "first_channel": col("来访类型"), "second_channel": col("来源渠道"),
            "third_channel": col("渠道明细"), "status": col("资源状态"),
            "description": col("资源名称"),
        }
    elif layout == "june" and sheet.title == "91":
        columns = {
            "date": col("分配时间", required=True), "resource_id": col("资源ID"),
            "work_order_id": col("工单ID"), "customer_id": col("客户ID"),
            "consultation_type": col("咨询类型"), "status": col("工单状态"),
            "first_channel": col("一级获取渠道"), "second_channel": col("二级获取渠道"),
            "third_channel": col("三级获取渠道"), "campaign": col("市场活动"),
            "country": col("意向国家"), "stage": col("意向阶段"),
            "description": col("资源描述", "91资源描述"),
        }
    elif layout == "june" and kind == "contracts":
        columns = {
            "contract_id": col("合同编号", required=True), "date": col("归档日期", required=True),
            "amount": col("签约金额", required=True), "customer_name": col("签约客户姓名"),
            "first_channel": col("来访类型"), "second_channel": col("来源渠道"),
            "third_channel": col("渠道明细"), "status": col("合同状态"),
        }
    elif layout == "june" and kind == "languages":
        columns = {
            "date": col("日期", required=True), "amount": col("签约金额", required=True),
            "customer_name": col("姓名"), "business_type": col("业务类型"),
            "language": col("语种"), "first_channel": col("一级获取渠道"),
            "second_channel": col("二级获取渠道"), "third_channel": col("三级获取渠道"),
            "signup_type": col("新签/续签"),
        }
    elif layout == "july" and sheet.title == "crm (核算)":
        columns = {
            "date": col("创建时间", required=True), "resource_id": col("记录ID", required=True),
            "record_id": col("记录ID", required=True),
            "source_group": col("大类归属"), "owner": col("资源归属人"),
            "line": col("条线"), "stage": col("意向阶段"),
            "country": col("意向国家或地区"), "first_channel": col("来访类型"),
            "second_channel": col("来源渠道"), "third_channel": col("渠道明细"),
            "status": col("资源状态"), "description": col("资源名称"),
        }
    elif layout == "july" and sheet.title == "91 (核算)":
        columns = {
            "date": col("分配时间", required=True), "resource_id": col("资源ID", required=True),
            "work_order_id": col("工单ID"), "customer_id": col("客户ID"),
            "owner": col("资源归属人"), "source_group": col("大类归属"),
            "consultation_type": col("咨询类型"), "status": col("工单状态"),
            "campaign": col("市场活动"), "first_channel": col("一级获取渠道"),
            "second_channel": col("二级获取渠道"), "third_channel": col("三级获取渠道"),
            "description": col("资源描述"),
        }
    elif layout == "july" and kind == "contracts":
        columns = {
            "record_id": col("记录id"), "contract_id": col("合同编号", required=True),
            "date": col("归档日期", required=True), "amount": col("签约金额", required=True),
            "owner": col("签约归属"), "source_group": col("大类归属"),
            "customer_id": col("客户ID"), "customer_name": col("签约客户姓名"),
            "first_channel": col("来访类型"), "second_channel": col("来源渠道"),
            "third_channel": col("渠道明细"), "campaign": col("91资源市场活动"),
        }
    elif layout == "july" and kind == "languages":
        date_columns = [index for index, header in enumerate(headers)
                        if _header_key(header) == _header_key("日期")]
        if len(date_columns) != 2:
            raise ValueError("7月语培签约必须包含两个“日期”字段")
        columns = {
            "date_part": date_columns[0], "date_full": date_columns[1],
            "month": col("月份"), "amount": col("签约金额", required=True),
            "owner": col("签约归属"), "source_group": col("大类归属"),
            "customer_name": col("姓名"), "business_type": col("业务类型"),
            "language": col("语种"), "student_id": col("学员编号"),
            "resource_id": col("资源ID"), "work_order_id": col("工单ID"),
            "signup_type": col("新签/续签"),
        }
    elif layout == "august" and kind == "resources":
        columns = {
            "date": col("分配时间", required=True), "resource_id": col("资源ID", required=True),
            "work_order_id": col("工单ID"), "customer_id": col("客户ID"),
            "source_group": col("归属大类", required=True), "owner": col("资源归属", required=True),
            "consultation_type": col("咨询类型（优化后）", required=True),
            "status": col("工单状态"), "campaign": col("市场活动"),
            "first_channel": col("一级获取渠道"), "second_channel": col("二级获取渠道"),
            "third_channel": col("三级获取渠道"), "country": col("意向国家/地区"),
            "stage": col("意向阶段"), "description": col("资源描述"),
        }
    elif layout == "august" and kind == "contracts":
        columns = {
            "record_id": col("记录id"), "contract_id": col("合同编号", required=True),
            "date": col("归档日期", required=True), "owner": col("签约归属", required=True),
            "source_group": col("归属大类", required=True), "amount": col("签约金额", required=True),
            "customer_id": col("客户ID"), "customer_name": col("签约客户姓名"),
            "first_channel": col("来访类型"), "second_channel": col("来源渠道"),
            "third_channel": col("渠道明细"), "campaign": col("91资源市场活动"),
        }
    elif layout == "august" and kind == "languages":
        columns = {
            "date": col("业务日期", required=True), "owner": col("签约归属", required=True),
            "source_group": col("归属大类", required=True), "amount": col("实缴金额", required=True),
            "student_id": col("学员编号"), "customer_name": col("姓名"),
            "language": col("语种"), "business_type": col("业务类型"),
            "resource_id": col("资源ID"), "work_order_id": col("工单ID"),
            "signup_type": col("新签/续签"),
        }
    else:
        raise ValueError(f"{sheet.title} 与已核实的留学历史布局不匹配")

    stats["has_amount"] = columns.get("amount") is not None

    signal_keys = [key for key in columns if key not in {"date_part", "date_full", "month"}]
    first_data_row = header_row + 1
    for row_number in range(first_data_row, sheet.max_row + 1):
        values = _record_values(sheet, row_number, width)
        if not any(not _blank(_value(values, columns, key)) for key in signal_keys):
            stats["template_rows_excluded"] += 1
            continue

        raw_date = _value(values, columns, "date")
        date_value = _parse_date(raw_date, sheet.parent.epoch)
        date_pair_consistent = None
        date_pair_raw = None
        if "date_part" in columns:
            raw_day = _value(values, columns, "date_part")
            raw_full = _value(values, columns, "date_full")
            full_date = _parse_date(raw_full, sheet.parent.epoch)
            month_value = _month_component(_value(values, columns, "month"), sheet.parent.epoch)
            day_value = _day_component(raw_day, sheet.parent.epoch)
            date_pair_consistent = bool(
                full_date and day_value == full_date.day
                and (month_value is None or month_value == full_date.month)
            )
            date_pair_raw = {"date_component": raw_day, "date_full": raw_full}
            date_value = full_date if date_pair_consistent else None
            if not date_pair_consistent:
                stats["date_pair_conflicts"] += 1

        if date_value is None:
            stats["date_missing"] += 1
        elif date_value.strftime("%Y-%m") != _EXPECTED_MONTH[month]:
            stats["date_outside_expected_month"] += 1
            raise ValueError(f"{filename} 的 {sheet.title} 存在非{_EXPECTED_MONTH[month]}业务日期")
        else:
            stats["date_values"].append(date_value)

        owner = _value(values, columns, "owner")
        if colors is not None:
            owner = _colored_owner(sheet, row_number, colors, stats, row_fills)
        owner_text = _text(owner) or None
        source_group = _text(_value(values, columns, "source_group")) or None
        resource_id = _identifier(_value(values, columns, "resource_id"))
        work_order_id = _identifier(_value(values, columns, "work_order_id"))
        contract_id = _identifier(_value(values, columns, "contract_id"))
        record_id = _identifier(_value(values, columns, "record_id"))
        customer_id = _identifier(_value(values, columns, "customer_id"))
        student_id = _identifier(_value(values, columns, "student_id"))
        customer_name = _text(_value(values, columns, "customer_name")) or None
        business_type = _value(values, columns, "business_type")
        language = _value(values, columns, "language")
        if language is None and layout in {"june", "july"} and kind == "languages":
            # The June and July exports use business_type for the language.
            language = business_type
        identity_value = student_id if kind == "languages" else customer_id
        identity = _identity_fields(identity_value, customer_name) if kind != "resources" else {}

        record = {
            **_lineage(row=row_number, sheet_name=sheet.title, filename=filename,
                       file_hash=file_hash),
            "resource_id": resource_id if kind != "contracts" or record_id is None else record_id,
            "record_id": record_id,
            "contract_id": contract_id,
            "customer_id": customer_id,
            "student_id": student_id,
            "work_order_id": work_order_id,
            "date": date_value,
            "date_full_candidate": full_date if "date_part" in columns else None,
            "date_component_candidate": date(2026, month, day_value) if "date_part" in columns and day_value else None,
            "archive_date": date_value if kind == "contracts" else None,
            "month": date_value.strftime("%Y-%m") if kind == "contracts" and date_value else None,
            "owner": owner_text,
            "source_group": source_group,
            "amount": _value(values, columns, "amount"),
            "customer_name": customer_name,
            "consultation_type": _value(values, columns, "consultation_type"),
            "status": _value(values, columns, "status"),
            "campaign": _value(values, columns, "campaign"),
            "country": _value(values, columns, "country"),
            "stage": _value(values, columns, "stage"),
            "business_line": _value(values, columns, "line"),
            "description": _value(values, columns, "description"),
            "first_channel": _value(values, columns, "first_channel"),
            "second_channel": _value(values, columns, "second_channel"),
            "third_channel": _value(values, columns, "third_channel"),
            "business_type": business_type,
            # Keep the source field as business_type even when it also supplies
            # the language enum in the June/July layouts.
            "language": language,
            "signup_type": _value(values, columns, "signup_type"),
            "customer_identity_available": identity.get("customer_identity_available"),
            "customer_identity_basis": identity.get("customer_identity_basis"),
        }
        if kind == "resources" and record["consultation_type"] is None:
            inferred = _infer_consultation_type(record["business_line"], record["stage"], record.get("country"))
            record["consultation_type"] = inferred
            if inferred is None:
                stats["consultation_type_unresolved"] += 1
        if date_pair_raw is not None:
            record.update(date_pair_raw)
            record["date_pair_consistent"] = date_pair_consistent
        if kind == "resources" and not resource_id:
            stats["missing_resource_id"] += 1
        if kind == "contracts":
            if not contract_id:
                stats["missing_contract_id"] += 1
            if not record_id:
                stats["missing_record_id"] += 1
            if not customer_id:
                stats["missing_customer_id"] += 1
        if kind == "languages":
            if not student_id:
                stats["missing_student_id"] += 1
            if not work_order_id:
                stats["missing_work_order_id"] += 1
            if identity_value is None:
                stats["missing_customer_id"] += 1

        amount_value = _value(values, columns, "amount")
        if columns.get("amount") is not None:
            amount = _money_decimal(amount_value)
            if amount is None:
                if _blank(amount_value):
                    stats["amount_missing"] += 1
                else:
                    stats["amount_invalid"] += 1
            else:
                stats["amount_sum"] += amount
        stats["rows"] += 1
        out.append(record)


def _derive_group_mapping(rows: Iterable[dict], supplied: Mapping[str, str] | None) -> tuple[list[dict], int]:
    groups: dict[str, set[str]] = defaultdict(set)
    first_row: dict[tuple[str, str], int] = {}
    for row in rows:
        owner = _text(row.get("owner"))
        source_group = _text(row.get("source_group"))
        if owner and source_group:
            groups[owner].add(source_group)
            first_row.setdefault((owner, source_group), row["source_row_number"])
    conflicts = sum(len(values) > 1 for values in groups.values())
    result = []
    for owner, values in groups.items():
        if len(values) == 1:
            group = next(iter(values))
            result.append({"source_row_number": first_row[(owner, group)], "owner": owner,
                           "source_group": group})
    if supplied:
        for owner, source_group in supplied.items():
            owner_text, group_text = _text(owner), _text(source_group)
            if not owner_text or not group_text or owner_text in groups:
                continue
            result.append({"source_row_number": None, "owner": owner_text,
                           "source_group": group_text, "mapping_source": "explicit_input"})
    return result, conflicts


def read_legacy_sources(source_paths: str | Path | Iterable[str | Path], *,
                        month: int | None = None,
                        groups: Mapping[str, str] | None = None) -> dict:
    """Read one or more explicitly named June-August FY27 legacy workbooks.

    ``groups`` may provide an explicit owner-to-group fallback. It is used only
    when the source rows contain no group for that owner; conflicting source
    groups remain unresolved and are reported in diagnostics.
    """
    paths = _paths(source_paths, month)
    resources: list[dict] = []
    contracts: list[dict] = []
    languages: list[dict] = []
    stats_by_sheet: dict[str, dict] = {}
    file_meta = []
    source_sheets_by_kind: dict[str, list[str]] = {key: [] for key in _SHEETS[6]}
    month_by_path = {path: _file_month(path) for path in paths}

    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        month = month_by_path[path]
        layout = {6: "june", 7: "july", 8: "august"}[month]
        file_hash_before = _sha256(path)
        book = load_workbook(path, read_only=False, data_only=True)
        try:
            expected = _SHEETS[month]
            for kind, names in expected.items():
                if any(name not in book.sheetnames for name in names):
                    raise ValueError(f"{path.name} 缺少已核实的{kind}工作表")
                for sheet_name in names:
                    source_sheets_by_kind[kind].append(sheet_name)
                    target = {"resources": resources, "contracts": contracts,
                              "languages": languages}[kind]
                    _append_rows(kind=kind, sheet=book[sheet_name], filename=path.name,
                                 file_hash=file_hash_before, month=month, layout=layout,
                                 header_row=2 if month == 6 else 1, out=target,
                                 stats_by_sheet=stats_by_sheet,
                                 stats_key=f"{path.name}::{sheet_name}")
        finally:
            book.close()
        file_hash_after = _sha256(path)
        if file_hash_after != file_hash_before:
            raise ValueError(f"{path.name} 在读取期间发生变化")
        file_meta.append({
            "path": str(path), "filename": path.name,
            "sha256": file_hash_before, "month": _EXPECTED_MONTH[month],
            "source_sheets": {kind: list(names) for kind, names in _SHEETS[month].items()},
        })

    group_mapping, mapping_conflicts = _derive_group_mapping(
        [*resources, *contracts, *languages], groups
    )
    if len(file_meta) == 1:
        source_hash = file_meta[0]["sha256"]
    else:
        identity = {"schema": _SCHEMA, "ordered_sha256": [item["sha256"] for item in file_meta]}
        source_hash = hashlib.sha256(json.dumps(
            identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()

    summary = {name: _summarize_stats(stats) for name, stats in stats_by_sheet.items()}
    source_sheets = {
        kind: ";".join(dict.fromkeys(sheet_names)) for kind, sheet_names in source_sheets_by_kind.items()
    }
    source_sheets["group_mapping"] = "derived from explicit source groups"
    return {
        "resources": resources,
        "contracts": contracts,
        "languages": languages,
        "group_mapping": group_mapping,
        "source_sheets": source_sheets,
        "source_sha256": source_hash,
        "source_path": str(paths[0]),
        "source_files": file_meta,
        "historical_import": True,
        "diagnostics": {
            "schema": _SCHEMA,
            "expected_months": [_EXPECTED_MONTH[month_by_path[path]] for path in paths],
            "by_sheet": summary,
            "group_mapping_conflicts": mapping_conflicts,
            "real_aggregate": {
                "rows": {"resources": len(resources), "contracts": len(contracts),
                         "languages": len(languages)},
                "amount_sum_by_sheet": {
                    name: values["amount_sum"] for name, values in summary.items()
                    if values["has_amount"]
                },
                "date_columns_and_ranges": {
                    name: {"date_min": values["date_min"], "date_max": values["date_max"],
                           "date_missing": values["date_missing"],
                           "date_pair_conflicts": values["date_pair_conflicts"]}
                    for name, values in summary.items()
                },
                "uncolored_owner_rows": {
                    name: values["uncolored_or_unknown_owner_rows"]
                    for name, values in summary.items()
                    if values["uncolored_or_unknown_owner_rows"]
                },
                "missing_ids": {
                    name: {key: values[key] for key in (
                        "missing_resource_id", "missing_record_id", "missing_contract_id",
                        "missing_customer_id", "missing_student_id", "missing_work_order_id",
                    ) if values[key]}
                    for name, values in summary.items()
                    if any(values[key] for key in (
                        "missing_resource_id", "missing_record_id", "missing_contract_id",
                        "missing_customer_id", "missing_student_id", "missing_work_order_id",
                    ))
                },
            },
        },
    }

