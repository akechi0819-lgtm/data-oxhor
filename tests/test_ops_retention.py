import json
from pathlib import Path

import pytest

from ops.pipeline import _retain_published
from ops import retention
from ops.retention import retain_candidates


def candidate(root, name):
    path = root / name
    path.mkdir()
    (path / 'warehouse.duckdb').write_bytes(b'fixture')
    return {'path': str(path), 'created_at': '2026-11-27T09:00:00+08:00',
            'biz_day': '2026-11-27', 'verified_release_id': name}


def test_deletes_old_enrolled_release_and_keeps_current_predecessor_and_references(tmp_path):
    root = tmp_path / 'releases'
    root.mkdir()
    entries = [candidate(root, name) for name in ('old', 'current', 'previous', 'referenced')]
    nested = Path(entries[2]['path']) / 'library'
    nested.mkdir()
    removed = retain_candidates(root, enrolled=entries, current=entries[1]['path'],
                                predecessor=nested, referenced=[entries[3]['path']])
    assert removed == [entries[0]['path']]
    assert not Path(entries[0]['path']).exists()
    assert all(Path(entry['path']).is_dir() for entry in entries[1:])
    assert not (tmp_path / 'releases-cold').exists()


def test_invalid_entry_or_missing_reference_does_not_delete(tmp_path):
    root = tmp_path / 'releases'
    root.mkdir()
    old, current, previous = [candidate(root, name) for name in ('old', 'current', 'previous')]
    invalid = dict(previous, verified_release_id='another-release')
    with pytest.raises(ValueError, match='identity'):
        retain_candidates(root, enrolled=[old, current, invalid], current=current['path'],
                          predecessor=previous['path'], referenced=[])
    assert Path(old['path']).is_dir()
    with pytest.raises(FileNotFoundError):
        retain_candidates(root, enrolled=[old, current], current=current['path'],
                          predecessor=root / 'missing', referenced=[])
    assert Path(old['path']).is_dir()


def test_retry_recovers_after_partial_deletion(tmp_path):
    root = tmp_path / 'releases'
    root.mkdir()
    old, current, previous = [candidate(root, name) for name in ('old', 'current', 'previous')]
    (root / 'old' / 'warehouse.duckdb').unlink()
    (root / 'old').rmdir()
    assert retain_candidates(root, enrolled=[old, current, previous], current=current['path'],
                             predecessor=previous['path'], referenced=[]) == [old['path']]


def test_published_callback_keeps_previous_library_within_direct_release(tmp_path):
    root = tmp_path / 'releases'
    root.mkdir()
    old, previous, current = [candidate(root, name) for name in ('old', 'previous', 'current')]
    previous_library = Path(previous['path']) / 'library'
    previous_library.mkdir()
    (tmp_path / 'release-retention.json').write_text(json.dumps([old, previous]))
    events = []
    _retain_published(tmp_path, {'release': 'current', 'candidate': current['path'],
                                 'predecessor': str(previous_library), 'biz_day': '2026-11-27'}, events.append)
    assert events == [{'status': 'passed', 'removed': [old['path']]}]
    assert [e['path'] for e in json.loads((tmp_path / 'release-retention.json').read_text())] == [
        previous['path'], current['path']]
    assert not Path(old['path']).exists()


def test_callback_records_failure_and_retries_partial_deletion(tmp_path, monkeypatch):
    root = tmp_path / 'releases'
    root.mkdir()
    old1, old2, previous, current = [
        candidate(root, name) for name in ('old1', 'old2', 'previous', 'current')
    ]
    (tmp_path / 'release-retention.json').write_text(json.dumps([old1, old2, previous]))
    original = retention.shutil.rmtree

    def fail_second(path):
        if path.name == 'old2':
            raise OSError('simulated filesystem failure')
        original(path)

    publication = {'release': 'current', 'candidate': current['path'],
                   'predecessor': previous['path'], 'biz_day': '2026-11-27'}
    events = []
    monkeypatch.setattr(retention.shutil, 'rmtree', fail_second)
    _retain_published(tmp_path, publication, events.append)
    assert events[-1] == {'status': 'failed', 'error_type': 'OSError'}
    assert not Path(old1['path']).exists() and Path(old2['path']).is_dir()
    assert len(json.loads((tmp_path / 'release-retention.json').read_text())) == 4

    monkeypatch.setattr(retention.shutil, 'rmtree', original)
    _retain_published(tmp_path, publication, events.append)
    assert events[-1] == {'status': 'passed', 'removed': [old1['path'], old2['path']]}
    assert [entry['path'] for entry in json.loads((tmp_path / 'release-retention.json').read_text())] == [
        previous['path'], current['path']]
    assert not Path(old2['path']).exists()
