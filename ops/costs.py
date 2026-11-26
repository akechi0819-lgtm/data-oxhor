"""Parse explicit group/day expense reports for transactional warehouse import."""
from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path

PLATFORMS = {"xhs": "小红书", "douyin": "抖音", "tencent": "腾讯广告"}
SEM_PLATFORMS = {"百度", "必应", "闲鱼", "360", "B站", "微博"}
GROUP_LINES = {"高中": "training", "大学": "training", "留学预备": "training", "语培整体": "training", "留学整体": "abroad"}
ALIASES = {"日期": "date", "业务组": "business_group", "业务线": "business_line", "金额": "amount", "平台": "platform"}


def _day(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError as exc:
        raise ValueError("费用日期必须是 YYYY-MM-DD") from exc


def _read(path):
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        records = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    elif suffix == ".json":
        records = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(records, list):
            raise ValueError("JSON 费用输入必须是数组")
    elif suffix == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            rows = iter(wb.worksheets[0].values)
            header = next(rows, ())
            records = [dict(zip(header, values)) for values in rows if any(v is not None for v in values)]
        finally:
            wb.close()
    else:
        raise ValueError("费用文件必须是 CSV、XLSX 或 JSON")
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("每条费用记录必须是对象")
    return records, hashlib.sha256(raw).hexdigest()


def parse_input(path, *, platform, confirmed_zero=()):
    """Return internal parsed batch; zero declarations use GROUP=DATE or GROUP/SEM平台=DATE."""
    if platform not in {*PLATFORMS, "sem"}:
        raise ValueError("不支持的费用平台")
    records, digest = _read(Path(path))
    items = {}
    for number, record in enumerate(records, 1):
        normalized = {}
        for key, value in record.items():
            name = ALIASES.get(key, key)
            if name in normalized:
                raise ValueError("费用字段重复")
            normalized[name] = value
        if not {"date", "business_group", "amount"} <= normalized.keys():
            raise ValueError("费用文件须包含日期、业务组、金额列")
        group = str(normalized["business_group"]).strip()
        line = GROUP_LINES.get(group)
        if line is None or (normalized.get("business_line") not in (None, "", line)):
            raise ValueError("业务线和业务组不匹配")
        channel = str(normalized.get("platform") or "").strip() if platform == "sem" else PLATFORMS[platform]
        if platform == "sem" and channel not in SEM_PLATFORMS:
            raise ValueError("SEM 每行必须明确已支持的具体平台")
        key = (line, group, channel, _day(normalized["date"]))
        if key in items:
            raise ValueError("费用文件存在重复的业务组、平台和日期")
        value = normalized["amount"]
        if value is None or (isinstance(value, str) and not value.strip()):
            amount = None
        else:
            if isinstance(value, bool):
                raise ValueError("费用金额必须为数字或空值")
            try:
                amount = Decimal(str(value))
            except InvalidOperation as exc:
                raise ValueError("费用金额必须为数字或空值") from exc
            if not amount.is_finite() or amount < 0:
                raise ValueError("费用金额必须为非负有限数字")
        items[key] = (amount, number)
    for declaration in confirmed_zero:
        scope, sep, day = declaration.partition("=")
        if not sep:
            raise ValueError("零消费声明格式应为 业务组=日期")
        group, slash, sem_channel = scope.partition("/")
        line = GROUP_LINES.get(group)
        if not line:
            raise ValueError("零消费声明业务组无效")
        if platform == "sem":
            if not slash or sem_channel not in SEM_PLATFORMS:
                raise ValueError("SEM 零消费声明须使用 业务组/具体平台=日期")
            channel = sem_channel
        else:
            if slash:
                raise ValueError("零消费声明业务组无效")
            channel = PLATFORMS[platform]
        key = (line, group, channel, _day(day))
        current = items.get(key)
        if current is not None and current[0] not in (None, Decimal(0)):
            raise ValueError("零消费声明与非零金额冲突")
        items[key] = (Decimal(0), current[1] if current else len(records) + len(items) + 1)
    if not items:
        raise ValueError("费用输入没有记录或明确零消费声明")
    sources, rows = [], []
    for (line, group, channel, day), (amount, number) in sorted(items.items()):
        identity = json.dumps([line, group, channel], ensure_ascii=False, separators=(",", ":"))
        source_id = "manual:" + hashlib.sha256(identity.encode()).hexdigest()
        if not any(source["source_id"] == source_id for source in sources):
            sources.append({"source_id": source_id, "source_kind": "manual_daily", "grain": "daily",
                            "business_line": line, "business_group": group, "platform": channel,
                            "sha256": digest})
        rows.append({"source_id": source_id, "source_row": number, "business_line": line,
                     "business_group": group, "platform": channel, "start_date": day, "end_date": day,
                     "amount": amount})
    return {"sources": sources, "rows": rows}


def ingest(connection, *, path, platform, confirmed_zero=(), import_id):
    """Write to a caller-provided isolated candidate; never publishes or sends notifications."""
    from dashboard_product.shadow_bi.sql_warehouse.expenses import replace_sources
    return replace_sources(connection, parse_input(path, platform=platform, confirmed_zero=confirmed_zero), import_id)


def build_cost_candidate(*, baseline_dir, output_dir, costs, batch_id):
    """Clone a verified SQL candidate and replace expenses without rebuilding business data."""
    from copy import deepcopy
    import shutil
    import duckdb
    from data_platform.query.evidence import file_ref, resolve_file
    from dashboard_product.shadow_bi.p5.sql_daily import _validate_candidate
    from dashboard_product.shadow_bi.sql_warehouse.expenses import replace_sources
    from dashboard_product.shadow_bi.sql_warehouse.header import update_date_label, coverage_note
    from dashboard_product.shadow_bi.sql_warehouse.relations import records

    baseline, output = Path(baseline_dir).resolve(strict=True), Path(output_dir).resolve()
    if output.is_relative_to(baseline):
        raise ValueError("费用候选必须与基线隔离")
    manifest = json.loads((baseline / "candidate.json").read_text(encoding="utf-8"))
    if not isinstance(batch_id, str) or not batch_id.strip() or batch_id == manifest["batch_id"]:
        raise ValueError("费用候选必须使用新的非空 batch_id")
    _validate_candidate(baseline, batch_id=manifest["batch_id"],
                        training_snapshot=manifest["snapshots"]["training"],
                        abroad_snapshot=manifest["snapshots"]["abroad"], as_of_date=manifest["as_of_date"])
    database = resolve_file(baseline, manifest["database"])
    preview = resolve_file(baseline, manifest["notification_preview"])
    output.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copy2(database, output / "warehouse.duckdb")
        shutil.copy2(preview, output / "notification-preview.json")
        shutil.copytree(baseline / "source-evidence", output / "source-evidence")
        with duckdb.connect(str(output / "warehouse.duckdb")) as connection:
            result = replace_sources(connection, costs, batch_id + "_fees")
            display_dates = records(connection, "SELECT * FROM business.update_dates")[0]
            connection.execute("UPDATE meta.identity SET batch_id=?", [batch_id])
            connection.execute("CHECKPOINT")
        candidate = deepcopy(manifest)
        candidate.update(batch_id=batch_id, database=file_ref(output / "warehouse.duckdb", output, "application/vnd.duckdb"),
                         notification_preview=file_ref(output / "notification-preview.json", output, "application/json"),
                         display_dates=display_dates, display_label=update_date_label(display_dates),
                         dashboard_coverage_note=coverage_note(display_dates),
                         expenses={"status": "updated", **result}, server_actions=False, notification_delivery=False,
                         expense_baseline={"candidate_sha256": hashlib.sha256((baseline / "candidate.json").read_bytes()).hexdigest(),
                                           "database_sha256": manifest["database"]["sha256"]})
        (output / "candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        _validate_candidate(output, batch_id=batch_id, training_snapshot=manifest["snapshots"]["training"],
                            abroad_snapshot=manifest["snapshots"]["abroad"], as_of_date=manifest["as_of_date"])
        return candidate
    except Exception:
        shutil.rmtree(output)
        raise
