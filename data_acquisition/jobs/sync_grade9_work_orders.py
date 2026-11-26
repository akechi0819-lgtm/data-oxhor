"""Synchronize grade-nine work orders to a caller-specified Tencent sheet."""
from __future__ import annotations

import math
import re
from datetime import date, timedelta

from data_acquisition.jobs.sheet_sync_common import commit_with_readback, map_columns, readback_matches

ID, STATUS = "ID", "工单状态"
DATE_HEADERS = {"分配日期", "分配时间", "邀约面询时间"}
LIMIT = 1000


def tool(client, name: str, params: dict) -> dict:
    result = client.call_tool(name, params)
    if result.get("error") or result.get("isError"):
        raise RuntimeError(f"{name} failed")
    return result


def cell_value(cell: dict) -> object:
    if cell.get("formula") or cell.get("formula_value"):
        return {"formula": cell.get("formula"), "formula_value": cell.get("formula_value")}
    key = {"STRING": "string_value", "NUMBER": "number_value", "BOOL": "bool_value"}.get(cell.get("value_type"))
    return cell.get(key) if key else cell.get("value")


def read_grid(client, file_id: str, sheet_id: str, rows: int, cols: int) -> dict[tuple[int, int], object]:
    grid = {}
    height = max(1, LIMIT // cols)
    for start in range(0, rows, height):
        result = tool(client, "sheet.get_cell_data", {
            "file_id": file_id, "sheet_id": sheet_id,
            "start_row": start, "end_row": min(rows - 1, start + height - 1),
            "start_col": 0, "end_col": cols - 1,
            "return_csv": False, "include_formula": True,
        })
        for cell in result["cells"]:
            key = (int(cell["row"]), int(cell["col"]))
            if key in grid:
                raise RuntimeError("duplicate cell coordinate in sheet response")
            grid[key] = cell_value(cell)
    return grid


def norm_id(value: object) -> str | None:
    if value is None or isinstance(value, dict):
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RuntimeError("invalid numeric ID")
        value = str(int(value)) if value.is_integer() else format(value, ".15g")
    text = str(value).strip()
    return re.sub(r"\.0$", "", text) if re.fullmatch(r"\d+\.0", text) else text or None


def sql_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_sql(relation: dict, root_headers: list[str], current_ids: list[str], as_of: date, start_date: date) -> tuple[str, list[str]]:
    columns = relation["columns"]
    source = [(c["header_label"], c["name"]) for c in columns if c.get("header_label")]
    labels = [label for label, _ in source]
    if len(labels) != len(set(labels)):
        raise RuntimeError("duplicate source header labels")
    by_header = dict(source)
    required = [ID, STATUS, "年级校正", "主被动"]
    date_fields = [h for h in ("分配日期", "分配时间") if h in by_header]
    if len(date_fields) != 1 or any(h not in by_header for h in required):
        raise RuntimeError("required source fields missing or ambiguous")
    if any(h not in root_headers for h in labels):
        raise RuntimeError("source header missing from target sheet")
    source_row = next((c["name"] for c in columns if c["name"] == "source_row_number"), None)
    if not source_row:
        raise RuntimeError("source_row_number missing from description")
    table = f'{sql_ident(relation["schema"])}.{sql_ident(relation["name"])}'
    id_expr = f"NULLIF(TRIM(CAST(src.{sql_ident(by_header[ID])} AS VARCHAR)), '')"
    ids = ", ".join(sql_text(value) for value in current_ids) or "NULL"
    date_col = f"src.{sql_ident(by_header[date_fields[0]])}"
    serial_date = f"DATE '1899-12-30' + CAST(FLOOR(TRY_CAST({date_col} AS DOUBLE)) AS INTEGER)"
    end_date = as_of + timedelta(days=1)
    fields = ", ".join(f'src.{sql_ident(name)} AS {sql_ident(label)}' for label, name in source)
    sql = f"""WITH ranked AS (
 SELECT src.*, ROW_NUMBER() OVER (PARTITION BY {id_expr} ORDER BY src.{sql_ident(source_row)} ASC NULLS LAST) AS __grade9_rn
 FROM {table} AS src
)
SELECT {fields} FROM ranked AS src
WHERE src.__grade9_rn = 1 AND {id_expr} IS NOT NULL AND (
   {id_expr} IN ({ids}) OR (
     {serial_date} >= DATE '{start_date.isoformat()}' AND {serial_date} < DATE '{end_date.isoformat()}'
     AND TRIM(src.{sql_ident(by_header['年级校正'])}) = '9年级（初三）'
     AND TRIM(src.{sql_ident(by_header['主被动'])}) = '被动'
   )
 )
ORDER BY src.{sql_ident(source_row)}"""
    return sql, labels


def as_sheet_cell(row: int, col: int, value: object, header: str) -> tuple[dict | None, str | None]:
    if value is None or value == "":
        return None, None
    if header == ID or "电话" in header:
        if isinstance(value, float) and value.is_integer():
            value = str(int(value))
        else:
            value = str(value)
    elif "日期" in header or "时间" in header:
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                pass
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value):
                raise RuntimeError("invalid date serial")
            fmt = "yyyy-mm-dd" if header in DATE_HEADERS and float(value).is_integer() else "yyyy-mm-dd hh:mm:ss"
            return {"row": row, "col": col, "value_type": "NUMBER", "number_value": value}, fmt
    if isinstance(value, bool):
        return {"row": row, "col": col, "value_type": "BOOL", "bool_value": value}, None
    if isinstance(value, (int, float)):
        return {"row": row, "col": col, "value_type": "NUMBER", "number_value": value}, None
    return {"row": row, "col": col, "value_type": "STRING", "string_value": str(value)}, None


def sync(client, file_id: str, sheet_id: str, relation: dict, query,
         as_of: date, start_date: date) -> dict:
    """Run one sync. query(sql, headers) returns {'columns': [...], 'rows': [[...]]}."""
    sheets = tool(client, "sheet.get_sheet_info", {"file_id": file_id})["sheets"]
    if not sheets or str(sheets[0]["sheet_id"]) != sheet_id:
        raise RuntimeError("configured sheet is not the first sheet")
    rows, cols = int(sheets[0]["row_count"]), int(sheets[0]["col_count"])
    before = read_grid(client, file_id, sheet_id, rows, cols)
    headers = [before.get((0, col)) for col in range(cols)]
    named = [h for h in headers if h not in (None, "")]
    if any(not isinstance(h, str) for h in named) or len(named) != len(set(named)):
        return {"status": "paused", "reason": "target_headers_ambiguous"}
    source_headers = [c["header_label"] for c in relation["columns"] if c.get("header_label")]
    if len(source_headers) != len(set(source_headers)):
        raise RuntimeError("duplicate source header labels")
    missing = [h for h in source_headers if h not in headers]
    if missing:
        return {"status": "paused", "reason": "target_headers_missing", "missing_headers": missing}
    required = [ID, STATUS, "年级校正", "主被动"]
    missing_source = [name for name in required if name not in source_headers]
    assigned_fields = [name for name in ("分配日期", "分配时间") if name in source_headers]
    if missing_source or not assigned_fields:
        return {"status": "paused", "reason": "source_headers_missing",
                "missing_headers": missing_source + (["分配日期/分配时间"] if not assigned_fields else [])}
    try:
        positions = map_columns([ID, STATUS], headers)
    except ValueError as exc:
        raise RuntimeError("target ID or status column missing") from exc
    existing = {}
    last_occupied = max((row for (row, _), value in before.items() if row and value not in (None, "")), default=0)
    for row in range(1, rows):
        ident = norm_id(before.get((row, positions[ID])))
        if ident:
            if ident in existing:
                raise RuntimeError("duplicate ID in target sheet")
            existing[ident] = row
    committed_rows = set(existing.values())
    source_cols = {col for col, name in enumerate(headers) if name in source_headers and name != ID}
    if any(row > 0 and row not in committed_rows and col in source_cols and value not in (None, "")
           for (row, col), value in before.items()):
        return {"status": "paused", "reason": "grade9_uncommitted_data_rows_require_review"}
    sql, selected = build_sql(relation, headers, list(existing), as_of, start_date)
    result = query(sql, selected)
    if result["columns"] != selected:
        raise RuntimeError("query result headers do not match description")
    source = {}
    for values in result["rows"]:
        if len(values) != len(selected):
            raise RuntimeError("query result row width mismatch")
        record = dict(zip(selected, values))
        ident = norm_id(record.get(ID))
        if not ident or ident in source:
            raise RuntimeError("query returned blank or duplicate ID")
        source[ident] = record
    writes, styles, additions = [], {}, []
    for ident, record in source.items():
        if ident not in existing:
            additions.append((ident, record))
            continue
        row, col = existing[ident], positions[STATUS]
        value = record.get(STATUS)
        current = before.get((row, col))
        if not isinstance(current, dict) and current != value and not (current in (None, "") and value in (None, "")):
            cell, _ = as_sheet_cell(row, col, value or "", STATUS)
            writes.append(cell or {"row": row, "col": col, "value_type": "STRING", "string_value": ""})
    for (row, col), value in before.items():
        header = headers[col] or ""
        if row and header in source_headers and ("日期" in header or "时间" in header) and isinstance(value, str):
            try:
                number = float(value.strip())
            except ValueError:
                continue
            if math.isfinite(number):
                writes.append({"row": row, "col": col, "value_type": "NUMBER", "number_value": number})
                styles[(row, col)] = "yyyy-mm-dd" if header in DATE_HEADERS and number.is_integer() else "yyyy-mm-dd hh:mm:ss"
    new_start = last_occupied + 1
    for offset, (_, record) in enumerate(additions):
        for col, header in enumerate(headers):
            if header in record:
                cell, fmt = as_sheet_cell(new_start + offset, col, record[header], header)
                if cell:
                    writes.append(cell)
                    if fmt:
                        styles[(new_start + offset, col)] = fmt
    current = tool(client, "sheet.get_sheet_info", {"file_id": file_id})["sheets"][0]
    if (int(current["row_count"]) != rows or int(current["col_count"]) != cols
            or read_grid(client, file_id, sheet_id, rows, cols) != before):
        raise RuntimeError("target sheet changed after plan; no cell values written")
    required_rows = new_start + len(additions)
    if required_rows > rows:
        tool(client, "sheet.insert_dimension", {"file_id": file_id, "sheet_id": sheet_id,
             "dimension_type": "row", "index": rows - 1, "count": required_rows - rows, "direction": "after"})
        rows = required_rows
    current = tool(client, "sheet.get_sheet_info", {"file_id": file_id})["sheets"][0]
    current_grid = read_grid(client, file_id, sheet_id, int(current["row_count"]), int(current["col_count"]))
    if not readback_matches(current_grid, before):
        raise RuntimeError("target sheet changed before write; no cell values written")
    payload = {(cell["row"], cell["col"]): cell for cell in writes}

    def read():
        info = tool(client, "sheet.get_sheet_info", {"file_id": file_id})["sheets"][0]
        if int(info["row_count"]) != rows or int(info["col_count"]) != cols:
            raise RuntimeError("target sheet dimensions changed")
        return read_grid(client, file_id, sheet_id, rows, cols)

    def write(values):
        cells = [payload[key] for key in values]
        for start in range(0, len(cells), LIMIT):
            tool(client, "sheet.set_range_value",
                 {"file_id": file_id, "sheet_id": sheet_id, "values": cells[start:start + LIMIT]})
        for (row, col) in values:
            if (fmt := styles.get((row, col))) is not None:
                tool(client, "sheet.set_cell_style", {"file_id": file_id, "sheet_id": sheet_id,
                     "start_row": row, "end_row": row, "start_col": col, "end_col": col,
                     "number_format_pattern": fmt})

    expected = {key: cell_value(cell) for key, cell in payload.items()}
    commit = {key: value for key, value in expected.items()
              if key[1] == positions[STATUS] or (key[0] >= new_start and key[1] == positions[ID])}
    source_values = {key: value for key, value in expected.items() if key not in commit}
    unchanged = {key: value for key, value in before.items() if key not in expected}
    commit_with_readback(write, read, source_values, commit,
                         {**unchanged, **{key: before.get(key) for key in commit}})
    final_grid = read()
    if not readback_matches(final_grid, {**unchanged, **expected}):
        raise RuntimeError("readback mismatch or unexpected change")
    final_ids = [norm_id(final_grid.get((row, positions[ID]))) for row in range(1, rows)]
    final_ids = [ident for ident in final_ids if ident]
    if len(final_ids) != len(set(final_ids)) or set(final_ids) != set(existing) | set(source):
        raise RuntimeError("final IDs do not match existing and appended IDs")
    return {"status": "passed", "record_count_before": len(existing), "record_count_after": len(final_ids),
            "added": len(additions), "missing_existing_ids": sorted(set(existing) - set(source)),
            "readback_verified": True, "data_through": (as_of - timedelta(days=1)).isoformat()}
