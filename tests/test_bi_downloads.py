from __future__ import annotations

from pathlib import Path

from data_acquisition.auth.auth_sessions import AuthSessionPaths, write_auth_session
from data_acquisition.connectors.bi.bi_downloads import BIExportConfig, build_cash_export_request, build_order_export_request


def test_order_export_uses_observed_batch_request_and_cash_request_stays_unchanged() -> None:
    config = BIExportConfig()
    start_date, end_date = "2026-08-03", "2026-11-03"
    order = build_order_export_request(config, start_date, end_date, "")
    cash = build_cash_export_request(config, start_date, end_date)

    assert config.page_url == "https://bibr.staff.xdf.cn/page/dc1bca538e57f49038476541"
    assert order.api == "/api/batchExportCardExcel"
    assert order.payload == {
        "pgId": "dc1bca538e57f49038476541",
        "cards": [
            {
                "cdId": "j7378d2612e2242ab85e3140",
                "saveFilters": False,
                "filters": [
                    {
                        "name": "分配日期",
                        "fdId": "bf9ab43250ab34a98836dcf4",
                        "dsId": "i2e269a4ea5d34590ad16727",
                        "cdId": "j7378d2612e2242ab85e3140",
                        "fdType": "DATE",
                        "filterType": "BT",
                        "sourceCdId": "xa6e577520eb543e7913a773",
                        "filterValue": [start_date, end_date],
                        "displayValue": [start_date, end_date],
                    }
                ],
                "treeFilters": [],
                "dynamicParams": [],
                "dynamicFieldFilters": [],
                "combinationFilters": [],
                "layerTreeFilters": [],
            }
        ],
        "exportType": "PIVOT",
        "saveType": "MANY_SHEET",
    }

    assert cash.api == "/api/batchExportCardExcel"
    assert cash.payload == {
        "pgId": "u9325e10935054279894536e",
        "cards": [
            {
                "cdId": "l7c4c81c230394601874711e",
                "saveFilters": False,
                "filters": [
                    {
                        "name": "业务日期",
                        "fdId": "q9a11a0ad4aa541c5a528121",
                        "dsId": "of4905b0c643e4df8881f8e1",
                        "cdId": "l7c4c81c230394601874711e",
                        "fdType": "DATE",
                        "filterType": "BT",
                        "sourceCdId": "e26aad5d30d4d4cd1b0b200d",
                        "filterValue": [start_date, end_date],
                        "displayValue": [start_date, end_date],
                    }
                ],
                "treeFilters": [],
                "dynamicParams": [],
                "dynamicFieldFilters": [],
                "combinationFilters": [],
                "layerTreeFilters": [],
            }
        ],
        "exportType": "NORMAL",
        "saveType": "MANY_SHEET",
    }


def test_auth_session_stays_under_its_workspace(tmp_path: Path) -> None:
    paths = AuthSessionPaths(tmp_path, "bi")
    write_auth_session("bi", cookies=[{"name": "sid", "value": "test"}], local_storage={"token": "test"}, paths=paths)

    assert paths.cookies.is_file()
    assert paths.local_storage.is_file()
    assert paths.cookies.stat().st_mode & 0o777 == 0o600
