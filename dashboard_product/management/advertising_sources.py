"""只读解析投放费用来源；不读取业务事实或连接数据仓库。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from .platforms import canonical_platform


_KINDS = {"xhs_daily", "ocean_daily", "network_weekly", "sem_daily", "xhs_mcc_daily"}
_BUSINESS_LINES = {"training", "abroad"}
_BUSINESS_GROUPS = {"留学预备", "高中", "大学", "留学整体"}
_DAILY_PLATFORMS = {"小红书", "抖音"}
_DAILY_KEY_COLUMNS = ("项目ID", "日期", "投放类型", "营销场景")
_CONTROL_LABELS = ("合计", "总计", "小计", "汇总")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_TOTAL_TOLERANCE = Decimal("0.011")


def load_sources(manifest_path: Path | None) -> dict[str, Any]:
    """加载清单中声明的投放费用文件；不配置清单是合法的缺失业务状态。"""
    if manifest_path is None:
        return {"rows": [], "sources": [], "configured": False}

    manifest = Path(manifest_path)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if (not isinstance(manifest_data, dict) or "sources" not in manifest_data
            or not set(manifest_data).issubset({"sources", "network_period_differences"})):
        raise ValueError("费用manifest必须包含sources，且只允许network_period_differences扩展字段")
    entries = manifest_data["sources"]
    if not isinstance(entries, list):
        raise ValueError("费用manifest的sources必须是数组")

    validated = []
    source_ids: set[str] = set()
    physical_files: dict[tuple[int, int], str] = {}
    content_hashes: dict[str, str] = {}
    for index, entry in enumerate(entries, start=1):
        item = _validate_manifest_entry(entry, index)
        source_id = item["source_id"]
        if source_id in source_ids:
            raise ValueError(f"manifest中source_id重复: {source_id}")
        source_ids.add(source_id)

        raw_path = Path(item["path"])
        path = (raw_path if raw_path.is_absolute() else manifest.parent / raw_path).resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"费用来源不是普通文件: {path}")
        item["resolved_path"] = path

        stat = path.stat()
        physical_id = (stat.st_dev, stat.st_ino)
        previous_id = physical_files.get(physical_id)
        if previous_id is not None:
            raise ValueError(f"同一物理费用文件被多个source_id重复提供: {previous_id}, {source_id}")
        physical_files[physical_id] = source_id

        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        previous_hash = content_hashes.get(digest)
        if previous_hash is not None:
            raise ValueError(f"相同sha256的费用文件被多个source_id重复提供: {previous_hash}, {source_id}")
        content_hashes[digest] = source_id
        if item.get("sha256") is not None and item["sha256"].lower() != digest:
            raise ValueError(f"费用来源sha256不匹配: {source_id}")
        item["raw"] = raw
        item["actual_sha256"] = digest
        validated.append(item)

    differences = _validate_network_period_differences(
        manifest_data.get("network_period_differences", []), validated, source_ids
    )
    cumulative_ids = {item["cumulative_source_id"] for item in differences}

    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    parsed_network: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for item in validated:
        if item["kind"] == "xhs_daily":
            parsed_rows, parsed_sources = _parse_daily(item, date_header="时间", amount_header="消费")
        elif item["kind"] == "ocean_daily":
            parsed_rows, parsed_sources = _parse_daily(item, date_header="日期", amount_header="消耗(元)", ocean=True)
        elif item["kind"] == "xhs_mcc_daily":
            from .xhs_sources import parse_xhs_mcc
            parsed_rows, parsed_sources = parse_xhs_mcc(item)
        elif item["kind"] == "sem_daily":
            from .sem_sources import parse_sem
            parsed_rows, parsed_sources = parse_sem(item)
        else:
            parsed_rows, parsed_sources = _parse_network_weekly(item)
            parsed_network[item["source_id"]] = (parsed_rows, parsed_sources)
            if item["source_id"] in cumulative_ids:
                continue
        rows.extend(parsed_rows)
        sources.extend(parsed_sources)

    source_by_id = {item["source_id"]: item for item in validated}
    for difference in differences:
        derived_rows, derived_sources = _derive_network_period_difference(
            difference,
            source_by_id[difference["cumulative_source_id"]],
            parsed_network[difference["cumulative_source_id"]][0],
            source_by_id[difference["current_source_id"]],
            parsed_network[difference["current_source_id"]][0],
        )
        rows.extend(derived_rows)
        sources.extend(derived_sources)

    # 新流水替代旧期间表的明确平台；差额派生先用完整原表计算，保留其他历史月份。
    excluded = {(item["source_id"], platform) for item in validated
                for platform in item.get("exclude_platforms", [])}
    excluded.update((item["source_id"], platform) for item in differences
                    for platform in item.get("exclude_platforms", []))
    rows = [row for row in rows if (row["source_id"], row["platform"]) not in excluded]
    sources = [source for source in sources if (source["source_id"], source["platform"]) not in excluded]
    for row in rows:
        row.pop("_amount_decimal", None)

    unique_sources: dict[tuple[str, str], dict[str, Any]] = {}
    for source in sources:
        key = (source["source_id"], source["platform"])
        if key in unique_sources:
            raise ValueError(f"来源元数据重复: {key[0]} / {key[1]}")
        unique_sources[key] = source
    return {"rows": rows, "sources": sources, "configured": True}


def _validate_manifest_entry(entry: Any, index: int) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(f"manifest sources[{index - 1}]必须是对象")
    if entry.get("kind") == "xhs_mcc_daily":
        from .xhs_sources import validate_xhs_mcc_entry
        return validate_xhs_mcc_entry(entry)
    if entry.get("kind") == "sem_daily":
        from .sem_sources import validate_sem_entry
        return validate_sem_entry(entry)
    allowed = {"source_id", "path", "kind", "business_line", "business_group", "platform", "sha256", "company", "exclude_platforms"}
    required = {"source_id", "path", "kind", "business_line", "business_group"}
    if not required.issubset(entry) or not set(entry).issubset(allowed):
        missing = sorted(required - set(entry))
        extra = sorted(set(entry) - allowed)
        raise ValueError(f"manifest sources[{index - 1}]字段无效；缺少={missing}，多余={extra}")

    source_id = entry["source_id"]
    path = entry["path"]
    kind = entry["kind"]
    business_line = entry["business_line"]
    business_group = entry["business_group"]
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError(f"manifest sources[{index - 1}].source_id必须是非空字符串")
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"manifest sources[{index - 1}].path必须是非空字符串")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise ValueError(f"manifest sources[{index - 1}].kind无效: {kind}")
    if (not isinstance(business_line, str) or business_line not in _BUSINESS_LINES
            or not isinstance(business_group, str) or business_group not in _BUSINESS_GROUPS):
        raise ValueError(f"manifest sources[{index - 1}]的业务线或业务组无效")
    expected_line = "abroad" if business_group == "留学整体" else "training"
    if business_line != expected_line:
        raise ValueError(f"业务组{business_group}必须归属business_line={expected_line}")

    platform = entry.get("platform")
    if kind in {"xhs_daily", "ocean_daily"}:
        if not isinstance(platform, str) or platform not in _DAILY_PLATFORMS:
            raise ValueError(f"日报来源{source_id}必须声明有效platform")
        expected_platform = "小红书" if kind == "xhs_daily" else "抖音"
        if platform != expected_platform:
            raise ValueError(f"{kind}来源{source_id}的platform必须是{expected_platform}")
    elif platform is not None and (not isinstance(platform, str) or platform not in _DAILY_PLATFORMS):
        raise ValueError(f"network_weekly来源{source_id}的platform无效")

    sha256 = entry.get("sha256")
    if sha256 is not None and (not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256)):
        raise ValueError(f"manifest sources[{index - 1}].sha256必须是64位十六进制")

    company = entry.get("company")
    if company is not None and (not isinstance(company, str) or not company.strip()):
        raise ValueError(f"manifest sources[{index - 1}].company必须是非空字符串")
    if company is not None and kind != "network_weekly":
        raise ValueError(f"manifest sources[{index - 1}].company仅支持network_weekly来源")

    exclusions = entry.get("exclude_platforms", [])
    if (not isinstance(exclusions, list) or any(not isinstance(p, str) or not p.strip() for p in exclusions)
            or (exclusions and kind != "network_weekly")):
        raise ValueError("exclude_platforms只支持网络期间来源的明确平台清单")

    return {
        "source_id": source_id,
        "path": path,
        "kind": kind,
        "business_line": business_line,
        "business_group": business_group,
        "platform": platform,
        "sha256": sha256,
        "company": company.strip() if company is not None else None,
        "exclude_platforms": exclusions,
    }


def _validate_network_period_differences(
    entries: Any, sources: list[dict[str, Any]], source_ids: set[str]
) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ValueError("manifest的network_period_differences必须是数组")
    source_by_id = {item["source_id"]: item for item in sources}
    result: list[dict[str, Any]] = []
    derived_ids: set[str] = set()
    used_input_ids: set[str] = set()
    required = {
        "source_id", "cumulative_source_id", "current_source_id",
        "start_date", "end_date", "missing_current_channel_policy",
    }
    for index, entry in enumerate(entries, start=1):
        if (not isinstance(entry, dict) or not required.issubset(entry)
                or set(entry) - required - {"exclude_platforms"}):
            raise ValueError(
                f"manifest network_period_differences[{index - 1}]字段无效；必须包含={sorted(required)}"
            )
        derived_id = entry["source_id"]
        cumulative_id = entry["cumulative_source_id"]
        current_id = entry["current_source_id"]
        if any(not isinstance(value, str) or not value.strip()
               for value in (derived_id, cumulative_id, current_id)):
            raise ValueError(f"网络费用差额关系{index}的来源ID必须是非空字符串")
        if derived_id in source_ids or derived_id in derived_ids:
            raise ValueError(f"网络费用差额source_id重复: {derived_id}")
        if cumulative_id == current_id or cumulative_id not in source_by_id or current_id not in source_by_id:
            raise ValueError(f"网络费用差额关系{derived_id}必须引用两个不同的已声明来源")
        if cumulative_id in used_input_ids or current_id in used_input_ids:
            raise ValueError(f"网络费用来源不能重复参与多个差额关系: {cumulative_id}, {current_id}")
        cumulative = source_by_id[cumulative_id]
        current = source_by_id[current_id]
        if cumulative["kind"] != "network_weekly" or current["kind"] != "network_weekly":
            raise ValueError(f"网络费用差额关系{derived_id}只支持network_weekly来源")
        if (cumulative["business_line"], cumulative["business_group"]) != ("abroad", "留学整体"):
            raise ValueError(f"网络费用差额关系{derived_id}累计来源必须归属留学整体")
        if (current["business_line"], current["business_group"]) != ("abroad", "留学整体"):
            raise ValueError(f"网络费用差额关系{derived_id}本月来源必须归属留学整体")
        if not cumulative.get("company") or cumulative.get("company") != current.get("company"):
            raise ValueError(f"网络费用差额关系{derived_id}必须声明相同的公司")
        if entry["missing_current_channel_policy"] != "zero_for_complete_source":
            raise ValueError(f"网络费用差额关系{derived_id}必须显式声明完整本月来源的缺失渠道按0处理")
        dates = {}
        for key in ("start_date", "end_date"):
            value = entry[key]
            if not isinstance(value, str):
                raise ValueError(f"网络费用差额关系{derived_id}.{key}必须是ISO日期")
            try:
                dates[key] = date.fromisoformat(value).isoformat()
            except ValueError as exc:
                raise ValueError(f"网络费用差额关系{derived_id}.{key}不是有效日期") from exc
        if dates["start_date"] > dates["end_date"]:
            raise ValueError(f"网络费用差额关系{derived_id}期间无效")
        exclusions = entry.get("exclude_platforms", [])
        if not isinstance(exclusions, list) or any(not isinstance(p, str) or not p.strip() for p in exclusions):
            raise ValueError("网络费用差额exclude_platforms必须是明确平台清单")
        normalized = {
            "source_id": derived_id,
            "cumulative_source_id": cumulative_id,
            "current_source_id": current_id,
            "start_date": dates["start_date"],
            "end_date": dates["end_date"],
            "missing_current_channel_policy": entry["missing_current_channel_policy"],
            "exclude_platforms": exclusions,
        }
        result.append(normalized)
        derived_ids.add(derived_id)
        used_input_ids.update((cumulative_id, current_id))
    return result


def _read_rows(raw: bytes, path: Path) -> tuple[list[tuple[Any, ...]], bool]:
    if raw.startswith(b"PK\x03\x04"):
        try:
            book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except (BadZipFile, OSError, ValueError) as exc:
            raise ValueError(f"无法读取OOXML费用来源: {path}") from exc
        try:
            sheet = book.active
            sheet.reset_dimensions()
            return [tuple(row) for row in sheet.iter_rows(values_only=True)], True
        finally:
            book.close()

    decoded = None
    chosen_encoding = None
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            candidate = raw.decode(encoding)
        except UnicodeError:
            continue
        if "\x00" in candidate:
            continue
        decoded = candidate
        chosen_encoding = encoding
        break
    if decoded is None:
        raise ValueError(f"无法识别CSV文本编码: {path}")
    try:
        return [tuple(row) for row in csv.reader(io.StringIO(decoded, newline=""))], False
    except csv.Error as exc:
        raise ValueError(f"CSV格式无效: {path} ({chosen_encoding})") from exc


def _parse_daily(
    item: dict[str, Any], *, date_header: str, amount_header: str, ocean: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path: Path = item["resolved_path"]
    table, is_excel = _read_rows(item["raw"], path)
    if not table:
        raise ValueError(f"日报为空: {path}")
    headers = _header_map(table[0], path, 1)
    _require_columns(headers, (date_header, amount_header), path)

    key_columns_present = all(name in headers for name in _DAILY_KEY_COLUMNS)
    if ocean and not key_columns_present:
        raise ValueError(f"巨量日报缺少重复校验列: {path}")

    parsed: list[dict[str, Any]] = []
    amounts: list[Decimal | None] = []
    summary_amount: Decimal | None = None
    summary_seen = False
    duplicate_keys: set[tuple[str, ...]] = set()
    for row_number, row in enumerate(table[1:], start=2):
        values = _row_values(headers, row)
        date_value = values.get(date_header)
        amount = _parse_amount(values.get(amount_header), path, row_number, amount_header)
        if _is_control_label(date_value):
            if summary_seen:
                raise ValueError(f"日报包含多个合计行: {path}")
            summary_seen = True
            summary_amount = amount
            continue

        normalized_date = _parse_date(date_value, is_excel, path, row_number, date_header, allow_blank=True)
        if normalized_date is None:
            if not _row_has_values(row):
                continue
            if ocean and row_number == 2 and amount is not None:
                summary_seen = True
                summary_amount = amount
                continue
            raise ValueError(f"日报第{row_number}行日期为空或无效: {path}")

        if key_columns_present:
            duplicate_key = _daily_duplicate_key(values, normalized_date, path, row_number)
            if duplicate_key in duplicate_keys:
                raise ValueError(f"日报重复项目日期投放键: source_id={item['source_id']} key={duplicate_key}")
            duplicate_keys.add(duplicate_key)

        record = {
            "source_id": item["source_id"],
            "source_row": row_number,
            "business_line": item["business_line"],
            "business_group": item["business_group"],
            "platform": item["platform"],
            "start_date": normalized_date,
            "end_date": normalized_date,
            "amount": None if amount is None else float(amount),
        }
        if amount is not None and not math.isfinite(record["amount"]):
            raise ValueError(f"日报金额超出可表示范围: {path} 第{row_number}行")
        parsed.append(record)
        amounts.append(amount)

    if summary_seen and summary_amount is not None:
        detail_total = sum((amount for amount in amounts if amount is not None), Decimal(0))
        if abs(detail_total - summary_amount) > _TOTAL_TOLERANCE:
            raise ValueError(
                f"日报明细与合计金额不符: source_id={item['source_id']} "
                f"明细={detail_total} 合计={summary_amount}"
            )

    dates = [record["start_date"] for record in parsed]
    source = _source_metadata(
        item,
        grain="daily",
        platform=item["platform"],
        start_date=min(dates) if dates else None,
        end_date=max(dates) if dates else None,
    )
    return parsed, [source]


def _parse_network_weekly(item: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path: Path = item["resolved_path"]
    table, is_excel = _read_rows(item["raw"], path)
    if len(table) < 3:
        raise ValueError(f"网络周表缺少期间行或表头: {path}")
    period = table[1]
    if len(period) < 2:
        raise ValueError(f"网络周表第2行缺少开始和结束日期: {path}")
    start_date = _parse_date(period[0], is_excel, path, 2, "期开始")
    end_date = _parse_date(period[1], is_excel, path, 2, "期结束")
    if start_date is None or end_date is None or start_date > end_date:
        raise ValueError(f"网络周表期间无效: {path}")

    headers = _header_map(table[2], path, 3)
    _require_columns(headers, ("渠道中类", "总推广费用"), path)
    if item.get("company"):
        _require_columns(headers, ("公司",), path)
    platform_amounts: dict[str, list[dict[str, Any]]] = {}
    parsed: list[dict[str, Any]] = []
    seen_channels: set[str] = set()
    for row_number, row in enumerate(table[3:], start=4):
        if not _row_has_values(row):
            continue
        values = _row_values(headers, row)
        channel = "" if values.get("渠道中类") is None else str(values["渠道中类"]).strip()
        if not channel:
            raise ValueError(f"网络周表第{row_number}行有数据但缺少渠道中类: {path}")
        if _is_control_label(channel):
            continue
        if channel in seen_channels:
            raise ValueError(f"网络周表原始渠道重复: source_id={item['source_id']} channel={channel}")
        seen_channels.add(channel)
        if item.get("company"):
            company = "" if values.get("公司") is None else str(values["公司"]).strip()
            if company != item["company"]:
                raise ValueError(
                    f"网络周表公司不符: source_id={item['source_id']} 第{row_number}行 "
                    f"期望={item['company']} 实际={company or '空'}"
                )
        platform = canonical_platform(channel)
        amount = _parse_amount(values.get("总推广费用"), path, row_number, "总推广费用")
        record = {
            "source_id": item["source_id"],
            "source_row": row_number,
            "raw_channel": channel,
            "business_line": item["business_line"],
            "business_group": item["business_group"],
            "platform": platform,
            "start_date": start_date,
            "end_date": end_date,
            "amount": None if amount is None else float(amount),
            "_amount_decimal": amount,
        }
        if amount is not None and not math.isfinite(record["amount"]):
            raise ValueError(f"网络周表金额超出可表示范围: {path} 第{row_number}行")
        parsed.append(record)
        platform_amounts.setdefault(platform, []).append(record)

    sources = [
        _source_metadata(item, grain="period", platform=platform,
                         start_date=start_date, end_date=end_date)
        for platform in platform_amounts
    ]
    return parsed, sources


def _derive_network_period_difference(
    difference: dict[str, Any],
    cumulative_item: dict[str, Any],
    cumulative_rows: list[dict[str, Any]],
    current_item: dict[str, Any],
    current_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_id = difference["source_id"]
    if not cumulative_rows or not current_rows:
        raise ValueError(f"网络费用差额关系{source_id}的累计表和本月表都必须有渠道行")

    def single_period(rows: list[dict[str, Any]], label: str) -> tuple[str, str]:
        periods = {(row["start_date"], row["end_date"]) for row in rows}
        if len(periods) != 1:
            raise ValueError(f"网络费用差额关系{source_id}的{label}表包含多个期间")
        return next(iter(periods))

    cumulative_start, cumulative_end = single_period(cumulative_rows, "累计")
    current_start, current_end = single_period(current_rows, "本月")
    target_start = date.fromisoformat(difference["start_date"])
    target_end = date.fromisoformat(difference["end_date"])
    if (cumulative_start != difference["start_date"]
            or cumulative_end != current_end
            or date.fromisoformat(current_start) != target_end + timedelta(days=1)):
        raise ValueError(
            f"网络费用差额关系{source_id}期间不连续: 累计={cumulative_start}至{cumulative_end}，"
            f"本月={current_start}至{current_end}，差额={target_start}至{target_end}"
        )

    cumulative_by_channel = {row["raw_channel"]: row for row in cumulative_rows}
    current_by_channel = {row["raw_channel"]: row for row in current_rows}
    current_only = sorted(current_by_channel.keys() - cumulative_by_channel.keys())
    if current_only:
        raise ValueError(
            f"网络费用差额关系{source_id}本月表出现累计表缺失的原渠道: {current_only}"
        )
    for label, channel_rows in (("累计", cumulative_by_channel), ("本月", current_by_channel)):
        blank = sorted(channel for channel, row in channel_rows.items() if row["_amount_decimal"] is None)
        if blank:
            raise ValueError(f"网络费用差额关系{source_id}{label}表总推广费用为空: {blank}")

    input_sources = [
        {
            "source_id": item["source_id"],
            "path": str(item["resolved_path"]),
            "sha256": item["actual_sha256"],
            "company": item["company"],
            "start_date": period_start,
            "end_date": period_end,
        }
        for item, (period_start, period_end) in (
            (cumulative_item, (cumulative_start, cumulative_end)),
            (current_item, (current_start, current_end)),
        )
    ]
    derivation = {
        "method": "cumulative_minus_current",
        "formula": "累计总推广费用 - 本月总推广费用",
        "match_key": "渠道中类原始值",
        "platform_mapping_order": "先按原渠道求差，再归类到平台",
        "missing_current_channel_policy": difference["missing_current_channel_policy"],
        "negative_differences": "preserved",
        "input_sources": input_sources,
    }

    result_rows: list[dict[str, Any]] = []
    platform_basis: dict[str, list[dict[str, Any]]] = {}
    for channel, cumulative in cumulative_by_channel.items():
        current = current_by_channel.get(channel)
        cumulative_amount: Decimal = cumulative["_amount_decimal"]
        current_amount: Decimal = Decimal(0) if current is None else current["_amount_decimal"]
        amount = cumulative_amount - current_amount
        platform = canonical_platform(channel)
        row_derivation = {
            "method": "cumulative_minus_current",
            "cumulative_source_id": cumulative_item["source_id"],
            "cumulative_source_row": cumulative["source_row"],
            "cumulative_amount": str(cumulative_amount),
            "current_source_id": current_item["source_id"],
            "current_source_row": None if current is None else current["source_row"],
            "current_amount": str(current_amount),
            "missing_current_channel_zero_filled": current is None,
        }
        row = {
            "source_id": source_id,
            "source_row": cumulative["source_row"],
            "raw_channel": channel,
            "business_line": cumulative_item["business_line"],
            "business_group": cumulative_item["business_group"],
            "platform": platform,
            "start_date": difference["start_date"],
            "end_date": difference["end_date"],
            "amount": float(amount),
            "_amount_decimal": amount,
            "derivation": row_derivation,
        }
        if not math.isfinite(row["amount"]):
            raise ValueError(f"网络费用差额超出可表示范围: source_id={source_id} channel={channel}")
        result_rows.append(row)
        platform_basis.setdefault(platform, []).append({
            "raw_channel": channel,
            "cumulative_source_row": cumulative["source_row"],
            "cumulative_amount": str(cumulative_amount),
            "current_source_row": None if current is None else current["source_row"],
            "current_amount": str(current_amount),
            "difference": str(amount),
            "missing_current_channel_zero_filled": current is None,
        })

    result_sources = []
    for platform, basis in platform_basis.items():
        result_sources.append({
            "source_id": source_id,
            "path": None,
            "sha256": None,
            "grain": "period",
            "business_line": cumulative_item["business_line"],
            "business_group": cumulative_item["business_group"],
            "company": cumulative_item["company"],
            "platform": platform,
            "start_date": difference["start_date"],
            "end_date": difference["end_date"],
            "derivation": derivation,
            "channel_basis": basis,
        })
    return result_rows, result_sources


def _source_metadata(
    item: dict[str, Any], *, grain: str, platform: str,
    start_date: str | None, end_date: str | None,
) -> dict[str, Any]:
    metadata = {
        "source_id": item["source_id"],
        "path": str(item["resolved_path"]),
        "sha256": item["actual_sha256"],
        "grain": grain,
        "business_line": item["business_line"],
        "business_group": item["business_group"],
        "platform": platform,
        "start_date": start_date,
        "end_date": end_date,
    }
    if item.get("company"):
        metadata["company"] = item["company"]
    return metadata


def _header_map(row: tuple[Any, ...], path: Path, row_number: int) -> dict[str, int]:
    headers: dict[str, int] = {}
    for index, value in enumerate(row):
        name = "" if value is None else str(value).strip()
        if not name:
            continue
        if name in headers:
            raise ValueError(f"表头列名重复: {path} 第{row_number}行 {name}")
        headers[name] = index
    return headers


def _require_columns(headers: dict[str, int], names: tuple[str, ...], path: Path) -> None:
    missing = [name for name in names if name not in headers]
    if missing:
        raise ValueError(f"费用来源缺少必需列: {path} {missing}")


def _row_values(headers: dict[str, int], row: tuple[Any, ...]) -> dict[str, Any]:
    return {name: row[index] if index < len(row) else None for name, index in headers.items()}


def _row_has_values(row: tuple[Any, ...]) -> bool:
    return any(value is not None and str(value).strip() != "" for value in row)


def _is_control_label(value: Any) -> bool:
    if value is None:
        return False
    label = re.sub(r"\s+", "", str(value))
    return any(label.startswith(prefix) for prefix in _CONTROL_LABELS)


def _parse_amount(value: Any, path: Path, row_number: int, column: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if normalized in {"", "-", "--"}:
            return None
        normalized = normalized.replace(",", "").replace("￥", "").replace("¥", "").replace("元", "")
    else:
        normalized = str(value).strip()
    try:
        result = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"费用金额无效: {path} 第{row_number}行 {column}={value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"费用金额不是有限数值: {path} 第{row_number}行 {column}={value!r}")
    return result


def _parse_date(
    value: Any, is_excel: bool, path: Path, row_number: int, column: str,
    *, allow_blank: bool = False,
) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_blank:
            return None
        raise ValueError(f"日期为空: {path} 第{row_number}行 {column}")
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_excel and isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            excel_date = from_excel(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(f"Excel日期无效: {path} 第{row_number}行 {column}={value!r}") from exc
        if isinstance(excel_date, datetime):
            return excel_date.date().isoformat()
        if isinstance(excel_date, date):
            return excel_date.isoformat()
        raise ValueError(f"Excel日期无效: {path} 第{row_number}行 {column}={value!r}")
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    for fmt in ("%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"日期无效: {path} 第{row_number}行 {column}={value!r}") from exc


def _daily_duplicate_key(
    values: dict[str, Any], normalized_date: str, path: Path, row_number: int
) -> tuple[str, ...]:
    components = [values.get("项目ID"), normalized_date, values.get("投放类型"), values.get("营销场景")]
    if any(value is None or str(value).strip() == "" for value in components):
        raise ValueError(f"日报第{row_number}行重复校验键不完整: {path}")
    return tuple(str(value).strip() for value in components)
