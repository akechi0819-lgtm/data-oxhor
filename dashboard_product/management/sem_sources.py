"""钉钉SEM原生整本的已确认叶表接入；不改原表、不分摊费用。"""
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import io
import re

from openpyxl import load_workbook


def validate_sem_entry(entry):
    required = {"source_id", "path", "kind", "start_date", "end_date", "sheets"}
    if not required.issubset(entry) or set(entry) - required - {"sha256"}:
        raise ValueError("SEM清单必须声明来源、文件、起止日期和叶表映射")
    if any(not isinstance(entry[k], str) or not entry[k].strip() for k in ("source_id", "path")):
        raise ValueError("SEM来源ID和路径不能为空")
    start, end = (date.fromisoformat(entry[k]).isoformat() for k in ("start_date", "end_date"))
    if start > end:
        raise ValueError("SEM日期范围倒置")
    if entry.get("sha256") is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", str(entry["sha256"])):
        raise ValueError("SEM文件sha256无效")
    if not isinstance(entry["sheets"], dict) or not entry["sheets"]:
        raise ValueError("SEM必须指定已确认的叶表")
    for name, mapping in entry["sheets"].items():
        if not isinstance(name, str) or "总计" in name or "汇总" in name:
            raise ValueError("SEM不能将总表和叶表重复计费")
        if not isinstance(mapping, dict) or set(mapping) != {"business_line", "business_group", "platform"}:
            raise ValueError("SEM叶表必须明确业务线、业务组和平台")
        groups = {"abroad": {"留学整体"}, "training": {"语培整体", "高中", "大学", "留学预备"}}
        if mapping["business_group"] not in groups.get(mapping["business_line"], set()):
            raise ValueError("SEM叶表业务归属无效")
        if mapping["platform"] not in {"百度", "必应", "闲鱼", "360", "B站", "微博"}:
            raise ValueError("SEM叶表平台无效")
    return {**entry, "start_date": start, "end_date": end,
            "business_line": None, "business_group": None}


def parse_sem(item):
    # 复用费用解析的日期、金额和来源回执规则；只读缓存，不执行源表公式。
    from .advertising_sources import _header_map, _require_columns, _row_values, _parse_date, _parse_amount, _source_metadata
    path = item["resolved_path"]
    rows, sources = [], []
    with_book = load_workbook(io.BytesIO(item["raw"]), read_only=True, data_only=True)
    formula_book = load_workbook(io.BytesIO(item["raw"]), read_only=True, data_only=False)
    try:
        for sheet, mapping in item["sheets"].items():
            if sheet not in with_book.sheetnames:
                raise ValueError(f"SEM叶表不存在: {sheet}")
            ws = with_book[sheet]
            formula_ws = formula_book[sheet]
            ws.reset_dimensions()  # 钉钉导出曾把实际多行表的dimension声明为A1。
            formula_ws.reset_dimensions()
            values = iter(ws.values)
            formula_values = iter(formula_ws.values)
            header = _header_map(next(values, ()), path, 1)
            formula_header = _header_map(next(formula_values, ()), path, 1)
            _require_columns(header, ("时间", "消费", "现金消费"), path)
            _require_columns(formula_header, ("时间", "消费", "现金消费"), path)
            leaf = {**item, **mapping, "source_id": item["source_id"] + ":" + sheet}
            seen, dates, missing_amount_dates = set(), [], []
            missing_consumption_dates = []
            amount_statuses = Counter()
            for number, (row, formula_row) in enumerate(zip(values, formula_values), 2):
                cells = _row_values(header, row)
                formula_cells = _row_values(formula_header, formula_row)
                raw_date = cells.get("时间")
                if raw_date is None or str(raw_date).strip().startswith(("合计", "总计")):
                    continue
                day = _parse_date(raw_date, True, path, number, "时间")
                if not item["start_date"] <= day <= item["end_date"]:
                    continue
                if day in seen:
                    raise ValueError(f"SEM叶表日期重复: {sheet}/{day}")
                seen.add(day)
                consume = _parse_amount(cells.get("消费"), path, number, "消费")
                cash = _parse_amount(cells.get("现金消费"), path, number, "现金消费")
                raw_cash = formula_cells.get("现金消费")
                cash_formula = raw_cash if isinstance(raw_cash, str) and raw_cash.startswith("=") else None
                # A cached formula zero derived from a blank consumption cell is
                # not evidence of a reported zero. Preserve the source values and
                # leave the amount unknown so downstream coverage stays partial.
                if cash is None:
                    amount, amount_status = None, "missing_cash_consumption"
                elif cash_formula is not None and consume is None:
                    amount, amount_status = None, "formula_derived_from_blank_consumption"
                else:
                    amount = None if cash is None else cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    amount_status = "reported_zero" if amount == 0 else "reported_value"
                rows.append({"source_id": leaf["source_id"], "source_row": number,
                             **mapping, "start_date": day, "end_date": day,
                             "amount": None if amount is None else float(amount),
                             "source_sheet": sheet, "raw_consume": None if consume is None else str(consume),
                             "raw_cash_consume": None if cash is None else str(cash),
                             "raw_cash_formula": cash_formula,
                             "amount_status": amount_status})
                dates.append(day)
                amount_statuses[amount_status] += 1
                if amount is None:
                    missing_amount_dates.append(day)
                if consume is None:
                    missing_consumption_dates.append(day)
            window_dates = {
                (date.fromisoformat(item["start_date"]) + timedelta(days=offset)).isoformat()
                for offset in range((date.fromisoformat(item["end_date"]) - date.fromisoformat(item["start_date"])).days + 1)
            }
            observed_dates = set(dates)
            missing_date_rows = sorted(window_dates - observed_dates)
            sources.append({**_source_metadata(leaf, grain="daily", platform=mapping["platform"],
                                               start_date=min(dates) if dates else None,
                                               end_date=max(dates) if dates else None),
                            "source_sheet": sheet, "amount_basis": "现金消费", "rounding": "每账号每日四舍五入到分",
                            "requested_start_date": item["start_date"],
                            "requested_end_date": item["end_date"],
                            "observed_date_count": len(dates),
                            "observed_dates": sorted(observed_dates),
                            "missing_date_count": len(missing_date_rows),
                            "missing_date_rows": missing_date_rows,
                            "missing_amount_count": len(missing_amount_dates),
                            "missing_amount_dates": missing_amount_dates,
                            "missing_consumption_dates": missing_consumption_dates,
                            "amount_status_counts": dict(amount_statuses),
                            "coverage_state": "partial" if missing_date_rows or missing_amount_dates else "available",
                            "blank_amount_policy": "blank or formula-derived value from a blank consumption cell remains missing; available rows are used"})
    finally:
        with_book.close()
        formula_book.close()
    return rows, sources
