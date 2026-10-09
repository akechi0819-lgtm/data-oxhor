"""Validate and package one management dashboard batch for static hosting."""
from __future__ import annotations

import argparse
from datetime import date
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from dashboard_product.online_team.export import validate_public_data


PACKAGE_FILES = frozenset({
    'index.html', 'prep_high.html', 'university.html', 'online.html',
    'styles.css', 'app.js', 'boards.css', 'boards.js',
    'data.json', 'university.data.json', 'prep_high.data.json',
    *(f'prep_high.{mask}.data.json' for mask in range(1, 8)),
})

# These are the complete files emitted into the sealed site/ directory. Some
# are source fragments already folded into the four public CSS/JS bundles.
SEALED_SITE_FILES = PACKAGE_FILES | frozenset({
    'capacity-view.css', 'capacity-view.js', 'flat-tables.css', 'flat-tables.js',
    'capacity-radar.css', 'capacity-radar.js',
    'suite-nav.css', 'suite-nav.js',
})

IDENTITY_KEYS = ('run_id', 'snapshot_id', 'data_through')
REFERENCE_PATHS = {
    'notifications_ref': 'notifications.json',
    'online_ref': 'online_shared_result.json',
    'details_ref': 'details.json',
}
FORBIDDEN_PUBLIC_KEYS = {
    'source_record', 'cash_source_record', 'work_order_id', 'student_id',
    'source_row_number', 'resource_description', 'query_receipts',
    'details_ref', 'records', 'diagnostics',
}
RUN_ID_RE = re.compile(r'run_[a-z0-9_-]{3,45}\Z')
SHA256_RE = re.compile(r'[0-9a-f]{64}\Z')


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f'{label} must not be a symlink: {path.name}')


def _safe_reference(root: Path, reference: object, name: str) -> Path:
    if not isinstance(reference, dict):
        raise ValueError(f'shared result requires {name}')
    relative = reference.get('path')
    expected_hash = reference.get('sha256')
    if relative != REFERENCE_PATHS[name] or not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
        raise ValueError(f'{name} must reference {REFERENCE_PATHS[name]} with a SHA-256 hash')
    rel_path = PurePosixPath(relative)
    if rel_path.is_absolute() or any(part in ('', '.', '..') for part in rel_path.parts):
        raise ValueError(f'{name} path must stay inside the shared result directory')
    path = root.joinpath(*rel_path.parts)
    _reject_symlink(path, name)
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError(f'{name} file is missing or escapes the shared result directory')
    if _sha256(path) != expected_hash:
        raise ValueError(f'{name} sha256 does not match the referenced file')
    return path


def _load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'{label} is not valid UTF-8 JSON') from exc
    if not isinstance(value, dict):
        raise ValueError(f'{label} must contain a JSON object')
    return value


def _identity(value: dict, label: str) -> dict:
    metadata = value.get('metadata')
    if not isinstance(metadata, dict) or not all(isinstance(metadata.get(key), str) and metadata[key] for key in IDENTITY_KEYS):
        raise ValueError(f'{label} has no explicit run, Snapshot, and data cutoff identity')
    return {key: metadata[key] for key in IDENTITY_KEYS}


def _check_identity(value: dict, expected: dict, label: str) -> None:
    if _identity(value, label) != expected:
        raise ValueError(f'{label} identity does not match shared_result.json')


def _validate_display_data(data: dict, label: str, expected: dict) -> None:
    validate_public_data(data)

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if FORBIDDEN_PUBLIC_KEYS.intersection(value):
                raise ValueError(f'{label} contains private evidence fields')
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    _check_identity(data, expected, label)


class _References(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str]] = []
        self.has_base = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == 'base':
            self.has_base = True
        if tag in ('link', 'script', 'img', 'iframe', 'source'):
            attr = 'href' if tag == 'link' else 'src'
            value = values.get(attr)
            if value:
                self.references.append((tag, value))
        if tag == 'a' and values.get('href'):
            self.references.append(('a', values['href']))


def _validate_html(name: str, content: bytes) -> dict | None:
    try:
        html = content.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError(f'{name} is not UTF-8 HTML') from exc
    if '<!doctype html>' not in html.lower():
        raise ValueError(f'{name} is not a complete HTML page')
    parser = _References()
    parser.feed(html)
    if parser.has_base:
        raise ValueError(f'{name} must not rewrite static resource paths with a base tag')
    for tag, reference in parser.references:
        if reference.startswith('#'):
            continue
        parts = urlsplit(reference)
        if parts.scheme or parts.netloc or parts.query:
            raise ValueError(f'{name} contains a non-local static reference')
        path = parts.path
        if path.startswith('./'):
            path = path[2:]
        rel = PurePosixPath(path)
        if rel.is_absolute() or any(part in ('', '.', '..') for part in rel.parts) or path not in PACKAGE_FILES:
            raise ValueError(f'{name} references a missing or unapproved resource: {reference}')
    marker = '<script id="dashboard-data" type="application/json">'
    if name != 'online.html':
        if marker in html:
            raise ValueError(f'{name} unexpectedly embeds a second data source')
        return None
    if html.count(marker) != 1:
        raise ValueError('online.html must contain one embedded dashboard data payload')
    try:
        data = json.loads(html.split(marker, 1)[1].split('</script>', 1)[0])
    except (json.JSONDecodeError, IndexError) as exc:
        raise ValueError('online.html contains invalid embedded dashboard data') from exc
    if not isinstance(data, dict):
        raise ValueError('online.html embedded data must be an object')
    return data


def _validate_local_code(files: dict[str, bytes]) -> None:
    allowed_fetch_targets = {
        '"./data.json"', "'./data.json'",
        '`./prep_high.${state.mask}.data.json`', '`./${board}.data.json`',
    }
    for name in ('app.js', 'boards.js', 'online.html'):
        text = files[name].decode('utf-8')
        targets = re.findall(r'\bfetch\s*\(\s*([^,\n]+)', text)
        if any(target.strip() not in allowed_fetch_targets for target in targets):
            raise ValueError(f'{name} requests a resource outside the static dashboard package')
        if re.search(r'\b(?:XMLHttpRequest|WebSocket|EventSource)\b', text):
            raise ValueError(f'{name} uses a network API outside the static dashboard package')
    for name in ('styles.css', 'boards.css'):
        text = files[name].decode('utf-8')
        if re.search(r'@import\b|url\s*\(', text, flags=re.IGNORECASE):
            raise ValueError(f'{name} references an external or unapproved asset')


def _read_site(site_dir: Path, identity: dict) -> dict[str, bytes]:
    _reject_symlink(site_dir, 'site directory')
    if not site_dir.is_dir():
        raise ValueError('shared result batch has no site directory')
    actual_files: set[str] = set()
    for root, dirs, files in os.walk(site_dir, followlinks=False):
        root_path = Path(root)
        for directory in dirs:
            path = root_path / directory
            _reject_symlink(path, 'site entry')
            if path.is_symlink() or not path.is_dir():
                raise ValueError('site directory contains a non-directory entry')
        for filename in files:
            path = root_path / filename
            _reject_symlink(path, 'site entry')
            relative = path.relative_to(site_dir).as_posix()
            if '/' in relative or relative not in SEALED_SITE_FILES:
                raise ValueError(f'site contains an unapproved resource: {relative}')
            if not path.is_file():
                raise ValueError(f'site resource is not a regular file: {relative}')
            actual_files.add(relative)
    missing_source = SEALED_SITE_FILES - actual_files
    if missing_source:
        raise ValueError('sealed site is missing required resources: ' + ', '.join(sorted(missing_source)))

    files = {name: (site_dir / name).read_bytes() for name in sorted(PACKAGE_FILES)}
    _validate_local_code(files)
    display_data: dict[str, dict] = {}
    for name, content in files.items():
        if not content:
            raise ValueError(f'site resource is empty: {name}')
        if name.endswith('.json'):
            try:
                value = json.loads(content.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f'{name} is not valid UTF-8 JSON') from exc
            if not isinstance(value, dict):
                raise ValueError(f'{name} must contain a JSON object')
            _validate_display_data(value, name, identity)
            display_data[name] = value

    embedded = None
    for name in ('index.html', 'prep_high.html', 'university.html', 'online.html'):
        parsed = _validate_html(name, files[name])
        if name == 'online.html':
            embedded = parsed
    if embedded is None:
        raise ValueError('online page is missing its embedded display data')
    _validate_display_data(embedded, 'online.html embedded data', identity)
    required_json = {
        'data.json', 'university.data.json', 'prep_high.data.json',
        *(f'prep_high.{mask}.data.json' for mask in range(1, 8)),
    }
    if set(display_data) != required_json:
        raise ValueError('site is missing one or more required display JSON resources')
    return files


def _validate_batch(shared_result: Path) -> tuple[dict[str, bytes], dict]:
    _reject_symlink(shared_result, 'shared result')
    if not shared_result.is_file():
        raise ValueError('shared result is missing or is not a regular file')
    root = shared_result.parent.resolve(strict=True)
    if shared_result.resolve(strict=True).parent != root:
        raise ValueError('shared result must be a direct file in its batch directory')
    shared = _load_json(shared_result, 'shared_result.json')
    identity = _identity(shared, 'shared_result.json')
    if not RUN_ID_RE.fullmatch(identity['run_id']):
        raise ValueError('shared result has an invalid run_id')
    try:
        date.fromisoformat(identity['data_through'])
    except ValueError as exc:
        raise ValueError('shared result has an invalid data_through date') from exc

    references = {name: _safe_reference(root, shared.get(name), name) for name in REFERENCE_PATHS}
    notifications = _load_json(references['notifications_ref'], 'notifications.json')
    online = _load_json(references['online_ref'], 'online_shared_result.json')
    details = _load_json(references['details_ref'], 'details.json')
    _check_identity(notifications, identity, 'notifications.json')
    _check_identity(online, identity, 'online_shared_result.json')
    _check_identity(details, identity, 'details.json')
    if notifications.get('data_through') != identity['data_through']:
        raise ValueError('notifications data_through does not match shared result metadata')
    details_ref = shared['details_ref']
    if not isinstance(details_ref.get('record_count'), int) or details_ref['record_count'] < 0:
        raise ValueError('details_ref requires a valid record_count')
    records = details.get('records')
    if not isinstance(records, list) or len(records) != details_ref['record_count']:
        raise ValueError('details record_count does not match details_ref')

    site_files = _read_site(root / 'site', identity)
    # Copy bytes already validated from the public allowlist only. Shared result,
    # notifications, online projection, and details remain local private inputs.
    return site_files, identity


def package(shared_result: Path, output_dir: Path) -> dict:
    shared_result = Path(shared_result).absolute()
    output_dir = Path(output_dir).absolute()
    files, identity = _validate_batch(shared_result)
    source_root = shared_result.parent.resolve(strict=True)
    output_resolved = output_dir.resolve(strict=False)
    if output_resolved.is_relative_to(source_root) or source_root.is_relative_to(output_resolved):
        raise ValueError('output directory must be separate from the shared result batch')
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError('output directory must not already exist')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f'.{output_dir.name}.', dir=output_dir.parent))
    try:
        manifest_files = []
        for name in sorted(files):
            target = temp_dir / name
            target.write_bytes(files[name])
            manifest_files.append({
                'path': name,
                'size_bytes': len(files[name]),
                'sha256': hashlib.sha256(files[name]).hexdigest(),
            })
        manifest = {
            'schema_version': 'management_dashboard_release.v1',
            **identity,
            'files': manifest_files,
        }
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
        (temp_dir / 'manifest.json').write_bytes(manifest_bytes)
        temp_dir.rename(output_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return {
        'status': 'packaged',
        **identity,
        'output_dir': str(output_dir),
        'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
        'file_count': len(manifest_files),
        'total_bytes': sum(entry['size_bytes'] for entry in manifest_files),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shared-result', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = package(args.shared_result, args.output_dir)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
