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


def test_confirmed_failure_falls_back_once_and_cash_keeps_full_window(tmp_path: Path) -> None:
    from data_acquisition.connectors.bi.bi_downloads import ExportTask, OfficialExportFailed, run_bi_download

    class Client:
        def __init__(self):
            self.requests = []

        def trigger_export(self, request):
            self.requests.append(request)
            return ExportTask(request.target, str(len(self.requests)), 'export.xlsx')

        def poll_download(self, task, config):
            if task.task_id == '1':
                raise OfficialExportFailed(task, 'CANCELED')
            path = tmp_path / f'{task.task_id}.xlsx'
            path.write_bytes(b'validated fixture')
            return path

    client = Client()
    config = BIExportConfig(download_dir=tmp_path)
    artifacts = run_bi_download(config, client, start_date='2026-05-05', end_date='2026-11-05',
                               orders_fallback_start_date='2026-11-04', orders_fallback_end_date='2026-11-04')
    windows = [r.payload['cards'][0]['filters'][0]['filterValue'] for r in client.requests]
    assert windows == [['2026-05-05', '2026-11-05'], ['2026-11-04', '2026-11-04'], ['2026-05-05', '2026-11-05']]
    assert [(a.start_date, a.end_date, a.mode) for a in artifacts] == [
        ('2026-11-04', '2026-11-04', 'incremental'), ('2026-05-05', '2026-11-05', 'full')]
    assert run_bi_download(config, client, start_date='2026-05-05', end_date='2026-11-05',
                           orders_fallback_start_date='2026-11-04', orders_fallback_end_date='2026-11-04') == artifacts
    assert len(client.requests) == 3


def test_unknown_timeout_resumes_original_task_without_fallback(tmp_path: Path) -> None:
    import pytest
    from data_acquisition.connectors.bi.bi_downloads import ExportTask, run_bi_download

    class Client:
        def __init__(self):
            self.submissions = 0
            self.polls = []

        def trigger_export(self, request):
            self.submissions += 1
            return ExportTask(request.target, 'original', 'export.xlsx')

        def poll_download(self, task, config):
            self.polls.append(task.task_id)
            raise TimeoutError('unknown result')

    client = Client()
    for _ in range(2):
        with pytest.raises(TimeoutError):
            run_bi_download(BIExportConfig(download_dir=tmp_path), client, targets=('orders',),
                            start_date='2026-05-05', end_date='2026-11-05',
                            orders_fallback_start_date='2026-11-04', orders_fallback_end_date='2026-11-04')
    assert client.submissions == 1
    assert client.polls == ['original', 'original']


def test_cash_failure_preserves_downloaded_orders_and_reuses_them(tmp_path: Path) -> None:
    import pytest
    from data_acquisition.connectors.bi.bi_downloads import ExportTask, run_bi_download

    class Client:
        def __init__(self):
            self.submissions = []

        def trigger_export(self, request):
            self.submissions.append(request.target)
            return ExportTask(request.target, request.target, 'export.xlsx')

        def poll_download(self, task, config):
            if task.target == 'cash':
                raise TimeoutError('cash pending')
            path = tmp_path / 'orders.xlsx'
            path.write_bytes(b'orders')
            return path

    client = Client()
    for _ in range(2):
        with pytest.raises(TimeoutError):
            run_bi_download(BIExportConfig(download_dir=tmp_path), client, start_date='2026-05-05', end_date='2026-11-05')
    assert (tmp_path / 'orders.xlsx').read_bytes() == b'orders'
    assert client.submissions == ['orders', 'cash']


def test_official_history_requires_exact_task_and_failure_status() -> None:
    import pytest
    from data_acquisition.connectors.bi.bi_downloads import PlaywrightBIExportClient, ExportTask, OfficialExportFailed

    class Page:
        def __init__(self, rows):
            self.rows = rows

        def evaluate(self, _):
            return {'data': self.rows}

    client = PlaywrightBIExportClient()
    task = ExportTask('orders', 'one', 'export.xlsx')
    for rows in [[{'taskId': 'other', 'taskStatus': 'CANCELED'}], [{'taskId': 'one', 'taskStatus': 'RUNNING'}], []]:
        client._page = Page(rows)
        client.require_not_failed(task)
    client._page = Page([{'taskId': 'one', 'taskStatus': 'CANCELED'}])
    with pytest.raises(OfficialExportFailed):
        client.require_not_failed(task)
    client._page = Page([{'taskId': 'one', 'taskStatus': 'FINISHED'}])
    client.require_not_failed(task)
    with pytest.raises(OfficialExportFailed, match='INVALID_XLSX'):
        client.require_not_failed(task, invalid_workbook=True)


def test_finished_invalid_xlsx_uses_order_fallback_and_is_not_resubmitted(tmp_path: Path) -> None:
    import json
    import pytest
    from data_acquisition.connectors.bi.bi_downloads import ExportTask, OfficialExportFailed, run_bi_download

    class Client:
        def __init__(self):
            self.submissions = []

        def trigger_export(self, request):
            self.submissions.append(request)
            number = len(self.submissions)
            return ExportTask(request.target, str(number), f'export-{number}.xlsx')

        def poll_download(self, task, config):
            if task.task_id == '1':
                raise OfficialExportFailed(task, 'INVALID_XLSX')
            path = tmp_path / 'fallback.xlsx'
            path.write_bytes(b'captured fixture')
            return path

    config = BIExportConfig(download_dir=tmp_path)
    client = Client()
    artifacts = run_bi_download(config, client, targets=('orders',),
        start_date='2026-05-07', end_date='2026-11-07',
        orders_fallback_start_date='2026-11-06', orders_fallback_end_date='2026-11-06')
    state = json.loads((tmp_path / 'orders-2026-05-07-2026-11-07.task.json').read_text())
    assert state['status'] == 'INVALID_XLSX'
    assert [(a.start_date, a.end_date, a.mode) for a in artifacts] == [
        ('2026-11-06', '2026-11-06', 'incremental')]
    assert len(client.submissions) == 2

    # The terminal original receipt remains evidence and is never submitted again.
    assert run_bi_download(config, client, targets=('orders',),
        start_date='2026-05-07', end_date='2026-11-07',
        orders_fallback_start_date='2026-11-06', orders_fallback_end_date='2026-11-06') == artifacts
    assert len(client.submissions) == 2


def test_invalid_xlsx_waits_while_official_task_is_running(tmp_path: Path) -> None:
    import base64
    import io
    from unittest.mock import patch
    from openpyxl import Workbook
    from data_acquisition.connectors.bi.bi_downloads import PlaywrightBIExportClient, ExportTask

    workbook = Workbook()
    output = io.BytesIO()
    workbook.save(output)
    valid_b64 = base64.b64encode(output.getvalue()).decode('ascii')

    class Page:
        def __init__(self):
            self.downloads = 0
            self.history_checks = 0

        def evaluate(self, script, _payload=None):
            if 'task-offline/guandata/history' in script:
                self.history_checks += 1
                return {'data': [{'taskId': 'one', 'taskStatus': 'RUNNING'}]}
            self.downloads += 1
            return {'ok': True, 'isFile': True,
                    'b64': 'UEsDBgAAAAAA' if self.downloads == 1 else valid_b64}

    client = PlaywrightBIExportClient()
    client._page = Page()
    config = BIExportConfig(download_dir=tmp_path, export_timeout_sec=20)
    with patch('data_acquisition.connectors.bi.bi_downloads.time.sleep', return_value=None):
        path = client.poll_download(ExportTask('orders', 'one', 'export.xlsx'), config)
    assert path.is_file()
    assert client._page.downloads == 2
    assert client._page.history_checks == 1


def test_finished_invalid_cash_fails_without_order_fallback(tmp_path: Path) -> None:
    import json
    import pytest
    from data_acquisition.connectors.bi.bi_downloads import ExportTask, OfficialExportFailed, run_bi_download

    class Client:
        def trigger_export(self, request):
            assert request.target == 'cash'
            return ExportTask('cash', 'cash-task', 'cash.xlsx')

        def poll_download(self, task, config):
            raise OfficialExportFailed(task, 'INVALID_XLSX')

    config = BIExportConfig(download_dir=tmp_path)
    with pytest.raises(OfficialExportFailed, match='INVALID_XLSX'):
        run_bi_download(config, Client(), targets=('cash',),
                        start_date='2026-05-07', end_date='2026-11-07',
                        orders_fallback_start_date='2026-11-06', orders_fallback_end_date='2026-11-06')
    state = json.loads((tmp_path / 'cash-2026-05-07-2026-11-07.task.json').read_text())
    assert state['status'] == 'INVALID_XLSX'


def test_unknown_submission_blocks_before_opening_browser(tmp_path: Path) -> None:
    import pytest
    from unittest.mock import patch
    from data_acquisition.connectors.bi.bi_downloads import run_bi_download

    class UnknownClient:
        def trigger_export(self, request):
            raise TimeoutError('submission response lost')

    config = BIExportConfig(download_dir=tmp_path)
    with pytest.raises(TimeoutError):
        run_bi_download(config, UnknownClient(), targets=('cash',), start_date='2026-05-05', end_date='2026-11-05')
    # Orders have no receipt yet. The later cash receipt must still block before
    # opening any browser or submitting the preceding orders export.
    with patch('data_acquisition.connectors.bi.bi_downloads.PlaywrightBIExportClient') as browser:
        with pytest.raises(RuntimeError, match='submission result unknown'):
            run_bi_download(config, start_date='2026-05-05', end_date='2026-11-05')
        browser.assert_not_called()


def test_complete_downloads_reuse_without_browser_and_verify_sha(tmp_path: Path) -> None:
    import pytest
    from unittest.mock import patch
    from data_acquisition.connectors.bi.bi_downloads import ExportTask, run_bi_download

    class Client:
        def trigger_export(self, request):
            return ExportTask(request.target, request.target, 'export.xlsx')

        def poll_download(self, task, config):
            path = tmp_path / f'{task.target}.xlsx'
            path.write_bytes(task.target.encode())
            return path

    config = BIExportConfig(download_dir=tmp_path)
    original = run_bi_download(config, Client(), start_date='2026-05-05', end_date='2026-11-05')
    with patch('data_acquisition.connectors.bi.bi_downloads.PlaywrightBIExportClient') as browser:
        assert run_bi_download(config, start_date='2026-05-05', end_date='2026-11-05') == original
        browser.assert_not_called()
        original[1].path.write_bytes(b'changed')
        with pytest.raises(ValueError, match='SHA mismatch'):
            run_bi_download(config, start_date='2026-05-05', end_date='2026-11-05')
        browser.assert_not_called()
