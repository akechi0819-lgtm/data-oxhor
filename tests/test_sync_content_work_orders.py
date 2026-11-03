from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import tempfile

import openpyxl
import pytest

from data_acquisition.jobs.sync_content_work_orders import sync


MANUAL_FIELDS = ("素材ID", "账号来源", "工单跟进情况")
BASE_HEADERS = ["团队", "分配时间", "学员号", "素材ID", "账号来源", "跟进顾问", "工单跟进情况", "ID"]
COLUMNS = BASE_HEADERS + [f"业务字段_{index:03d}" for index in range(104 - len(BASE_HEADERS))]
SOURCE_EXTRA_HEADERS = [f"源文件额外字段_{index:03d}" for index in range(25)]
ID_COLUMN = COLUMNS.index("ID")


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "content-work-orders.json"
    path.write_text(json.dumps({
        "file_id": "file-test",
        "sheet_id": "sheet-test",
        "token_file": "unused-token",
        "start_date": "2026-11-01",
        "columns": COLUMNS,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def _write_source(
    path: Path,
    rows: list[dict],
    *,
    reverse: bool = True,
    omit: set[str] | None = None,
) -> Path:
    omitted = omit or set()
    source_headers = [header for header in COLUMNS if header not in MANUAL_FIELDS and header not in omitted]
    source_headers.extend(SOURCE_EXTRA_HEADERS)
    if reverse:
        source_headers.reverse()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "工单明细导出用表"
    sheet.append(source_headers)
    for row in rows:
        sheet.append([row.get(header) for header in source_headers])
    workbook.save(path)
    workbook.close()
    return path


def _row(identifier, assigned, *, learner="学员-1", team="测试组", extra=None):
    result = {header: None for header in COLUMNS}
    result.update({
        "团队": team,
        "分配时间": assigned,
        "学员号": learner,
        "ID": identifier,
    })
    result.update(extra or {})
    return result


class FakeMCPClient:
    def __init__(self, *, headers=None, rows=1):
        header_values = list(headers if headers is not None else COLUMNS)
        self.grid = [header_values + [None] * (len(COLUMNS) - len(header_values))]
        self.grid.extend([[None] * len(COLUMNS) for _ in range(max(0, rows - 1))])
        self.calls = []
        self.fail_id_batch_after_prefix = False
        self.fail_after_partial_source_write = False
        self._partial_failed = False

    def _cell(self, row, col, value):
        while len(self.grid) <= row:
            self.grid.append([None] * len(COLUMNS))
        if value in (None, ""):
            self.grid[row][col] = None
        else:
            self.grid[row][col] = value

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "sheet.get_sheet_info":
            return {"sheets": [{
                "sheet_id": "sheet-test",
                "row_count": len(self.grid),
                "col_count": len(self.grid[0]),
            }]}
        if name == "sheet.get_cell_data":
            cells = []
            for row in range(arguments["start_row"], arguments["end_row"] + 1):
                for col in range(arguments["start_col"], arguments["end_col"] + 1):
                    value = self.grid[row][col] if row < len(self.grid) else None
                    if value is None or value == "":
                        continue
                    cell = {"string_value": "", "number_value": 0, "bool_value": False}
                    if isinstance(value, bool):
                        cell.update(value_type="BOOL", bool_value=value)
                    elif isinstance(value, (int, float)):
                        cell.update(value_type="NUMBER", number_value=value)
                    else:
                        cell.update(value_type="STRING", string_value=str(value))
                    cells.append({"row": row, "col": col, **cell})
            return {"cells": cells}
        if name == "sheet.insert_dimension":
            assert arguments["dimension_type"] == "row"
            index = arguments["index"] + 1
            self.grid[index:index] = [
                [None] * len(COLUMNS) for _ in range(arguments["count"])
            ]
            return {"ok": True}
        if name == "sheet.set_range_value":
            values = arguments["values"]
            is_id_commit = bool(values) and all(value["col"] == ID_COLUMN for value in values)
            if is_id_commit:
                if self.fail_id_batch_after_prefix:
                    value = values[0]
                    cell_value = value.get("string_value", value.get("number_value", value.get("bool_value")))
                    self._cell(value["row"], value["col"], cell_value)
                    self.fail_id_batch_after_prefix = False
                    raise RuntimeError("simulated partial commit")
            elif self.fail_after_partial_source_write and not self._partial_failed:
                for value in values[:7]:
                    self._cell(value["row"], value["col"], value.get("string_value", value.get("number_value", value.get("bool_value"))))
                self._partial_failed = True
                raise RuntimeError("simulated partial source write")
            for value in values:
                cell_value = value.get("string_value", value.get("number_value", value.get("bool_value")))
                self._cell(value["row"], value["col"], cell_value)
            return {"ok": True}
        raise AssertionError(f"unexpected tool: {name}")


def _run(tmp_path: Path, client: FakeMCPClient, source: Path, *, day="2026-11-01", run_id="run-test"):
    return sync(
        workspace=tmp_path / "workspace",
        source_file=source,
        as_of_date=day,
        run_id=run_id,
        config_path=_config(tmp_path),
        client=client,
    )


def _remote_ids(client: FakeMCPClient) -> list[str]:
    return [str(row[ID_COLUMN]) for row in client.grid[1:] if row[ID_COLUMN] not in (None, "")]


def test_new_append_repeat_zero_then_next_day_catches_up(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-1", date(2026, 11, 1), learner=88001),
        _row("wo-2", date(2026, 11, 2), learner=88002),
    ])
    client = FakeMCPClient(rows=1)

    first = _run(tmp_path, client, source, run_id="run-first")
    repeated = _run(tmp_path, client, source, run_id="run-repeat")
    next_day = _run(tmp_path, client, source, day="2026-11-02", run_id="run-next-day")

    assert first["added"] == 1
    assert repeated["added"] == 0
    assert repeated["total"] == 1
    assert next_day["added"] == 1
    assert next_day["total"] == 2
    assert _remote_ids(client) == ["wo-1", "wo-2"]
    assert first["readback_status"] == "passed"
    id_batches = [values for name, args in client.calls if name == "sheet.set_range_value"
                  for values in [args["values"]] if all(cell["col"] == ID_COLUMN for cell in values)]
    assert len(id_batches) == 2
    assert any(name == "sheet.insert_dimension" for name, _ in client.calls)


def test_exports_are_written_in_chunks_of_twenty_five(tmp_path: Path) -> None:
    rows = [_row(f"wo-{index}", date(2026, 11, 1), learner=88000 + index)
            for index in range(26)]
    source = _write_source(tmp_path / "source.xlsx", rows)
    client = FakeMCPClient(rows=1)

    result = _run(tmp_path, client, source)

    writes = [args["values"] for name, args in client.calls if name == "sheet.set_range_value"]
    id_batches = [batch for batch in writes if all(cell["col"] == ID_COLUMN for cell in batch)]
    assert result["added"] == 26
    assert [len(batch) for batch in id_batches] == [25, 1]


def test_pre_november_source_is_successful_zero_with_real_max_date(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-oct-25", date(2026, 10, 25)),
        _row("wo-oct-29", date(2026, 10, 29)),
    ])
    client = FakeMCPClient(rows=1)

    result = _run(tmp_path, client, source, day="2026-11-01")

    assert result["status"] == "passed"
    assert result["candidates"] == 0
    assert result["added"] == 0
    assert result["max_source_date"] == "2026-10-29"
    assert not any(name == "sheet.set_range_value" for name, _ in client.calls)


def test_manual_columns_are_never_overwritten(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-new", date(2026, 11, 1), extra={
            "跟进顾问": "顾问来源值", "业务字段_000": "source-value",
        }),
        _row("wo-next", date(2026, 11, 2), extra={
            "跟进顾问": "次日顾问来源值", "业务字段_000": "next-day-value",
        }),
    ])
    client = FakeMCPClient(rows=3)
    account_source_col = COLUMNS.index("账号来源")
    followup_col = COLUMNS.index("工单跟进情况")
    client.grid[1][account_source_col] = "人工账号来源"
    client.grid[1][followup_col] = "人工已填写"

    result = _run(tmp_path, client, source)
    repeated = _run(tmp_path, client, source, run_id="run-repeat-manual")
    next_day = _run(tmp_path, client, source, day="2026-11-02", run_id="run-next-manual")

    assert result["added"] == 1
    assert repeated["added"] == 0
    assert next_day["added"] == 1
    assert client.grid[1][account_source_col] == "人工账号来源"
    assert client.grid[1][followup_col] == "人工已填写"
    assert client.grid[2][account_source_col] is None
    assert client.grid[2][followup_col] is None
    assert client.grid[1][COLUMNS.index("素材ID")] is None
    assert client.grid[1][COLUMNS.index("跟进顾问")] == "顾问来源值"
    assert client.grid[1][COLUMNS.index("业务字段_000")] == "source-value"
    assert client.grid[2][COLUMNS.index("跟进顾问")] == "次日顾问来源值"
    assert client.grid[2][COLUMNS.index("业务字段_000")] == "next-day-value"


def test_source_fields_around_manual_columns_keep_header_mapping_and_104_column_schema(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-map", date(2026, 11, 1), learner=88031, team="团队映射值",
             extra={"跟进顾问": "顾问映射值", "业务字段_000": "ID后业务字段"}),
    ])
    client = FakeMCPClient(rows=1)

    result = _run(tmp_path, client, source)
    schema = client.call_tool("sheet.get_sheet_info", {"file_id": "file-test"})["sheets"][0]
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        source_headers = list(next(workbook.active.iter_rows(min_row=1, max_row=1, values_only=True)))
    finally:
        workbook.close()

    assert len(COLUMNS) == 104
    assert schema["col_count"] == 104
    assert len(source_headers) == 126
    assert "录入来源" not in source_headers
    assert source_headers != [header for header in COLUMNS if header not in MANUAL_FIELDS]
    assert result["added"] == 1
    assert client.grid[1][COLUMNS.index("团队")] == "团队映射值"
    assert client.grid[1][COLUMNS.index("分配时间")] == "2026-11-01"
    assert client.grid[1][COLUMNS.index("学员号")] == "88031"
    assert client.grid[1][COLUMNS.index("素材ID")] is None
    assert client.grid[1][COLUMNS.index("账号来源")] is None
    assert COLUMNS.index("账号来源") == COLUMNS.index("素材ID") + 1
    assert client.grid[1][COLUMNS.index("跟进顾问")] == "顾问映射值"
    assert client.grid[1][COLUMNS.index("工单跟进情况")] is None
    assert client.grid[1][COLUMNS.index("ID")] == "wo-map"
    assert client.grid[1][COLUMNS.index("业务字段_000")] == "ID后业务字段"


def test_105_column_config_is_rejected(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [_row("wo-1", date(2026, 11, 1))])
    config_path = _config(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["columns"].append("录入来源")
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    client = FakeMCPClient(rows=1)

    with pytest.raises(RuntimeError, match="config_columns_must_be_104_unique_headers"):
        sync(tmp_path / "workspace", source, "2026-11-01", "run-legacy-config",
             config_path=config_path, client=client)

    assert not any(name in {"sheet.set_range_value", "sheet.insert_dimension"}
                   for name, _ in client.calls)


def test_missing_nonmanual_source_column_fails_without_writing(tmp_path: Path) -> None:
    source = _write_source(
        tmp_path / "source.xlsx", [_row("wo-1", date(2026, 11, 1))], omit={"业务字段_000"}
    )
    client = FakeMCPClient(rows=1)

    with pytest.raises(RuntimeError, match="source_headers_missing_required_fields"):
        _run(tmp_path, client, source)

    assert not any(name in {"sheet.set_range_value", "sheet.insert_dimension"}
                   for name, _ in client.calls)


def test_header_mismatch_fails_without_writing(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [_row("wo-1", date(2026, 11, 1))])
    wrong_headers = list(COLUMNS)
    wrong_headers[0] = "错误表头"
    client = FakeMCPClient(headers=wrong_headers)

    with pytest.raises(RuntimeError, match="remote_header_mismatch"):
        _run(tmp_path, client, source)

    assert not any(name in {"sheet.set_range_value", "sheet.insert_dimension"} for name, _ in client.calls)
    receipt = json.loads((tmp_path / "workspace/Work/ContentWorkOrders/Runs/run-test/receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["error"] == "remote_header_mismatch"


def test_partial_id_commit_reuses_uncommitted_tail_on_retry(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-1", date(2026, 11, 1), extra={"业务字段_001": "one"}),
        _row("wo-2", date(2026, 11, 1), extra={"业务字段_001": "two"}),
        _row("wo-3", date(2026, 11, 1), extra={"业务字段_001": "three"}),
    ])
    client = FakeMCPClient(rows=1)
    client.fail_id_batch_after_prefix = True

    with pytest.raises(RuntimeError, match="mcp_tool_call_failed:sheet.set_range_value"):
        _run(tmp_path, client, source, run_id="run-partial")
    failed = json.loads((tmp_path / "workspace/Work/ContentWorkOrders/Runs/run-partial/receipt.json").read_text())
    assert failed["status"] == "failed"
    assert failed["added"] == 0
    assert _remote_ids(client) == ["wo-1"]

    retry = _run(tmp_path, client, source, run_id="run-retry")
    assert retry["status"] == "passed"
    assert retry["added"] == 2
    assert retry["total"] == 3
    assert _remote_ids(client) == ["wo-1", "wo-2", "wo-3"]
    assert client.grid[2][COLUMNS.index("业务字段_001")] == "two"
    assert client.grid[3][COLUMNS.index("业务字段_001")] == "three"


def test_partial_source_write_is_overwritten_before_id_commit(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-1", date(2026, 11, 1), extra={"业务字段_000": "new"}),
    ])
    client = FakeMCPClient(rows=1)
    client.fail_after_partial_source_write = True

    with pytest.raises(RuntimeError, match="mcp_tool_call_failed:sheet.set_range_value"):
        _run(tmp_path, client, source, run_id="run-partial-source")
    assert _remote_ids(client) == []

    retry = _run(tmp_path, client, source, run_id="run-retry-source")
    assert retry["added"] == 1
    assert _remote_ids(client) == ["wo-1"]
    assert client.grid[1][COLUMNS.index("业务字段_000")] == "new"


def test_id_date_normalization_and_source_cutoff(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row(700, date(2026, 10, 31), learner=77000),
        _row(701, datetime(2026, 11, 1), learner=77001),
        _row(702, date(2026, 11, 2), learner=77002),
        _row(703, date(2026, 11, 3), learner=77003),
    ])
    client = FakeMCPClient(rows=1)

    result = _run(tmp_path, client, source, day="2026-11-02")

    assert result["candidates"] == 2
    assert result["added"] == 2
    assert result["max_source_date"] == "2026-11-03"
    assert _remote_ids(client) == ["701", "702"]
    assert client.grid[1][COLUMNS.index("学员号")] == "77001"
    assert client.grid[2][COLUMNS.index("学员号")] == "77002"
    assert client.grid[1][COLUMNS.index("分配时间")] == "2026-11-01"
    assert client.grid[2][COLUMNS.index("分配时间")] == "2026-11-02"


def test_identical_source_ids_deduplicate_but_conflicting_source_ids_fail(tmp_path: Path) -> None:
    same = _row("wo-same", date(2026, 11, 1), extra={"业务字段_000": "same"})
    source = _write_source(tmp_path / "source.xlsx", [same, dict(same)])
    client = FakeMCPClient(rows=1)
    result = _run(tmp_path, client, source)
    assert result["candidates"] == 1
    assert result["added"] == 1

    conflict = dict(same)
    conflict["业务字段_000"] = "different"
    conflicting_source = _write_source(tmp_path / "conflict.xlsx", [same, conflict])
    second_client = FakeMCPClient(rows=1)
    with pytest.raises(RuntimeError, match="source_id_conflict"):
        _run(tmp_path, second_client, conflicting_source, run_id="run-conflict")
    assert not any(name == "sheet.set_range_value" for name, _ in second_client.calls)


def test_duplicate_remote_ids_fail_before_writes(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [_row("wo-new", date(2026, 11, 1))])
    client = FakeMCPClient(rows=3)
    client.grid[1][ID_COLUMN] = "wo-old"
    client.grid[2][ID_COLUMN] = "wo-old"

    with pytest.raises(RuntimeError, match="remote_duplicate_id"):
        _run(tmp_path, client, source)

    assert not any(name == "sheet.set_range_value" for name, _ in client.calls)


def test_noncontiguous_remote_ids_fail_before_writes(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [_row("wo-new", date(2026, 11, 1))])
    client = FakeMCPClient(rows=4)
    client.grid[1][ID_COLUMN] = "wo-1"
    client.grid[3][ID_COLUMN] = "wo-3"

    with pytest.raises(RuntimeError, match="remote_id_gap"):
        _run(tmp_path, client, source)

    assert not any(name in {"sheet.set_range_value", "sheet.insert_dimension"} for name, _ in client.calls)
