"""The shared native calculation must never select the retired page output area."""
import json
from types import SimpleNamespace
import pytest
from dashboard_product.management import calculation


def test_native_output_identity_is_selected_before_any_query(tmp_path, monkeypatch):
    work = tmp_path/'Work'; work.mkdir()
    (work/'workspace.json').write_text(json.dumps({'current_snapshot_id': 'snapshot_fixture'}))
    args = SimpleNamespace(workspace=tmp_path, snapshot_id='snapshot_fixture',
                           run_id='run_native_fixture', as_of_date='2026-10-26')
    observed = []
    class StopBeforeQuery(Exception):
        pass
    def capture_output(*identity):
        observed.append(identity)
        raise StopBeforeQuery
    monkeypatch.setattr(calculation, 'prepare_output', capture_output)
    monkeypatch.setattr(calculation.subprocess, 'check_output', lambda *a, **k: pytest.fail('no query before output identity'))
    with pytest.raises(StopBeforeQuery):
        calculation.calculate(args)
    assert observed == [(tmp_path/'Output/ShadowBI/run_native_fixture', tmp_path,
                         'run_native_fixture', 'snapshot_fixture', '2026-10-26')]
