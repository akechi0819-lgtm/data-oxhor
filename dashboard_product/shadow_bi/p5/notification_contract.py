"""Strict fixed notification requests; shared by receiver and privileged worker."""
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

RELEASE = re.compile(r"daily-[A-Za-z0-9_-]{1,96}")
JOB = re.compile(r"[0-9a-f]{64}")
SHA256 = re.compile(r"[0-9a-f]{64}")

class Rejected(ValueError):
    def __init__(self, reason, status=400):
        super().__init__(reason)
        self.status = status


def _json_object(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"notification manifest missing or unsafe: {path.name}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"notification manifest must be an object: {path.name}")
    return value


def _iso_date(value, name):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError(f"invalid {name}")


def current_manifest(library):
    """Read the active notification identity from an SQL release or rollback library.

    This deliberately uses only the standard library: receiver and notification
    workers run with a small memory limit and must not import warehouse code.
    """
    library = Path(library)
    candidate_path = library / 'candidate.json'
    release_path = library / 'release.json'
    sql_marked = any(path.exists() or path.is_symlink() for path in (candidate_path, release_path))
    if not sql_marked:
        legacy_path = library / 'library_manifest.json'
        manifest = _json_object(legacy_path)
        if manifest.get('schema_version') != 'business_query_library.v1':
            raise ValueError('unsupported legacy notification manifest')
        return manifest

    candidate = _json_object(candidate_path)
    release = _json_object(release_path)
    if candidate.get('schema_version') != 'sql_warehouse_candidate.v1':
        raise ValueError('unsupported SQL candidate schema')
    if release.get('schema_version') != 'sql_warehouse_release.v1':
        raise ValueError('unsupported SQL release schema')

    release_id = release.get('release_id')
    if (not isinstance(release_id, str) or not RELEASE.fullmatch(release_id)
            or library.parent.name != release_id):
        raise ValueError('SQL release identity differs from current path')
    batch_id = candidate.get('batch_id')
    if (not isinstance(batch_id, str) or not batch_id
            or release.get('batch_id') != batch_id):
        raise ValueError('SQL release batch differs from candidate')
    as_of_date = candidate.get('as_of_date')
    _iso_date(as_of_date, 'candidate as_of_date')
    if release.get('as_of_date') != as_of_date:
        raise ValueError('SQL release date differs from candidate')

    snapshots = candidate.get('snapshots')
    if (not isinstance(snapshots, dict) or set(snapshots) != {'training', 'abroad'}
            or not all(isinstance(value, str) and value for value in snapshots.values())
            or release.get('snapshots') != snapshots):
        raise ValueError('SQL release Snapshots differ from candidate')

    coverage = release.get('coverage')
    if not isinstance(coverage, dict):
        raise ValueError('SQL release coverage missing')
    through = candidate.get('through_date')
    _iso_date(through, 'candidate through_date')
    _iso_date(coverage.get('data_through'), 'release coverage data_through')
    abroad = coverage.get('study_abroad_source')
    if (coverage['data_through'] != through
            or coverage.get('snapshot_id') != snapshots['training']
            or not isinstance(abroad, dict)
            or abroad.get('snapshot_id') != snapshots['abroad']
            or abroad.get('through_date') != through):
        raise ValueError('SQL release coverage differs from candidate')

    candidate_ref = release.get('candidate')
    candidate_sha = release.get('candidate_sha256')
    actual_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    if (not isinstance(candidate_ref, dict) or candidate_ref.get('path') != 'candidate.json'
            or candidate_ref.get('sha256') != candidate_sha
            or not isinstance(candidate_sha, str) or not SHA256.fullmatch(candidate_sha)
            or actual_sha != candidate_sha):
        raise ValueError('SQL candidate digest differs from release')

    database = candidate.get('database')
    database_sha = release.get('database_sha256')
    if (not isinstance(database, dict) or database.get('path') != 'warehouse.duckdb'
            or not isinstance(database.get('sha256'), str)
            or not SHA256.fullmatch(database['sha256'])
            or database['sha256'] != database_sha):
        raise ValueError('SQL database identity differs from release')
    return release


def normalize(payload):
    if not isinstance(payload, dict) or set(payload) - {'operation','expected_release','as_of_date','retry'}:
        raise Rejected('unsupported request fields')
    if not {'operation','expected_release','as_of_date'} <= set(payload):
        raise Rejected('required request fields missing')
    if payload['operation'] not in ('preview','send-scheduled'):
        raise Rejected('unsupported fixed operation')
    if not isinstance(payload['expected_release'], str) or not RELEASE.fullmatch(payload['expected_release']):
        raise Rejected('invalid release')
    try:
        value = payload['as_of_date']
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise Rejected('invalid date') from None
    if type(payload.get('retry', False)) is not bool:
        raise Rejected('invalid retry flag')
    return {key: payload[key] for key in ('operation','expected_release','as_of_date')}


def job_id(payload):
    return hashlib.sha256(json.dumps(normalize(payload), sort_keys=True, separators=(',',':')).encode()).hexdigest()


def validate(payload, release, manifest, policy, now=None):
    item = normalize(payload)
    now = (now or datetime.now(ZoneInfo('Asia/Shanghai'))).astimezone(ZoneInfo('Asia/Shanghai'))
    if item['expected_release'] != release or item['as_of_date'] != manifest['as_of_date']:
        raise Rejected('formal release changed', 409)
    if item['as_of_date'] != now.date().isoformat():
        raise Rejected('today formal release required', 409)
    if manifest.get('coverage',{}).get('data_through') != (now.date()-timedelta(days=1)).isoformat():
        raise Rejected('yesterday complete cutoff required', 409)
    if item['operation'] == 'send-scheduled':
        if (not policy.get('imported_state_ready') or policy.get('no_backfill') is not True
                or policy.get('history_complete') is not False):
            raise Rejected('imported state and cutover proof required', 423)
        try:
            start = date.fromisoformat(policy['send_start_date'])
        except (ValueError, KeyError, TypeError):
            raise Rejected('cutover policy missing', 423) from None
        if now.date() < start:
            raise Rejected('before authorized no-backfill start', 403)
        if now.hour != 10:
            raise Rejected('outside Shanghai 10:00 hour', 403)
    return item
