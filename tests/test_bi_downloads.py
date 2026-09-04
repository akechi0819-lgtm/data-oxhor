from __future__ import annotations

from pathlib import Path

from data_acquisition.auth.auth_sessions import AuthSessionPaths, write_auth_session
from data_acquisition.connectors.bi.bi_downloads import BIExportConfig, build_cash_export_request, build_order_export_request


def test_bi_exports_have_only_confirmed_date_filters() -> None:
    config = BIExportConfig()
    order = build_order_export_request(config, "2025-06-01", "2026-09-02", "")
    cash = build_cash_export_request(config, "2025-06-01", "2026-09-02")

    assert [item["name"] for item in order.payload["filters"]] == ["分配时间"]
    assert order.payload["filters"][0]["filterValue"] == ["2025-06-01", "2026-09-02"]
    assert [item["name"] for item in cash.payload["cards"][0]["filters"]] == ["业务日期"]
    assert cash.payload["cards"][0]["filters"][0]["filterValue"] == ["2025-06-01", "2026-09-02"]


def test_auth_session_stays_under_its_workspace(tmp_path: Path) -> None:
    paths = AuthSessionPaths(tmp_path, "bi")
    write_auth_session("bi", cookies=[{"name": "sid", "value": "test"}], local_storage={"token": "test"}, paths=paths)

    assert paths.cookies.is_file()
    assert paths.local_storage.is_file()
    assert paths.cookies.stat().st_mode & 0o777 == 0o600
