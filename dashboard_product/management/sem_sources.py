"""钉钉SEM原生整本的已确认叶表接入；不改原表、不分摊费用。"""
from datetime import date
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
    try:
        for sheet, mapping in item["sheets"].items():
            if sheet not in with_book.sheetnames:
                raise ValueError(f"SEM叶表不存在: {sheet}")
            ws = with_book[sheet]
            ws.reset_dimensions()  # 钉钉导出曾把实际多行表的dimension声明为A1。
            values = iter(ws.values)
            header = _header_map(next(values, ()), path, 1)
            _require_columns(header, ("时间", "消费", "现金消费"), path)
            leaf = {**item, **mapping, "source_id": item["source_id"] + ":" + sheet}
            seen, dates = set(), []
            for number, row in enumerate(values, 2):
                cells = _row_values(header, row)
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
                # 用户2026-10-27确认：SEM空白消费表示未消费；只作用于窗口内实际日期行。
                if consume is None or consume == 0:
                    if cash not in (None, Decimal(0)):
                        raise ValueError(f"SEM消费为空或0但现金费用非0: {sheet}/{day}")
                    amount = Decimal(0)
                else:
                    amount = None if cash is None else cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                rows.append({"source_id": leaf["source_id"], "source_row": number,
                             **mapping, "start_date": day, "end_date": day,
                             "amount": None if amount is None else float(amount),
                             "source_sheet": sheet, "raw_consume": None if consume is None else str(consume),
                             "raw_cash_consume": None if cash is None else str(cash)})
                dates.append(day)
            if dates:
                sources.append({**_source_metadata(leaf, grain="daily", platform=mapping["platform"],
                                                   start_date=min(dates), end_date=max(dates)),
                                "source_sheet": sheet, "amount_basis": "现金消费", "rounding": "每账号每日四舍五入到分",
                                "blank_consumption": "按用户2026-10-27确认计为零消费"})
    finally:
        with_book.close()
    return rows, sources
