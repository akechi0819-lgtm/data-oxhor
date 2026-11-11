"""Append dated BI work-order rows to the configured Tencent Docs sheet."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, time
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterator

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from data_acquisition.connectors.tencent_docs.mcp import TencentDocsMCPClient, TencentDocsMCPError
from dashboard_product.management.platforms import canonical_platform

DATE_FIELD = "分配时间"
ID_FIELD = "ID"
LEARNER_NUMBER_FIELD = "学员号"
MATERIAL_ID_FIELD = "素材ID"
ACCOUNT_SOURCE_FIELD = "账号来源"
SECONDARY_CHANNEL_FIELD = "二级渠道"
SECONDARY_CHANNEL_PLATFORMS = frozenset({"腾讯广告", "抖音", "小红书"})
MANUAL_FIELDS = frozenset({
    MATERIAL_ID_FIELD, ACCOUNT_SOURCE_FIELD, "工单跟进情况", "重点资源意向", "所属条线",
})
RECEIPT_ROOT = Path("Work/ContentWorkOrders")
RECEIPT_SCHEMA = "content_work_orders_sync.v1"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BATCH_SIZE = 25

class SyncError(RuntimeError):
    """A safe, stable error code for a failed content-work-order sync."""

def _iso_date(value: object, field: str) -> date:
    if not isinstance(value, str) or not ISO_DATE_RE.fullmatch(value):
        raise SyncError(f"invalid_{field}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise SyncError(f"invalid_{field}") from None

def _parse_source_date(value: object, epoch: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return None
        try:
            converted = from_excel(value, epoch=epoch)
        except (OverflowError, TypeError, ValueError):
            return None
        return converted.date() if isinstance(converted, datetime) else converted if isinstance(converted, date) else None
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(text)
            except ValueError:
                try:
                    numeric_value = float(text)
                except (OverflowError, ValueError):
                    return None
                return _parse_source_date(numeric_value, epoch)
    return None

def _identifier(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None if value is None else str(value)
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise SyncError("source_identifier_invalid")
        text = str(int(value)) if value.is_integer() else format(value, ".15g")
    else:
        text = str(value)
    stripped = text.strip()
    if not stripped or stripped.casefold() in {"none", "null", "nan", "/"}:
        return None
    if re.fullmatch(r"\d+\.0", stripped):
        return stripped[:-2]
    return text

def _iso_value(value: object, header: str, epoch: Any) -> object:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0, 0) else value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="seconds")
    is_date_field = "日期" in header or "时间" in header or header.casefold().endswith("date")
    if is_date_field and isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            converted = from_excel(value, epoch=epoch)
        except (OverflowError, TypeError, ValueError):
            return value
        if isinstance(converted, datetime):
            return converted.date().isoformat() if converted.time() == time(0, 0) else converted.isoformat(timespec="seconds")
        return converted.isoformat() if isinstance(converted, (date, time)) else value
    if is_date_field and isinstance(value, str) and value.strip():
        try:
            parsed_datetime = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed_datetime.date().isoformat() if parsed_datetime.time().replace(tzinfo=None) == time(0, 0) else parsed_datetime.isoformat(timespec="seconds")
        except ValueError:
            try:
                return date.fromisoformat(value.strip()).isoformat()
            except ValueError:
                return value
    return value

def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SyncError("config_missing_or_invalid") from None
    if not isinstance(value, dict):
        raise SyncError("config_must_be_object")
    for name in ("file_id", "sheet_id", "token_file"):
        if not isinstance(value.get(name), str) or not value[name].strip():
            raise SyncError(f"config_{name}_missing")
    columns = value.get("columns")
    if (not isinstance(columns, list) or not columns
            or any(not isinstance(item, str) or not item for item in columns)
            or len(set(columns)) != len(columns)):
        raise SyncError("config_columns_must_be_nonempty_unique_headers")
    if ID_FIELD not in columns or DATE_FIELD not in columns or not MANUAL_FIELDS.issubset(columns):
        raise SyncError("config_required_headers_missing")
    if columns.index(ACCOUNT_SOURCE_FIELD) != columns.index(MATERIAL_ID_FIELD) + 1:
        raise SyncError("config_account_source_must_follow_material_id")
    if "secondary_channel_platforms" in value:
        platforms = value["secondary_channel_platforms"]
        if (not isinstance(platforms, list) or not platforms
                or any(not isinstance(platform, str) for platform in platforms)
                or len(set(platforms)) != len(platforms)):
            raise SyncError("config_secondary_channel_platforms_must_be_nonempty_unique_list")
        if any(platform not in SECONDARY_CHANNEL_PLATFORMS for platform in platforms):
            raise SyncError("config_secondary_channel_platform_unsupported")
    if "window_mode" in value and value["window_mode"] != "current_month":
        raise SyncError("config_window_mode_unsupported")
    value["start_date"] = _iso_date(value.get("start_date"), "start_date").isoformat()
    return value

def _resolve_path(value: str | Path, *, base: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()

def _load_candidates(source_file: Path, columns: list[str], start: date,
                     through: date,
                     secondary_channel_platforms: list[str] | None = None
                     ) -> tuple[list[list[object]], date | None]:
    if not source_file.is_file():
        raise SyncError("source_file_missing")
    try:
        workbook = load_workbook(source_file, read_only=True, data_only=True)
    except (OSError, ValueError, KeyError):
        raise SyncError("source_xlsx_invalid") from None
    try:
        if not workbook.worksheets:
            raise SyncError("source_xlsx_has_no_sheets")
        try:
            source_headers = [cell.value for cell in next(workbook.active.iter_rows(min_row=1, max_row=1))]
        except StopIteration:
            raise SyncError("source_header_missing") from None
        if len(set(source_headers)) != len(source_headers):
            raise SyncError("source_header_duplicate")
        source_index = {header: index for index, header in enumerate(source_headers) if isinstance(header, str)}
        if any(header not in source_index and header not in MANUAL_FIELDS for header in columns):
            raise SyncError("source_headers_missing_required_fields")
        if DATE_FIELD not in source_index or ID_FIELD not in source_index:
            raise SyncError("source_required_field_missing")
        secondary_channel_index = source_index.get(SECONDARY_CHANNEL_FIELD)
        if secondary_channel_platforms is not None and secondary_channel_index is None:
            raise SyncError("source_secondary_channel_missing")
        sheet = workbook.active
        indexes = [source_index.get(header) for header in columns]
        date_index = source_index[DATE_FIELD]
        id_column = columns.index(ID_FIELD)
        maximum_date: date | None = None
        candidates: dict[str, list[object]] = {}
        for source_row in sheet.iter_rows(min_row=2, values_only=True):
            if not any(value not in (None, "") for value in source_row):
                continue
            raw_day = source_row[date_index] if date_index < len(source_row) else None
            row_day = _parse_source_date(raw_day, workbook.epoch)
            if row_day is None:
                raise SyncError("source_work_order_date_missing" if raw_day in (None, "")
                                else "source_work_order_date_invalid")
            maximum_date = row_day if maximum_date is None else max(maximum_date, row_day)
            if row_day < start or row_day > through:
                continue
            if (secondary_channel_platforms is not None
                    and canonical_platform(source_row[secondary_channel_index]) not in secondary_channel_platforms):
                continue
            target_row = []
            for header, column_index in zip(columns, indexes):
                value = None if header in MANUAL_FIELDS or column_index is None or column_index >= len(source_row) else source_row[column_index]
                is_id = header.casefold().endswith("id") or header == LEARNER_NUMBER_FIELD
                value = row_day.isoformat() if header == DATE_FIELD else _identifier(value) if is_id else _iso_value(value, header, workbook.epoch)
                if isinstance(value, float) and not math.isfinite(value):
                    raise SyncError("source_numeric_value_invalid")
                target_row.append(value)
            source_id = target_row[id_column]
            if source_id is None:
                raise SyncError("source_work_order_id_missing")
            prior = candidates.get(source_id)
            if prior is None:
                candidates[source_id] = target_row
            elif prior != target_row:
                raise SyncError("source_id_conflict")
        return list(candidates.values()), maximum_date
    finally:
        workbook.close()

def _call_tool(client: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        result = client.call_tool(name, arguments)
    except SyncError:
        raise
    except TencentDocsMCPError as error:
        raise SyncError(str(error)) from None
    except Exception:
        raise SyncError(f"mcp_tool_call_failed:{name}") from None
    if not isinstance(result, dict):
        raise SyncError(f"mcp_tool_response_invalid:{name}")
    if result.get("isError") or result.get("error"):
        raise SyncError(f"mcp_tool_reported_error:{name}")
    structured = result.get("structuredContent") if "structuredContent" in result else result
    if not isinstance(structured, dict):
        raise SyncError(f"mcp_tool_structured_content_missing:{name}")
    if structured.get("error"):
        raise SyncError(f"mcp_tool_reported_error:{name}")
    return structured

def _range_cells(client: Any, file_id: str, sheet_id: str, *,
                 start_row: int, end_row: int, start_col: int, end_col: int) -> dict[tuple[int, int], object]:
    if end_row < start_row or end_col < start_col:
        return {}
    response = _call_tool(client, "sheet.get_cell_data", {
        "file_id": file_id,
        "sheet_id": sheet_id,
        "start_row": start_row,
        "end_row": end_row,
        "start_col": start_col,
        "end_col": end_col,
        "return_csv": False,
        "include_formula": True,
    })
    cells = response.get("cells")
    if not isinstance(cells, list):
        raise SyncError("mcp_cells_response_missing")
    result = {}
    for cell in cells:
        try:
            coordinate = (int(cell["row"]), int(cell["col"]))
        except (KeyError, TypeError, ValueError):
            raise SyncError("mcp_cell_coordinate_invalid") from None
        if coordinate in result:
            raise SyncError("mcp_duplicate_cell_coordinate")
        key = {"STRING": "string_value", "NUMBER": "number_value", "BOOL": "bool_value"}.get(cell.get("value_type"))
        result[coordinate] = cell.get(key) if key else next((cell[k] for k in ("string_value", "number_value", "bool_value", "value") if k in cell), None)
    return result

def _remote_state(client: Any, *, file_id: str, sheet_id: str,
                  columns: list[str]) -> tuple[int, dict[str, int]]:
    info = _call_tool(client, "sheet.get_sheet_info", {"file_id": file_id})
    sheets = info.get("sheets")
    if not isinstance(sheets, list):
        raise SyncError("mcp_sheet_info_invalid")
    matches = [sheet for sheet in sheets if isinstance(sheet, dict)
               and str(sheet.get("sheet_id")) == sheet_id]
    if len(matches) != 1:
        raise SyncError("remote_sheet_not_found_or_ambiguous")
    sheet = matches[0]
    try:
        row_count = int(sheet["row_count"])
        column_count = int(sheet.get("col_count", len(columns)))
    except (KeyError, TypeError, ValueError):
        raise SyncError("mcp_sheet_dimensions_invalid") from None
    if row_count < 1 or column_count < len(columns):
        raise SyncError("remote_sheet_too_small")

    header_cells = _range_cells(client, file_id, sheet_id, start_row=0, end_row=0,
                                start_col=0, end_col=column_count - 1)
    remote_headers = [header_cells.get((0, index)) for index in range(column_count)]
    if remote_headers[:len(columns)] != columns or any(
            value not in (None, "") for value in remote_headers[len(columns):]):
        raise SyncError("remote_header_mismatch")

    id_column = columns.index(ID_FIELD)
    id_cells = _range_cells(client, file_id, sheet_id, start_row=1,
                            end_row=row_count - 1, start_col=id_column, end_col=id_column)
    remote_ids: dict[str, int] = {}
    for (row, _), raw_value in id_cells.items():
        identifier = _identifier(raw_value)
        if identifier is None:
            continue
        if identifier in remote_ids:
            raise SyncError("remote_duplicate_id")
        remote_ids[identifier] = row
    occupied_rows = set(remote_ids.values())
    last_id_row = max(occupied_rows, default=0)
    # Never fill an internal hole: it may sit before a row already committed remotely.
    if any(row not in occupied_rows for row in range(1, last_id_row + 1)):
        raise SyncError("remote_id_gap")
    return row_count, remote_ids

def _encode_cell(row: int, column: int, value: object) -> dict[str, Any]:
    cell: dict[str, Any] = {"row": row, "col": column}
    if value is None or value == "":
        cell.update(value_type="STRING", string_value="")
    elif isinstance(value, bool):
        cell.update(value_type="BOOL", bool_value=value)
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise SyncError("source_numeric_value_invalid")
        cell.update(value_type="NUMBER", number_value=value)
    else:
        cell.update(value_type="STRING", string_value=str(value))
    return cell

def _check_batch_readback(cells: dict[tuple[int, int], object], *,
                          columns: list[str], records: list[list[object]],
                          row_numbers: list[int], id_committed: bool,
                          manual_before: dict[tuple[int, int], object]) -> None:
    for row_number, record in zip(row_numbers, records):
        for column, header in enumerate(columns):
            actual = cells.get((row_number, column))
            if header in MANUAL_FIELDS:
                expected = manual_before.get((row_number, column))
            elif header == ID_FIELD and not id_committed:
                expected = None
            else:
                expected = record[column]
            if actual != expected and not (actual in (None, "") and expected in (None, "")):
                raise SyncError("readback_mismatch")

def _write_batch(client: Any, *, file_id: str, sheet_id: str,
                 columns: list[str], records: list[list[object]], row_numbers: list[int]) -> None:
    start_row, end_row = min(row_numbers), max(row_numbers)
    before = _range_cells(client, file_id, sheet_id, start_row=start_row, end_row=end_row,
                          start_col=0, end_col=len(columns) - 1)
    manual_before = {
        (row, column): before.get((row, column))
        for row in row_numbers
        for column, header in enumerate(columns)
        if header in MANUAL_FIELDS
    }
    id_column = columns.index(ID_FIELD)
    if any(_identifier(before.get((row, id_column))) is not None for row in row_numbers):
        raise SyncError("append_target_row_already_has_id")

    source_values = [
        _encode_cell(row_number, column, value)
        for row_number, record in zip(row_numbers, records)
        for column, (header, value) in enumerate(zip(columns, record))
        if header not in MANUAL_FIELDS and header != ID_FIELD
    ]
    _call_tool(client, "sheet.set_range_value", {
        "file_id": file_id, "sheet_id": sheet_id, "values": source_values,
    })

    source_readback = _range_cells(client, file_id, sheet_id, start_row=start_row,
                                   end_row=end_row, start_col=0, end_col=len(columns) - 1)
    _check_batch_readback(source_readback, columns=columns, records=records,
                          row_numbers=row_numbers, id_committed=False,
                          manual_before=manual_before)

    id_values = [
        _encode_cell(row_number, id_column, record[id_column])
        for row_number, record in zip(row_numbers, records)
    ]
    _call_tool(client, "sheet.set_range_value", {
        "file_id": file_id, "sheet_id": sheet_id, "values": id_values,
    })

    final_readback = _range_cells(client, file_id, sheet_id, start_row=start_row,
                                  end_row=end_row, start_col=0, end_col=len(columns) - 1)
    _check_batch_readback(final_readback, columns=columns, records=records,
                          row_numbers=row_numbers, id_committed=True,
                          manual_before=manual_before)

@contextmanager
def _sync_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".sync.lock"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncError("content_work_orders_sync_busy") from None
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)

def _safe_error(error: Exception) -> str:
    if isinstance(error, SyncError):
        return str(error)
    return f"operation_failed:{type(error).__name__}"

def sync(workspace, source_file, as_of_date, run_id, config_path=None, client=None) -> dict[str, Any]:
    """Append newly observed work orders through ``as_of_date`` and write a receipt."""
    workspace_path = Path(workspace).expanduser().resolve()
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise SyncError("invalid_run_id")
    as_of = _iso_date(as_of_date, "as_of_date")
    root = workspace_path / RECEIPT_ROOT
    run_dir = root / "Runs" / run_id
    receipt_path = run_dir / "receipt.json"

    with _sync_lock(root):
        if run_dir.exists() or run_dir.is_symlink():
            raise SyncError("run_id_already_used")
        run_dir.mkdir(parents=True, exist_ok=False)
        receipt: dict[str, Any] = {
            "schema_version": RECEIPT_SCHEMA,
            "run_id": run_id,
            "status": "running",
            "source_path": str(Path(source_file).expanduser()),
            "source_sha256": None,
            "date_field": DATE_FIELD,
            "start_date": None,
            "window_mode": None,
            "as_of_date": as_of.isoformat(),
            "secondary_channel_filter": None,
            "max_source_date": None,
            "candidates": 0,
            "added": 0,
            "total": 0,
            "readback_status": "not_started",
        }
        _write_json(receipt_path, receipt)
        try:
            selected_config_path = (_resolve_path(config_path, base=workspace_path)
                                    if config_path is not None else
                                    workspace_path / ".private" / "content-work-orders.json")
            config = _read_config(selected_config_path)
            start = date.fromisoformat(config["start_date"])
            window_mode = config.get("window_mode", "fixed")
            if window_mode == "current_month":
                start = max(start, as_of.replace(day=1))
            if as_of < start:
                raise SyncError("as_of_date_before_start_date")
            receipt["start_date"] = start.isoformat()
            receipt["window_mode"] = window_mode
            secondary_channel_platforms = config.get("secondary_channel_platforms")
            if secondary_channel_platforms is not None:
                receipt["secondary_channel_filter"] = {
                    "field": SECONDARY_CHANNEL_FIELD,
                    "canonical_platforms": secondary_channel_platforms,
                }

            source_path = _resolve_path(source_file, base=workspace_path)
            receipt["source_path"] = str(source_path)
            receipt["source_sha256"] = _hash_file(source_path) if source_path.is_file() else None
            columns = config["columns"]
            candidates, maximum_date = _load_candidates(
                source_path, columns, start, as_of,
                secondary_channel_platforms=secondary_channel_platforms,
            )
            receipt["max_source_date"] = maximum_date.isoformat() if maximum_date else None
            receipt["candidates"] = len(candidates)

            token_file = _resolve_path(config["token_file"], base=selected_config_path.parent)
            active_client = client if client is not None else TencentDocsMCPClient(token_file)
            file_id, sheet_id = config["file_id"], config["sheet_id"]
            row_count, remote_ids = _remote_state(
                active_client, file_id=file_id, sheet_id=sheet_id, columns=columns,
            )
            additions = [record for record in candidates if record[columns.index(ID_FIELD)] not in remote_ids]
            receipt["total"] = len(remote_ids)
            if additions:
                last_id_row = max(remote_ids.values(), default=0)
                next_row = last_id_row + 1
                required_rows = next_row + len(additions)
                missing_rows = max(0, required_rows - row_count)
                if missing_rows:
                    _call_tool(active_client, "sheet.insert_dimension", {
                        "file_id": file_id,
                        "sheet_id": sheet_id,
                        "dimension_type": "row",
                        "index": row_count - 1,
                        "count": missing_rows,
                        "direction": "after",
                    })
                committed = 0
                for offset in range(0, len(additions), BATCH_SIZE):
                    batch = additions[offset:offset + BATCH_SIZE]
                    row_numbers = list(range(next_row + offset, next_row + offset + len(batch)))
                    _write_batch(
                        active_client,
                        file_id=file_id,
                        sheet_id=sheet_id,
                        columns=columns,
                        records=batch,
                        row_numbers=row_numbers,
                    )
                    committed += len(batch)
                    receipt["added"] = committed
                    receipt["total"] = len(remote_ids) + committed
                    _write_json(receipt_path, receipt)
            receipt["readback_status"] = "passed"
            receipt["total"] = len(remote_ids) + receipt["added"]
            receipt["status"] = "passed"
            _write_json(receipt_path, receipt)
            return {**receipt, "receipt_path": str(receipt_path)}
        except Exception as error:
            receipt["status"] = "failed"
            receipt["readback_status"] = "failed"
            receipt["error"] = _safe_error(error)
            _write_json(receipt_path, receipt)
            if isinstance(error, SyncError):
                raise
            raise SyncError(_safe_error(error)) from None

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-file", type=Path, required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--config-path", type=Path)
    args = parser.parse_args(argv)
    try:
        result = sync(args.workspace, args.source_file, args.as_of_date, args.run_id, args.config_path)
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "error": _safe_error(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
