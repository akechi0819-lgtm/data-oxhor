from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import tempfile

import openpyxl
import pytest
from openpyxl.utils.datetime import CALENDAR_MAC_1904, to_excel

from data_acquisition.jobs.sync_content_work_orders import sync


MANUAL_FIELDS = ("素材ID", "账号来源", "工单跟进情况", "重点资源意向", "所属条线")
BASE_HEADERS = [
    "团队", "分配时间", "学员号", "素材ID", "账号来源", "跟进顾问",
    "工单跟进情况", "ID", "重点资源意向", "所属条线",
]
COLUMNS = BASE_HEADERS + [f"业务字段_{index:03d}" for index in range(103 - len(BASE_HEADERS))]
SOURCE_EXTRA_HEADERS = [f"源文件额外字段_{index:03d}" for index in range(25)]
ID_COLUMN = COLUMNS.index("ID")


def _config(
    tmp_path: Path,
    *,
    secondary_channel_platforms: list[str] | None = None,
    start_date: str = "2026-11-01",
    window_mode: str | None = None,
) -> Path:
    path = tmp_path / "content-work-orders.json"
    config = {
        "file_id": "file-test",
        "sheet_id": "sheet-test",
        "token_file": "unused-token",
        "start_date": start_date,
        "columns": COLUMNS,
    }
    if secondary_channel_platforms is not None:
        config["secondary_channel_platforms"] = secondary_channel_platforms
    if window_mode is not None:
        config["window_mode"] = window_mode
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return path


def _write_source(
    path: Path,
    rows: list[dict],
    *,
    reverse: bool = True,
    omit: set[str] | None = None,
    epoch=None,
) -> Path:
    omitted = omit or set()
    source_headers = [header for header in COLUMNS if header not in MANUAL_FIELDS and header not in omitted]
    source_headers.extend(SOURCE_EXTRA_HEADERS)
    source_headers.extend(
        field for field in ("二级渠道", "一级渠道", "资源描述")
        if any(field in row for row in rows)
    )
    if reverse:
        source_headers.reverse()
    workbook = openpyxl.Workbook()
    if epoch is not None:
        workbook.epoch = epoch
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


def test_current_month_window_advances_from_november_to_december(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-oct", date(2026, 10, 31)),
        _row("wo-nov-start", date(2026, 11, 1)),
        _row("wo-nov-end", date(2026, 11, 30)),
        _row("wo-dec-start", date(2026, 12, 1)),
        _row("wo-dec-end", date(2026, 12, 2)),
    ])
    config_path = _config(tmp_path, window_mode="current_month")
    november_client = FakeMCPClient(rows=1)
    december_client = FakeMCPClient(rows=1)

    november = sync(
        workspace=tmp_path / "workspace", source_file=source,
        as_of_date="2026-11-30", run_id="run-current-month-november",
        config_path=config_path, client=november_client,
    )
    december = sync(
        workspace=tmp_path / "workspace", source_file=source,
        as_of_date="2026-12-02", run_id="run-current-month-december",
        config_path=config_path, client=december_client,
    )

    assert november["start_date"] == "2026-11-01"
    assert november["window_mode"] == "current_month"
    assert november["added"] == 2
    assert _remote_ids(november_client) == ["wo-nov-start", "wo-nov-end"]
    assert december["start_date"] == "2026-12-01"
    assert december["window_mode"] == "current_month"
    assert december["added"] == 2
    assert _remote_ids(december_client) == ["wo-dec-start", "wo-dec-end"]


def test_unconfigured_window_mode_keeps_fixed_start_date(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-nov", date(2026, 11, 30)),
        _row("wo-dec", date(2026, 12, 1)),
    ])
    client = FakeMCPClient(rows=1)

    result = sync(
        workspace=tmp_path / "workspace", source_file=source,
        as_of_date="2026-12-01", run_id="run-fixed-window",
        config_path=_config(tmp_path), client=client,
    )

    assert result["start_date"] == "2026-11-01"
    assert result["window_mode"] == "fixed"
    assert result["added"] == 2
    assert _remote_ids(client) == ["wo-nov", "wo-dec"]


def test_unknown_window_mode_is_rejected(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [_row("wo-1", date(2026, 11, 1))])
    client = FakeMCPClient(rows=1)

    with pytest.raises(RuntimeError, match="config_window_mode_unsupported"):
        sync(
            workspace=tmp_path / "workspace", source_file=source,
            as_of_date="2026-11-01", run_id="run-unknown-window",
            config_path=_config(tmp_path, window_mode="previous_month"), client=client,
        )

    assert not any(name in {"sheet.set_range_value", "sheet.insert_dimension"}
                   for name, _ in client.calls)


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


def test_new_manual_columns_may_be_absent_from_source_and_are_never_written(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-existing", date(2026, 11, 1)),
        _row("wo-new", date(2026, 11, 2)),
    ])
    source_workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        source_headers = list(next(source_workbook.active.iter_rows(min_row=1, max_row=1, values_only=True)))
    finally:
        source_workbook.close()
    assert "重点资源意向" not in source_headers
    assert "所属条线" not in source_headers

    client = FakeMCPClient(rows=2)
    client.grid[1][ID_COLUMN] = "wo-existing"
    intent_col = COLUMNS.index("重点资源意向")
    line_col = COLUMNS.index("所属条线")
    client.grid[1][intent_col] = "重点资源人工标记"
    client.grid[1][line_col] = "人工归属条线"

    result = _run(tmp_path, client, source, day="2026-11-02")

    assert result["added"] == 1
    assert client.grid[1][intent_col] == "重点资源人工标记"
    assert client.grid[1][line_col] == "人工归属条线"
    assert client.grid[2][intent_col] is None
    assert client.grid[2][line_col] is None
    writes = [
        cell
        for name, arguments in client.calls if name == "sheet.set_range_value"
        for cell in arguments["values"]
    ]
    assert not any(cell["col"] in {intent_col, line_col} for cell in writes)


def test_source_fields_around_manual_columns_keep_header_mapping_and_103_column_schema(tmp_path: Path) -> None:
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

    assert len(COLUMNS) == 103
    assert schema["col_count"] == 103
    assert len(source_headers) == 123
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


def test_103_column_config_matches_remote_and_syncs(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [_row("wo-1", date(2026, 11, 1))])
    config_path = _config(tmp_path)
    client = FakeMCPClient(rows=1)

    result = sync(
        tmp_path / "workspace", source, "2026-11-01", "run-current-config",
        config_path=config_path, client=client,
    )

    assert result["added"] == 1
    assert client.grid[1][COLUMNS.index("ID")] == "wo-1"
    assert client.call_tool("sheet.get_sheet_info", {"file_id": "file-test"})["sheets"][0]["col_count"] == 103


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


@pytest.mark.parametrize("epoch", [None, CALENDAR_MAC_1904], ids=["1900-epoch", "1904-epoch"])
def test_numeric_string_source_date_uses_workbook_epoch(tmp_path: Path, epoch) -> None:
    assigned = date(2026, 11, 1)
    serial = str(to_excel(assigned, epoch=epoch)) if epoch is not None else str(to_excel(assigned))
    source = _write_source(
        tmp_path / "source.xlsx", [_row("wo-serial", serial)], epoch=epoch,
    )
    client = FakeMCPClient(rows=1)

    result = _run(tmp_path, client, source)

    assert result["added"] == 1
    assert client.grid[1][COLUMNS.index("分配时间")] == "2026-11-01"
    assert _remote_ids(client) == ["wo-serial"]


@pytest.mark.parametrize("assigned", ["not a date", "NaN", "1e309", "1e20"])
def test_invalid_numeric_string_source_date_is_rejected(tmp_path: Path, assigned: str) -> None:
    source = _write_source(tmp_path / "source.xlsx", [_row("wo-invalid-date", assigned)])
    client = FakeMCPClient(rows=1)

    with pytest.raises(RuntimeError, match="source_work_order_date_invalid"):
        _run(tmp_path, client, source)

    assert not any(name in {"sheet.set_range_value", "sheet.insert_dimension"}
                   for name, _ in client.calls)


def test_secondary_channel_filter_uses_canonical_platform_and_only_secondary_channel(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-tencent", date(2026, 11, 1), extra={"二级渠道": "腾讯广告"}),
        _row("wo-douyin", date(2026, 11, 1), extra={"二级渠道": "抖音本地推"}),
        _row("wo-laike", date(2026, 11, 1), extra={"二级渠道": "抖音来客"}),
        _row("wo-feiyu", date(2026, 11, 1), extra={"二级渠道": "巨量飞鱼"}),
        _row("wo-xhs", date(2026, 11, 1), extra={"二级渠道": "小红书"}),
        _row("wo-first-channel-only", date(2026, 11, 1), extra={
            "二级渠道": "大众点评", "一级渠道": "腾讯广告", "资源描述": "抖音推广"
        }),
        _row("wo-description-only", date(2026, 11, 1), extra={
            "二级渠道": "其他线上来源", "一级渠道": "小红书", "资源描述": "腾讯广告"
        }),
        _row("wo-after-cutoff", date(2026, 11, 3), extra={"二级渠道": "小红书"}),
    ])
    client = FakeMCPClient(rows=1)
    config_path = _config(
        tmp_path, secondary_channel_platforms=["腾讯广告", "抖音", "小红书"]
    )

    result = sync(
        workspace=tmp_path / "workspace", source_file=source,
        as_of_date="2026-11-02", run_id="run-secondary-filter",
        config_path=config_path, client=client,
    )

    assert result["candidates"] == 5
    assert result["added"] == 5
    assert result["max_source_date"] == "2026-11-03"
    assert _remote_ids(client) == [
        "wo-tencent", "wo-douyin", "wo-laike", "wo-feiyu", "wo-xhs",
    ]
    assert result["secondary_channel_filter"] == {
        "field": "二级渠道",
        "canonical_platforms": ["腾讯广告", "抖音", "小红书"],
    }


def test_unconfigured_secondary_channel_filter_preserves_existing_behavior(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [
        _row("wo-any-channel", date(2026, 11, 1), extra={"二级渠道": "大众点评"}),
    ])
    client = FakeMCPClient(rows=1)

    result = _run(tmp_path, client, source)

    assert result["added"] == 1
    assert _remote_ids(client) == ["wo-any-channel"]
    assert result["secondary_channel_filter"] is None


def test_configured_secondary_channel_filter_requires_source_field(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.xlsx", [_row("wo-no-channel", date(2026, 11, 1))])
    client = FakeMCPClient(rows=1)
    config_path = _config(tmp_path, secondary_channel_platforms=["腾讯广告"])

    with pytest.raises(RuntimeError, match="source_secondary_channel_missing"):
        sync(
            workspace=tmp_path / "workspace", source_file=source,
            as_of_date="2026-11-01", run_id="run-missing-secondary-channel",
            config_path=config_path, client=client,
        )

    assert not any(name in {"sheet.set_range_value", "sheet.insert_dimension"}
                   for name, _ in client.calls)


@pytest.mark.parametrize(("platforms", "error"), [
    ([], "config_secondary_channel_platforms_must_be_nonempty_unique_list"),
    (["抖音", "抖音"], "config_secondary_channel_platforms_must_be_nonempty_unique_list"),
    (["微信"], "config_secondary_channel_platform_unsupported"),
])
def test_secondary_channel_filter_config_requires_unique_supported_platforms(
    tmp_path: Path, platforms: list[str], error: str,
) -> None:
    source = _write_source(tmp_path / "source.xlsx", [_row("wo-1", date(2026, 11, 1))])
    client = FakeMCPClient(rows=1)
    config_path = _config(tmp_path, secondary_channel_platforms=platforms)

    with pytest.raises(RuntimeError, match=error):
        sync(
            workspace=tmp_path / "workspace", source_file=source,
            as_of_date="2026-11-01", run_id="run-invalid-secondary-filter",
            config_path=config_path, client=client,
        )

    assert not any(name in {"sheet.set_range_value", "sheet.insert_dimension"}
                   for name, _ in client.calls)


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
