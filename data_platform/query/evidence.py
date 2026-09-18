"""Portable query evidence: exact bytes, bounded paths, and Snapshot identity."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib
from functools import wraps
from typing import Any

class EvidenceError(ValueError):
    pass

def guarded(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except EvidenceError:
            raise
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise EvidenceError(str(exc)) from exc
    return call

def load_json_bytes(raw):
    def invalid(value):
        raise EvidenceError('non-finite JSON number')
    return json.loads(raw, parse_constant=invalid)


def encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False).encode('utf-8')

def producer(name: str) -> dict:
    try:
        release = version('data-oxhor')
    except PackageNotFoundError:
        release = tomllib.loads((Path(__file__).resolve().parents[2] / 'pyproject.toml').read_text())['project']['version']
    return {'name': name, 'version': release}

def file_ref(path: Path, base: Path, media_type: str, **identity: str) -> dict:
    raw = path.read_bytes()
    return {**identity, 'path': path.relative_to(base).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw), 'media_type': media_type}

@guarded
def resolve_file(base: Path, ref: dict) -> Path:
    if not isinstance(ref, dict):
        raise EvidenceError('file reference must be an object')
    value = ref.get('path')
    if not isinstance(value, str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
        raise EvidenceError('unsafe evidence path')
    path = base / value
    if not path.is_file() or not path.resolve().is_relative_to(base.resolve()):
        raise EvidenceError('missing or escaping evidence file')
    raw = path.read_bytes()
    if ref.get('sha256') != hashlib.sha256(raw).hexdigest() or type(ref.get('size_bytes')) is not int or ref['size_bytes'] != len(raw):
        raise EvidenceError('evidence byte identity mismatch')
    if not isinstance(ref.get('media_type'), str) or '/' not in ref['media_type']:
        raise EvidenceError('invalid media type')
    return path

def metadata(document: dict) -> None:
    for field in ('run_id', 'snapshot_id'):
        if not isinstance(document.get(field), str) or not document[field]:
            raise EvidenceError(f'missing {field}')
    p = document.get('producer')
    if not isinstance(p, dict) or any(not isinstance(p.get(k), str) or not p[k].strip() or p[k] == 'unknown' for k in ('name', 'version')):
        raise EvidenceError('producer name and version required')
    try:
        stamp = datetime.fromisoformat(document['created_at'].replace('Z', '+00:00'))
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise EvidenceError('created_at must be UTC') from None

@guarded
def snapshot_ref(warehouse: Path, snapshot_id: str) -> dict:
    manifest = warehouse.parent / 'snapshot_manifest.json'
    try:
        raw = manifest.read_bytes()
        doc = load_json_bytes(raw)
        entries = [x for x in doc['artifacts'] if x['path'] == 'warehouse.duckdb']
        if doc['schema_version'] != 'warehouse_snapshot.v2' or doc['snapshot_id'] != snapshot_id or warehouse.name != 'warehouse.duckdb' or len(entries) != 1:
            raise ValueError()
        entry = entries[0]
        if entry['size_bytes'] != warehouse.stat().st_size or not re.fullmatch('[0-9a-f]{64}', entry['sha256']):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise EvidenceError('Snapshot manifest identity/path/size invalid') from exc
    return {'snapshot_id': snapshot_id, 'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'warehouse_sha256': entry['sha256']}

@guarded
def verify_receipt(path: Path) -> tuple[dict, dict]:
    doc = load_json_bytes(path.read_bytes())
    if doc.get('schema_version') != 'query_receipt.v1' or doc.get('kind') != 'query':
        raise EvidenceError('unsupported query receipt')
    metadata(doc)
    if not isinstance(doc.get('evidence_id'), str) or not re.fullmatch('evidence_[a-zA-Z0-9_-]+', doc['evidence_id']):
        raise EvidenceError('invalid evidence_id')
    snap = doc.get('snapshot_ref', {})
    if snap.get('snapshot_id') != doc['snapshot_id'] or any(not isinstance(snap.get(k), str) or not re.fullmatch('[0-9a-f]{64}', snap[k]) for k in ('manifest_sha256', 'warehouse_sha256')):
        raise EvidenceError('invalid snapshot_ref')
    paths = [resolve_file(path.parent, doc[k]) for k in ('sql', 'parameters', 'result')]
    if len(set(paths)) != 3:
        raise EvidenceError('query files must be distinct')
    paths[0].read_text(encoding='utf-8')
    load_json_bytes(paths[1].read_bytes())
    data = load_json_bytes(paths[2].read_bytes())
    if set(data) != {'columns', 'rows'} or not isinstance(data['columns'], list) or not all(isinstance(x,str) for x in data['columns']) or not isinstance(data['rows'], list) or any(not isinstance(r,list) or len(r) != len(data['columns']) for r in data['rows']):
        raise EvidenceError('invalid result rows/columns')
    if doc.get('columns') != data['columns'] or doc.get('row_count') != len(data['rows']):
        raise EvidenceError('receipt/result mismatch')
    limits = doc.get('limits', {})
    if any(type(limits.get(k)) is not int or limits[k] < 1 for k in ('max_rows','max_result_bytes')) or len(data['rows']) > limits['max_rows'] or paths[2].stat().st_size > limits['max_result_bytes']:
        raise EvidenceError('invalid result limits')
    for k in ('referenced_relations', 'referenced_source_ids'):
        if not isinstance(doc.get(k), list) or any(not isinstance(x,str) or not x for x in doc[k]):
            raise EvidenceError('invalid query provenance')
    if 'saved_query_ref' in doc:
        saved = doc['saved_query_ref']
        if not isinstance(saved, dict) or set(saved) != {'query_id','version'} or not isinstance(saved.get('query_id'),str) or not re.fullmatch('[a-z][a-z0-9_-]{2,63}',saved['query_id']) or not isinstance(saved.get('version'),str) or not re.fullmatch(r'v[0-9]+(?:\.[0-9]+){0,2}',saved['version']):
            raise EvidenceError('invalid saved query identity')
    return doc, data

@guarded
def read_query_result(response: dict, *, output_root: Path) -> dict:
    if response.get('schema_version') != 'controlled_query_result.v2' or response.get('status') != 'passed':
        raise EvidenceError('unsupported or failed controlled query response')
    run_id = response.get('run_id', '')
    if not re.fullmatch('run_[a-z0-9][a-z0-9_-]{2,67}', run_id):
        raise EvidenceError('invalid response run_id')
    if not (output_root / run_id).resolve().is_relative_to(output_root.resolve()):
        raise EvidenceError('run escapes output root')
    path = resolve_file(output_root / run_id, response['receipt'])
    receipt, data = verify_receipt(path)
    if any(receipt.get(k) != response.get(k) for k in ('run_id','snapshot_id')) or receipt['evidence_id'] != response['receipt'].get('evidence_id'):
        raise EvidenceError('response/receipt identity mismatch')
    if response.get('result') is not None and response['result'] != data:
        raise EvidenceError('inline result differs from evidence')
    return data
