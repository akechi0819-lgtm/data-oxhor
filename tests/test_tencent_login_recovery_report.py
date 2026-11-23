import json
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path
from unittest.mock import Mock

import pytest

from data_acquisition.connectors.advertising import tencent_requests as tencent
from data_acquisition.connectors.advertising import xhs_requests as xhs
from data_acquisition.auth.auth_sessions import AuthSessionMissingError
from data_acquisition.auth.auth_sessions import AuthSessionPaths
from data_acquisition.jobs import prepare_full_daily


class _Response:
    def __init__(self, value):
        self.raw = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self.raw


@pytest.mark.parametrize(
    "value, expected_type",
    [
        ({"code": 4501, "ret": 4501, "message": "login prompt SECRET"}, tencent.TencentLoginRequired),
        ({"code": 4502, "ret": 4502, "message": "other response SECRET"}, tencent.ExportBlocked),
    ],
)
def test_post_only_classifies_exact_observed_4501(value, expected_type, tmp_path, monkeypatch):
    auth = {
        "account_id": "74749810",
        "queries": {"display_plus": {"path": tencent.QUERY, "query": {}, "headers": {}}},
    }
    monkeypatch.setattr(tencent, "private_json", lambda _path: auth)
    monkeypatch.setattr(tencent, "build_opener", lambda *args, **kwargs: Mock(open=Mock(return_value=_Response(value))))
    client = tencent.TencentExport(tmp_path)
    client.scope = "display_plus"
    client._cookie = lambda _path: "fixture"

    with pytest.raises(expected_type) as caught:
        client._post("query", {})

    assert "SECRET" not in str(caught.value)
    if value["code"] == 4501:
        assert caught.value.error_code == 4501
        assert str(caught.value) == "tencent_login_required"
    else:
        assert type(caught.value) is tencent.ExportBlocked
        assert str(caught.value) == "tencent_api_rejected"
        assert not hasattr(caught.value, "error_code")


@pytest.mark.parametrize(
    "value, expected",
    [
        ({"code": 0}, True),
        ({"code": 0, "ret": 0}, True),
        ({"code": 0, "ret": 4501}, False),
        ({"code": 4501, "ret": 4501}, False),
    ],
)
def test_normal_query_capture_requires_success_ret_when_present(value, expected):
    assert tencent._normal_query_succeeded(value) is expected


def test_login_capture_requires_success_from_both_query_scopes():
    display = [(tencent.QUERY_PATHS["display_plus"], {"g-tk": "fresh"}, {})]
    assert tencent._required_login_scopes_captured(display) is False
    both = display + [(tencent.QUERY_PATHS["legacy_search"], {"mp-tk": "fresh"}, {})]
    assert tencent._required_login_scopes_captured(both) is True


class _VisibleLocator:
    def __init__(self, label, visible, actions):
        self.label = label
        self.visible = visible
        self.actions = actions

    def is_visible(self):
        return self.visible()

    def click(self):
        self.actions.append(self.label)


class _LocatorGroup:
    def __init__(self, locators):
        self.locators = locators

    def all(self):
        return self.locators


class _NavigationPage:
    def __init__(self):
        self.actions = []

    def get_by_text(self, text, exact):
        assert exact is True
        if text == "竞价-展示投放":
            return _LocatorGroup([_VisibleLocator(text, lambda: True, self.actions)])
        if text == "搜索投放":
            return _LocatorGroup([_VisibleLocator(text, lambda: bool(self.actions), self.actions)])
        return _LocatorGroup([])

    def wait_for_timeout(self, _milliseconds):
        return None


class _QueryResponse:
    def json(self):
        return {"code": 0, "ret": 0}


class _CapturedQuery:
    def __init__(self, path, headers, query):
        self.url = tencent.ORIGIN + path + "?" + "&".join(
            f"{key}={value}" for key, value in query.items()
        )
        self.post_data = json.dumps({"account_id_list": [74749810]})
        self.headers = headers

    def response(self):
        return _QueryResponse()

    def all_headers(self):
        return self.headers


class _LoginPage:
    def __init__(self):
        self.handlers = {}
        self.reload_called = False
        self.on_goto = None
        self.on_reload = None

    def on(self, event, callback):
        self.handlers[event] = callback

    def emit(self, request):
        self.handlers["requestfinished"](request)

    def goto(self, _url, **_kwargs):
        if self.on_goto is not None:
            self.on_goto()

    def wait_for_function(self, *_args, **_kwargs):
        return None

    def reload(self, **_kwargs):
        self.reload_called = True
        if self.on_reload is not None:
            self.on_reload()

    def evaluate(self, _script):
        return {"verified_session": "fresh"}

    def wait_for_timeout(self, _milliseconds):
        return None


class _LoginContext:
    def __init__(self, page):
        self.page = page
        self.injected_cookies = []
        self.init_scripts = []

    def new_page(self):
        return self.page

    def cookies(self, _origins):
        return [{"name": "session", "value": "fresh", "domain": "ad.qq.com"}]

    def add_cookies(self, _cookies):
        self.injected_cookies.append(_cookies)

    def add_init_script(self, _script):
        self.init_scripts.append(_script)


class _LoginBrowser:
    def __init__(self, context):
        self.context = context
        self.closed = False

    def new_context(self, **_kwargs):
        return self.context

    def close(self):
        self.closed = True


def _install_fake_playwright(monkeypatch, browser):
    playwright = ModuleType("playwright")
    playwright.__path__ = []
    sync_api = ModuleType("playwright.sync_api")

    class _PlaywrightContext:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(
                launch=lambda **_kwargs: browser,
            ))

        def __exit__(self, *_args):
            return False

    sync_api.sync_playwright = _PlaywrightContext
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


def _export_auth_fixture(workspace):
    paths = AuthSessionPaths(workspace, "tencent_ads")
    paths.root.mkdir(parents=True)
    auth = {
        "account_id": "74749810",
        "create": {"path": tencent.CREATE, "headers": {"mp-tk": "old"},
                   "query": {"mp_tk": "old", "g_tk": "old"}},
        "poll": {"path": tencent.POLL, "headers": {"mp-tk": "old"},
                 "query": {"mp_tk": "old"}},
        "list": {"path": tencent.TASKS, "headers": {}, "query": {"mp_tk": "old"}},
        "download": {"path": tencent.DOWNLOAD, "headers": {}, "query": {"mp_tk": "old"}},
        "queries": {
            "display_plus": {"path": tencent.QUERY, "headers": {"g-tk": "old"},
                             "query": {"g_tk": "old"}},
            "legacy_search": {"path": tencent.LEGACY_QUERY,
                              "headers": {"mp-tk": "old"},
                              "query": {"mp_tk": "old"}},
        },
    }
    auth_path = paths.root / "export-auth.json"
    auth_path.write_text(json.dumps(auth))
    auth_path.chmod(0o600)
    return paths, auth_path, auth_path.read_bytes()


def test_save_login_keeps_successful_display_query_and_persists_same_context(
        tmp_path, monkeypatch):
    paths, auth_path, _original_auth = _export_auth_fixture(tmp_path)
    page = _LoginPage()
    browser = _LoginBrowser(_LoginContext(page))
    page.on_goto = lambda: page.emit(_CapturedQuery(
        tencent.QUERY, {"g-tk": "fresh-g"}, {"g_tk": "fresh-g"},
    ))
    page.on_reload = lambda: None
    monkeypatch.setattr(tencent, "_open_legacy_search", lambda current: current.emit(
        _CapturedQuery(tencent.LEGACY_QUERY, {"mp-tk": "fresh-mp"},
                       {"mp_tk": "fresh-mp"}),
    ))
    _install_fake_playwright(monkeypatch, browser)

    tencent.save_login(tmp_path)

    assert page.reload_called is False
    assert json.loads(paths.cookies.read_text())[0]["value"] == "fresh"
    assert json.loads(paths.local_storage.read_text()) == {"verified_session": "fresh"}
    updated_auth = json.loads(auth_path.read_text())
    assert updated_auth["queries"]["display_plus"]["query"]["g_tk"] == "fresh-g"
    assert updated_auth["queries"]["legacy_search"]["query"]["mp_tk"] == "fresh-mp"
    assert browser.closed is True


def test_save_login_keeps_verified_session_when_report_query_is_not_verified(
        tmp_path, monkeypatch):
    paths, auth_path, original_auth = _export_auth_fixture(tmp_path)
    page = _LoginPage()
    browser = _LoginBrowser(_LoginContext(page))
    monkeypatch.setattr(tencent, "_wait_for_query_scope", lambda *_args, **_kwargs: False)
    _install_fake_playwright(monkeypatch, browser)

    with pytest.raises(tencent.TencentLoginRecoveryUnverified,
                       match="tencent_display_query_not_verified_session_saved"):
        tencent.save_login(tmp_path)

    assert json.loads(paths.cookies.read_text())[0]["value"] == "fresh"
    assert json.loads(paths.local_storage.read_text()) == {"verified_session": "fresh"}
    assert auth_path.read_bytes() == original_auth
    assert browser.closed is True


def test_save_login_does_not_persist_session_before_account_verification(
        tmp_path, monkeypatch):
    paths, auth_path, original_auth = _export_auth_fixture(tmp_path)
    page = _LoginPage()
    page.wait_for_function = Mock(side_effect=TimeoutError("account not verified"))
    browser = _LoginBrowser(_LoginContext(page))
    _install_fake_playwright(monkeypatch, browser)

    with pytest.raises(TimeoutError, match="account not verified"):
        tencent.save_login(tmp_path)

    assert not paths.cookies.exists()
    assert not paths.local_storage.exists()
    assert auth_path.read_bytes() == original_auth
    assert browser.closed is True


def test_save_login_can_start_fresh_without_injecting_saved_cookies(
        tmp_path, monkeypatch):
    paths, _auth_path, _original_auth = _export_auth_fixture(tmp_path)
    from data_acquisition.auth.auth_sessions import write_auth_session
    write_auth_session("tencent_ads", cookies=[{"name": "old", "value": "old"}],
                       local_storage={"old": "old"}, paths=paths)
    page = _LoginPage()
    browser_context = _LoginContext(page)
    browser = _LoginBrowser(browser_context)
    page.on_goto = lambda: page.emit(_CapturedQuery(
        tencent.QUERY, {"g-tk": "fresh-g"}, {"g_tk": "fresh-g"},
    ))
    monkeypatch.setattr(tencent, "_open_legacy_search", lambda current: current.emit(
        _CapturedQuery(tencent.LEGACY_QUERY, {"mp-tk": "fresh-mp"},
                       {"mp_tk": "fresh-mp"}),
    ))
    _install_fake_playwright(monkeypatch, browser)

    tencent.save_login(tmp_path, inject_saved_state=False)

    assert browser_context.injected_cookies == []
    assert browser_context.init_scripts == []
    assert json.loads(paths.cookies.read_text())[0]["value"] == "fresh"


def test_high_school_login_uses_independent_saved_state(tmp_path, monkeypatch):
    from data_acquisition.auth.auth_sessions import write_auth_session
    from data_acquisition.connectors.advertising import tencent_high_school_login

    abroad = AuthSessionPaths(tmp_path, "tencent_ads")
    high_school = AuthSessionPaths(tmp_path, "tencent_ads_94274565")
    write_auth_session("tencent_ads", cookies=[{"name": "abroad", "value": "old"}],
                       local_storage={"abroad": "old"}, paths=abroad)
    write_auth_session("tencent_ads_94274565", cookies=[{"name": "school", "value": "old"}],
                       local_storage={"school": "old"}, paths=high_school)
    original_abroad = (abroad.cookies.read_bytes(), abroad.local_storage.read_bytes())
    page = _LoginPage()
    page.goto = Mock()
    page.wait_for_function = Mock()
    context = _LoginContext(page)
    browser = _LoginBrowser(context)
    _install_fake_playwright(monkeypatch, browser)

    tencent_high_school_login.save_login(tmp_path)

    assert context.injected_cookies == [[{"name": "school", "value": "old"}]]
    assert '"school": "old"' in context.init_scripts[0]
    assert '94274565' in page.goto.call_args.args[0]
    assert 'ID:94274565' in page.wait_for_function.call_args.args[0]
    assert json.loads(high_school.cookies.read_text())[0]["value"] == "fresh"
    assert (abroad.cookies.read_bytes(), abroad.local_storage.read_bytes()) == original_abroad
    assert browser.closed is True


def test_high_school_login_does_not_save_unverified_account(tmp_path, monkeypatch):
    from data_acquisition.connectors.advertising import tencent_high_school_login

    page = _LoginPage()
    page.wait_for_function = Mock(side_effect=TimeoutError("account not verified"))
    browser = _LoginBrowser(_LoginContext(page))
    _install_fake_playwright(monkeypatch, browser)

    with pytest.raises(TimeoutError, match="account not verified"):
        tencent_high_school_login.save_login(tmp_path)

    paths = AuthSessionPaths(tmp_path, "tencent_ads_94274565")
    assert not paths.cookies.exists()
    assert browser.closed is True


def test_training_login_uses_independent_saved_state(tmp_path, monkeypatch):
    from data_acquisition.auth.auth_sessions import write_auth_session
    from data_acquisition.connectors.advertising import tencent_training_login

    others = [AuthSessionPaths(tmp_path, service) for service in
              ("tencent_ads", "tencent_ads_94274565")]
    for paths in others:
        write_auth_session(paths.service, cookies=[{"name": paths.service, "value": "old"}],
                           local_storage={paths.service: "old"}, paths=paths)
    original = [(paths.cookies.read_bytes(), paths.local_storage.read_bytes()) for paths in others]
    training = AuthSessionPaths(tmp_path, "tencent_ads_73047077")
    write_auth_session(training.service, cookies=[{"name": "training", "value": "old"}],
                       local_storage={"training": "old"}, paths=training)
    page = _LoginPage()
    page.goto = Mock()
    page.wait_for_function = Mock()
    context = _LoginContext(page)
    browser = _LoginBrowser(context)
    _install_fake_playwright(monkeypatch, browser)

    tencent_training_login.save_login(tmp_path)

    assert context.injected_cookies == [[{"name": "training", "value": "old"}]]
    assert '"training": "old"' in context.init_scripts[0]
    assert '73047077' in page.goto.call_args.args[0]
    assert 'ID:73047077' in page.wait_for_function.call_args.args[0]
    assert json.loads(training.cookies.read_text())[0]["value"] == "fresh"
    assert [(paths.cookies.read_bytes(), paths.local_storage.read_bytes()) for paths in others] == original
    assert browser.closed is True


def test_training_login_does_not_save_unverified_account(tmp_path, monkeypatch):
    from data_acquisition.connectors.advertising import tencent_training_login

    page = _LoginPage()
    page.wait_for_function = Mock(side_effect=TimeoutError("account not verified"))
    browser = _LoginBrowser(_LoginContext(page))
    _install_fake_playwright(monkeypatch, browser)

    with pytest.raises(TimeoutError, match="account not verified"):
        tencent_training_login.save_login(tmp_path)

    assert not AuthSessionPaths(tmp_path, "tencent_ads_73047077").cookies.exists()
    assert browser.closed is True


def test_login_opens_the_observed_legacy_search_navigation():
    page = _NavigationPage()

    tencent._open_legacy_search(page)

    assert page.actions == ["竞价-展示投放", "搜索投放"]


def test_wait_for_login_capture_requires_a_new_matching_scope_request():
    captured = [(tencent.QUERY_PATHS["legacy_search"], {}, {})]

    class _Page:
        def wait_for_timeout(self, _milliseconds):
            captured.append((tencent.QUERY_PATHS["legacy_search"], {}, {}))

    assert tencent._wait_for_query_scope(
        _Page(), captured, "legacy_search", after=1, timeout_seconds=0.01
    ) is True
    assert tencent._wait_for_query_scope(
        _Page(), captured[:1], "display_plus", timeout_seconds=0
    ) is False


def test_refresh_uses_observed_url_parameter_for_existing_header_and_query_fields():
    auth = {
        "create": {"path": tencent.CREATE, "headers": {"mp-tk": "old"}, "query": {"mp_tk": "old", "g_tk": "old"}},
        "poll": {"path": tencent.POLL, "headers": {"mp-tk": "old", "g-tk": "old"}, "query": {}},
        "list": {"path": tencent.TASKS, "headers": {}, "query": {"mp_tk": "old"}},
        "download": {"path": tencent.DOWNLOAD, "headers": {}, "query": {"mp_tk": "old"}},
        "queries": {
            "display_plus": {"path": tencent.QUERY, "headers": {}, "query": {"g_tk": "old"}},
            "legacy_search": {"path": tencent.LEGACY_QUERY, "headers": {"mp-tk": "old"}, "query": {"mp_tk": "old"}},
        },
    }

    query = tencent._auth_query_values("https://ad.qq.com/api/test?mp_tk=fresh-mp&ignored=not-captured")
    tencent._refresh_export_auth(auth, [(tencent.LEGACY_QUERY, {"g-tk": "fresh-g"}, query)])

    assert auth["create"]["headers"]["mp-tk"] == "old"
    assert auth["create"]["query"] == {"mp_tk": "old", "g_tk": "fresh-g"}
    assert auth["poll"]["headers"] == {"mp-tk": "old", "g-tk": "fresh-g"}
    assert auth["list"]["query"]["mp_tk"] == "old"
    assert auth["download"]["query"]["mp_tk"] == "old"
    assert auth["queries"]["legacy_search"]["headers"]["mp-tk"] == "fresh-mp"
    assert auth["queries"]["legacy_search"]["query"]["mp_tk"] == "fresh-mp"
    assert auth["queries"]["display_plus"]["query"]["g_tk"] == "fresh-g"


def test_refresh_rejects_conflicting_observed_header_and_url_values():
    auth = {"create": {"path": tencent.CREATE, "headers": {"mp-tk": "old"}, "query": {"mp_tk": "old"}},
            "poll": {"path": tencent.POLL, "headers": {}, "query": {}},
            "list": {"path": tencent.TASKS, "headers": {}, "query": {}},
            "download": {"path": tencent.DOWNLOAD, "headers": {}, "query": {}},
            "queries": {"legacy_search": {"path": tencent.LEGACY_QUERY, "headers": {"mp-tk": "old"}, "query": {"mp_tk": "old"}}}}
    with pytest.raises(tencent.ExportBlocked, match="tencent_auth_refresh_ambiguous"):
        tencent._refresh_export_auth(auth, [(tencent.LEGACY_QUERY, {"mp-tk": "header-value"}, {"mp_tk": ["url-value"]})])
    assert auth["queries"]["legacy_search"]["headers"]["mp-tk"] == "old"


def test_refresh_does_not_require_or_copy_legacy_mp_token_for_display_query():
    auth = {
        "create": {"path": tencent.CREATE, "headers": {"mp-tk": "old"}, "query": {"mp_tk": "old"}},
        "poll": {"path": tencent.POLL, "headers": {"mp-tk": "old"}, "query": {}},
        "list": {"path": tencent.TASKS, "headers": {"mp-tk": "old"}, "query": {"mp_tk": "old"}},
        "download": {"path": tencent.DOWNLOAD, "headers": {}, "query": {"mp_tk": "old"}},
        "queries": {
            "display_plus": {"path": tencent.QUERY, "headers": {}, "query": {"nonce": "n", "timestamp": "t"}},
            "legacy_search": {"path": tencent.LEGACY_QUERY, "headers": {"mp-tk": "old"}, "query": {"mp_tk": "old"}},
        },
    }

    tencent._refresh_export_auth(auth, [(tencent.QUERY, {"g-tk": "fresh-g"}, {})])

    assert auth["queries"]["legacy_search"]["headers"]["mp-tk"] == "old"
    assert auth["queries"]["legacy_search"]["query"]["mp_tk"] == "old"
    assert auth["queries"]["display_plus"]["query"] == {"nonce": "n", "timestamp": "t"}


def test_collector_persists_only_fixed_4501_recovery_details(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    (workspace / ".private").mkdir(parents=True)
    (workspace / ".private/full-daily-sources.json").write_text(json.dumps({
        "expected_sources": {
            "xhs": {"start_date": "2026-10-01"},
            "ocean": {"start_date": "2026-10-01"},
            "tencent_ads_abroad": {"start_date": "2026-10-01"},
            "sem": {"start_date": "2026-10-01"},
        }
    }))
    batch = tmp_path / "batch"
    xhs_contracts = tmp_path / "contracts" / "xhs-network-sample"
    xhs_contracts.mkdir(parents=True)
    (xhs_contracts / "network-contract.json").write_text("{}")
    xhs_scope = tmp_path / "xhs-scope.json"
    xhs_scope.write_text("{}")
    contracts = tmp_path / "contracts" / "tencent-network-sample"
    contracts.mkdir(parents=True)
    (contracts / "legacy-network-contract.json").write_text("{}")
    (contracts / "dedicated-network-contract.json").write_text("{}")
    monkeypatch.setattr(prepare_full_daily, "_tencent_scope_confirmation", lambda _path=None: None)
    xhs_client = Mock()
    xhs_client.run.side_effect = [
        AuthSessionMissingError("missing"), RuntimeError("xhs detail SECRET"),
    ]
    xhs_login = Mock()
    monkeypatch.setattr(xhs, "save_login", xhs_login)
    monkeypatch.setattr(prepare_full_daily, "XHSExport", lambda **kwargs: xhs_client)
    monkeypatch.setattr(prepare_full_daily, "OceanExport", lambda *_args, **kwargs: Mock(run=Mock(side_effect=RuntimeError("ocean detail SECRET"))))

    outcomes = iter([
        tencent.TencentLoginRequired(),
        tencent.TencentLoginRequired(),
        tencent.ExportBlocked("untrusted response detail SECRET"),
    ])
    tencent_clients = []
    tencent_login = Mock()
    monkeypatch.setattr(tencent, "save_login", tencent_login)

    def make_tencent_client(_workspace):
        client = Mock()
        client.paths = Mock(repo_root=workspace)
        client.run.side_effect = lambda **_kw: (_ for _ in ()).throw(next(outcomes))
        tencent_clients.append(client)
        return client

    monkeypatch.setattr(prepare_full_daily, "TencentExport", make_tencent_client)
    collect = prepare_full_daily.collector(batch, tmp_path / "contracts", xhs_scope)

    with pytest.raises(prepare_full_daily.DailyBlocked):
        collect(workspace, "2026-10-30", "run-test", tmp_path / "capture")

    report_text = (batch / "collection-report.json").read_text()
    report = json.loads(report_text)
    assert report["sources"]["tencent_search"] == {
        "status": "blocked",
        "error_type": "TencentLoginRequired",
        "error_code": 4501,
        "recovery": "login_required",
        "message": "腾讯广告登录状态需要恢复",
    }
    assert report["sources"]["tencent_display"] == {
        "status": "blocked",
        "error_type": "ExportBlocked",
    }
    xhs_login.assert_called_once_with(workspace)
    assert xhs_client.run.call_count == 2
    assert xhs_client.run.call_args_list[0] == xhs_client.run.call_args_list[1]
    tencent_login.assert_called_once_with(workspace)
    assert [client.run.call_count for client in tencent_clients] == [2, 1]
    assert tencent_clients[0].run.call_args_list[0] == tencent_clients[0].run.call_args_list[1]
    assert "SECRET" not in report_text
    assert "4502" not in report_text
