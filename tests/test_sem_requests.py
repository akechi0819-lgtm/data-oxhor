import json
import stat
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from openpyxl import Workbook
import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from data_acquisition.connectors.advertising import native_exports as exports
from data_acquisition.connectors.advertising import sem_requests as sem


TITLE = "汇报202610SEM"
START = "2026-10-01"
THROUGH = "2026-10-31"
SHEETS = ["SEM总计", "2665", "bing"]
JOB_ID = "32566313513"
OSS_URL = "https://alidocs-body.oss-cn-zhangjiakou.aliyuncs.com/signed-private-query"
PAYLOAD = "RAW_SERIALIZED_PAYLOAD_SECRET"


def _xlsx(sheet_names=SHEETS):
    book = Workbook(write_only=True)
    for name in sheet_names:
        book.create_sheet(name)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


class _Response:
    status = 200
    ok = True

    def __init__(self, body):
        self._body = body

    def body(self):
        return self._body


class _Request:
    def __init__(self, body=None, error=None):
        self._body = body
        self._error = error
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append((url, kwargs))
        if self._error:
            raise self._error
        return _Response(self._body)


class _Page:
    def __init__(self, body=None, download_error=None):
        self.url = sem.ORIGIN + "/i/nodes/" + sem.DOCUMENT
        self.context = SimpleNamespace(request=_Request(body, download_error))

    def locator(self, _selector):
        return SimpleNamespace(inner_text=lambda **_kwargs: "")

    def wait_for_timeout(self, _milliseconds):
        pass


def _new_actions(*, guard=None, upload=None, submit=None, query=None):
    return {
        "prepare": {"title": TITLE, "payload": PAYLOAD, "checkpoint_version": 1},
        "guard": guard or {"isSuccess": True, "isBlocked": False},
        "upload": upload or {"isSuccess": True, "storagePath": "tmp_cp/document/resource-1", "upload_status": 200},
        "submit": submit or {"isSuccess": True, "jobId": JOB_ID, "status": "init"},
        "query": query or {
            "isSuccess": True,
            "jobId": JOB_ID,
            "status": "success",
            "ossUrl": OSS_URL,
        },
    }


def _run(page, destination, actions, *, timeout_sec=1, phase_callback=None, submission_callback=None):
    calls = []

    def evaluate(_page, action, _payload=None):
        calls.append(action)
        value = actions[action]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    with mock.patch.object(sem, "_evaluate", side_effect=evaluate):
        result = sem.download_sem_requests(
            page,
            destination=destination,
            workbook_title=TITLE,
            expected_sheets=SHEETS,
            start_date=START,
            through_date=THROUGH,
            timeout_sec=timeout_sec,
            phase_callback=phase_callback,
            submission_callback=submission_callback,
        )
    return result, calls


def _complete_download(tmp_path):
    destination = tmp_path / "native.xlsx"
    page = _Page(_xlsx())
    result, calls = _run(page, destination, _new_actions())
    return destination, page, result, calls


def test_evaluate_waits_for_frontend_runtime_after_iframe_body_exists():
    waits = []
    requests = []

    class Body:
        def wait_for_function(self, expression, *, timeout):
            waits.append((expression, timeout))

        def evaluate(self, expression, _arg=None):
            assert expression == sem._REQUEST
            requests.append(expression)
            return {"isSuccess": True}

    class Frame:
        def locator(self, selector):
            assert selector == "body"
            return Body()

    class Page:
        def frame_locator(self, selector):
            assert selector == "#wiki-new-sheet-iframe"
            return Frame()

    assert sem._evaluate(Page(), "guard", {"document": sem.DOCUMENT}) == {"isSuccess": True}
    assert waits == [(sem._FRONTEND_READY, 30000)]
    assert len(requests) == 1
    assert "Array.isArray(w.webpackChunkflex_table_app)" in sem._FRONTEND_READY
    assert "w.webpackChunkflex_table_app.push !== w.Array.prototype.push" in sem._FRONTEND_READY


def test_evaluate_blocks_request_when_frontend_runtime_does_not_become_ready():
    waits = []
    requests = []

    class Body:
        def wait_for_function(self, expression, *, timeout):
            waits.append((expression, timeout))
            raise PlaywrightTimeoutError("Timeout 30000ms exceeded")

        def evaluate(self, expression, _arg=None):
            requests.append(expression)
            return {"isSuccess": True}

    class Frame:
        def locator(self, selector):
            assert selector == "body"
            return Body()

    class Page:
        def frame_locator(self, selector):
            assert selector == "#wiki-new-sheet-iframe"
            return Frame()

    with pytest.raises(exports.ExportError, match="sem_frontend_contract_changed"):
        sem._evaluate(Page(), "guard", {"document": sem.DOCUMENT})

    assert waits == [(sem._FRONTEND_READY, 30000)]
    assert requests == []


def test_evaluate_preserves_non_timeout_readiness_errors():
    failure = PlaywrightError("Execution context was destroyed")

    class Body:
        def wait_for_function(self, _expression, *, timeout):
            assert timeout == 30000
            raise failure

    class Frame:
        def locator(self, _selector):
            return Body()

    class Page:
        def frame_locator(self, _selector):
            return Frame()

    with pytest.raises(PlaywrightError, match="Execution context was destroyed") as caught:
        sem._evaluate(Page(), "guard", {"document": sem.DOCUMENT})
    assert caught.value is failure


def test_non_callable_frontend_require_is_reported_as_contract_change():
    class Body:
        def wait_for_function(self, expression, *, timeout):
            assert expression == sem._FRONTEND_READY
            assert timeout == 30000

        def evaluate(self, expression, _arg=None):
            assert expression == sem._REQUEST
            return {"__sem_error": True, "code": "sem_frontend_contract_changed"}

    class Frame:
        def locator(self, _selector):
            return Body()

    class Page:
        def frame_locator(self, _selector):
            return Frame()

    assert "typeof req !== 'function'" in sem._REQUEST
    with pytest.raises(exports.ExportError, match="sem_frontend_contract_changed"):
        sem._evaluate(Page(), "guard", {"document": sem.DOCUMENT})


def test_happy_path_submits_once_validates_native_file_and_writes_safe_state(tmp_path):
    destination = tmp_path / "native.xlsx"
    phases, submissions = [], []
    page = _Page(_xlsx())

    result, calls = _run(
        page,
        destination,
        _new_actions(),
        phase_callback=phases.append,
        submission_callback=submissions.append,
    )

    assert result["status"] == "success"
    assert result["task_id"] == JOB_ID
    assert result["account_ids"] == SHEETS
    assert result["completion"] == {"complete": False, "through_date": None, "basis": "download_only"}
    assert calls.count("submit") == 1
    assert calls[:4] == ["guard", "prepare", "upload", "submit"]
    assert "query" in calls
    assert all("menu" not in action and "click" not in action for action in calls)
    assert "export_request_pending" in phases
    assert submissions == [{
        "kind": "submit",
        "http_status": None,
        "task_id": JOB_ID,
        "response_body_status": "parsed",
    }]
    assert page.context.request.urls == [(OSS_URL, {"timeout": 120000, "max_redirects": 0})]

    state_path = destination.with_suffix(".request-state.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    evidence_path = destination.with_suffix(".evidence.json")
    evidence_text = evidence_path.read_text(encoding="utf-8")
    assert state["state"] == "downloaded"
    assert state["job_id"] == JOB_ID
    assert len(state["snapshot_sha256"]) == 64
    assert state["snapshot_bytes"] == len(PAYLOAD.encode("utf-8"))
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    for private_value in (PAYLOAD, OSS_URL, "tmp_cp/document/resource-1"):
        assert private_value not in state_path.read_text(encoding="utf-8")
        assert private_value not in evidence_text


def test_known_job_resume_queries_and_downloads_without_new_submission(tmp_path):
    destination, _page, _result, _first_calls = _complete_download(tmp_path)
    state_path = destination.with_suffix(".request-state.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["state"] = "task_submitted"
    destination.unlink()
    destination.with_suffix(".evidence.json").unlink()
    state_path.write_text(json.dumps(state), encoding="utf-8")

    page = _Page(_xlsx())
    result, calls = _run(page, destination, {"query": _new_actions()["query"]})

    assert result["task_id"] == JOB_ID
    assert calls == ["query"]
    assert page.context.request.urls == [(OSS_URL, {"timeout": 120000, "max_redirects": 0})]


def test_submit_outcome_unknown_is_durable_and_blocks_blind_resubmission(tmp_path):
    destination = tmp_path / "native.xlsx"
    actions = _new_actions(submit=RuntimeError("private signed URL must not escape"))
    page = _Page(_xlsx())
    calls = []

    def evaluate(_page, action, _payload=None):
        calls.append(action)
        value = actions[action]
        if isinstance(value, BaseException):
            raise value
        return value

    with mock.patch.object(sem, "_evaluate", side_effect=evaluate):
        with pytest.raises(exports.ExportPending, match="sem_export_submission_outcome_unknown") as error:
            sem.download_sem_requests(
                page, destination=destination, workbook_title=TITLE, expected_sheets=SHEETS,
                start_date=START, through_date=THROUGH)
    assert "private signed URL" not in str(error.value)
    assert calls.count("submit") == 1
    state_path = destination.with_suffix(".request-state.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["state"] == "submission_outcome_unknown"
    assert not state.get("job_id")

    with mock.patch.object(sem, "_evaluate") as evaluate_again:
        with pytest.raises(exports.ExportPending, match="sem_export_submission_outcome_unknown"):
            sem.download_sem_requests(
                page, destination=destination, workbook_title=TITLE, expected_sheets=SHEETS,
                start_date=START, through_date=THROUGH)
    evaluate_again.assert_not_called()


def test_unknown_state_with_known_job_only_queries(tmp_path):
    destination, _page, _result, _calls = _complete_download(tmp_path)
    state_path = destination.with_suffix(".request-state.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["state"] = "submission_outcome_unknown"
    destination.unlink()
    destination.with_suffix(".evidence.json").unlink()
    state_path.write_text(json.dumps(state), encoding="utf-8")

    page = _Page(_xlsx())
    _result, calls = _run(page, destination, {"query": _new_actions()["query"]})
    assert calls == ["query"]


def test_permission_denial_does_not_submit_or_report_success(tmp_path):
    destination = tmp_path / "native.xlsx"
    page = _Page(_xlsx())

    with mock.patch.object(sem, "_evaluate", side_effect=lambda _page, action, _payload=None: {
        "prepare": {"title": TITLE, "payload": PAYLOAD, "checkpoint_version": 1},
        "guard": {"isSuccess": True, "isBlocked": True},
    }[action]) as evaluate:
        with pytest.raises(exports.ExportError):
            sem.download_sem_requests(
                page, destination=destination, workbook_title=TITLE, expected_sheets=SHEETS,
                start_date=START, through_date=THROUGH)

    assert [call.args[1] for call in evaluate.call_args_list] == ["guard"]
    assert not destination.exists()
    assert json.loads(destination.with_suffix(".request-state.json").read_text())["state"] == "pre_submit"


def test_missing_prepare_schema_fails_before_upload_or_submission(tmp_path):
    destination = tmp_path / "native.xlsx"
    page = _Page(_xlsx())
    calls = []

    def evaluate(_page, action, _payload=None):
        calls.append(action)
        return {"isSuccess": True, "isBlocked": False} if action == "guard" else {"title": TITLE, "checkpoint_version": 1}

    with mock.patch.object(sem, "_evaluate", side_effect=evaluate):
        with pytest.raises(exports.ExportError):
            sem.download_sem_requests(
                page, destination=destination, workbook_title=TITLE, expected_sheets=SHEETS,
                start_date=START, through_date=THROUGH)

    assert calls == ["guard", "prepare"]
    assert not destination.exists()


def test_download_failure_keeps_known_job_for_resume(tmp_path):
    destination, _page, _result, _calls = _complete_download(tmp_path)
    state_path = destination.with_suffix(".request-state.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["state"] = "task_submitted"
    destination.unlink()
    destination.with_suffix(".evidence.json").unlink()
    state_path.write_text(json.dumps(state), encoding="utf-8")

    page = _Page(download_error=RuntimeError("private OSS URL"))
    with mock.patch.object(sem, "_evaluate", return_value=_new_actions()["query"]) as evaluate:
        with pytest.raises(exports.ExportPending) as error:
            sem.download_sem_requests(
                page, destination=destination, workbook_title=TITLE, expected_sheets=SHEETS,
                start_date=START, through_date=THROUGH)

    assert "private OSS URL" not in str(error.value)
    assert [call.args[1] for call in evaluate.call_args_list] == ["query"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["state"] == "task_submitted"
    assert state["job_id"] == JOB_ID
    assert not destination.exists()


def test_downloaded_file_is_hash_reused_without_browser_or_network(tmp_path):
    destination, _page, first, _calls = _complete_download(tmp_path)
    with mock.patch.object(sem, "_evaluate") as evaluate:
        result = sem.download_sem_requests(
            _Page(), destination=destination, workbook_title=TITLE, expected_sheets=SHEETS,
            start_date=START, through_date=THROUGH)
    evaluate.assert_not_called()
    assert result["files"][0]["sha256"] == first["files"][0]["sha256"]


def test_native_workbook_missing_expected_sheet_is_rejected(tmp_path):
    destination = tmp_path / "native.xlsx"
    page = _Page(_xlsx(["SEM总计", "2665"]))

    with mock.patch.object(sem, "_evaluate", side_effect=lambda _page, action, _payload=None: _new_actions()[action]):
        with pytest.raises(exports.ExportError, match="sem_whole_workbook_missing_sheets"):
            sem.download_sem_requests(
                page, destination=destination, workbook_title=TITLE, expected_sheets=SHEETS,
                start_date=START, through_date=THROUGH)

    assert destination.with_suffix(".request-state.json").exists()
    state = json.loads(destination.with_suffix(".request-state.json").read_text(encoding="utf-8"))
    assert state["state"] == "task_submitted"
    assert state["job_id"] == JOB_ID
