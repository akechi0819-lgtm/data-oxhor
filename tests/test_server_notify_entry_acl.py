import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'monitoring_product/deploy/run_server_notify.sh'


def _acl_commands(root):
    source = SCRIPT.read_text()
    start = source.index("/srv/shadow-bi/venv/bin/python - <<'PY'\n") + len("/srv/shadow-bi/venv/bin/python - <<'PY'\n")
    end = source.index('\nPY\n# A transient bounded process', start)
    snippet = source[start:end].replace(
        "base=pathlib.Path('/var/lib/shadow-bi')",
        f"base=pathlib.Path({str(root)!r})",
    )
    commands = []
    real_lstat = Path.lstat

    def root_owned_lstat(path):
        info = real_lstat(path)
        return SimpleNamespace(st_uid=0, st_mode=info.st_mode)

    def record(command, check):
        commands.append(command)

    with patch.object(Path, 'lstat', root_owned_lstat), patch('subprocess.run', side_effect=record):
        exec(compile(snippet, str(SCRIPT), 'exec'), {})
    return commands


def _sql_release(library):
    snapshots = {'training': 'snapshot-training', 'abroad': 'snapshot-abroad'}
    through = '2026-11-05'
    database_bytes = b'synthetic duckdb'
    preview_bytes = b'{}'
    (library / 'warehouse.duckdb').write_bytes(database_bytes)
    (library / 'notification-preview.json').write_bytes(preview_bytes)
    candidate = {
        'schema_version': 'sql_warehouse_candidate.v1',
        'batch_id': 'run-synthetic',
        'as_of_date': '2026-11-06',
        'through_date': through,
        'snapshots': snapshots,
        'database': {'path': 'warehouse.duckdb', 'sha256': hashlib.sha256(database_bytes).hexdigest()},
        'notification_preview': {'path': 'notification-preview.json', 'sha256': hashlib.sha256(preview_bytes).hexdigest()},
    }
    candidate_bytes = json.dumps(candidate).encode()
    (library / 'candidate.json').write_bytes(candidate_bytes)
    digest = hashlib.sha256(candidate_bytes).hexdigest()
    release = {
        'schema_version': 'sql_warehouse_release.v1',
        'release_id': library.parent.name,
        'batch_id': candidate['batch_id'],
        'as_of_date': candidate['as_of_date'],
        'snapshots': snapshots,
        'coverage': {
            'data_through': through,
            'snapshot_id': snapshots['training'],
            'study_abroad_source': {'snapshot_id': snapshots['abroad'], 'through_date': through},
        },
        'candidate': {'path': 'candidate.json', 'sha256': digest},
        'candidate_sha256': digest,
        'database_sha256': candidate['database']['sha256'],
    }
    (library / 'release.json').write_text(json.dumps(release))


def test_acl_preflight_grants_only_sql_release_files(tmp_path):
    release = tmp_path / 'releases' / 'daily-sql-fixture'
    library = release / 'library'
    library.mkdir(parents=True)
    (tmp_path / 'current').symlink_to(release)
    _sql_release(library)

    commands = _acl_commands(tmp_path)
    file_acl_paths = [Path(command[-1]) for command in commands if command[2].endswith('r--')]
    assert file_acl_paths == [
        library / 'release.json',
        library / 'candidate.json',
        library / 'warehouse.duckdb',
        library / 'notification-preview.json',
    ]
    assert not any('landing' in str(path) or 'source' in str(path) for path in file_acl_paths)


def test_acl_preflight_keeps_only_two_legacy_rollback_files(tmp_path):
    release = tmp_path / 'releases' / 'daily-legacy-fixture'
    library = release / 'library'
    library.mkdir(parents=True)
    (tmp_path / 'current').symlink_to(release)
    (library / 'library_manifest.json').write_text('{}')
    (library / 'business.duckdb').write_bytes(b'legacy fixture')

    commands = _acl_commands(tmp_path)
    file_acl_paths = [Path(command[-1]) for command in commands if command[2].endswith('r--')]
    assert file_acl_paths == [library / 'library_manifest.json', library / 'business.duckdb']


def test_sql_digest_failure_happens_before_any_acl_change(tmp_path):
    release = tmp_path / 'releases' / 'daily-sql-fixture'
    library = release / 'library'
    library.mkdir(parents=True)
    (tmp_path / 'current').symlink_to(release)
    _sql_release(library)
    manifest_path = library / 'release.json'
    manifest = json.loads(manifest_path.read_bytes())
    manifest['candidate_sha256'] = '0' * 64
    manifest_path.write_text(json.dumps(manifest))

    real_lstat = Path.lstat

    def root_owned_lstat(path):
        info = real_lstat(path)
        return SimpleNamespace(st_uid=0, st_mode=info.st_mode)

    commands = []
    with patch.object(Path, 'lstat', root_owned_lstat), patch('subprocess.run', side_effect=lambda *args, **kwargs: commands.append(args[0])):
        source = SCRIPT.read_text()
        start = source.index("/srv/shadow-bi/venv/bin/python - <<'PY'\n") + len("/srv/shadow-bi/venv/bin/python - <<'PY'\n")
        end = source.index('\nPY\n# A transient bounded process', start)
        snippet = source[start:end].replace(
            "base=pathlib.Path('/var/lib/shadow-bi')",
            f"base=pathlib.Path({str(tmp_path)!r})",
        )
        with pytest.raises(ValueError, match='candidate digest'):
            exec(compile(snippet, str(SCRIPT), 'exec'), {})
    assert commands == []
