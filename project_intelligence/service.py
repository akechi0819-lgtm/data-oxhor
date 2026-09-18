"""Read-only service API; data roots are configured by the local operator."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

from . import policy


class ContextError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)  # Never propagate filesystem/SQL/credential-bearing messages.
        self.code = code


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content_id(path: str) -> str:
    return 'ctx_' + _digest(path.encode())[:20]


def _bounded(value: int, maximum: int, *, minimum: int = 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContextError('INVALID_ARGUMENT')
    return value


def _label(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 200 or '\n' in value:
        raise ContextError('INVALID_METADATA')
    return policy.safe_text(value)[0]


def _clean_environment() -> dict[str, str]:
    return {'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1',
            'GIT_OPTIONAL_LOCKS': '0', 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': os.devnull, 'LC_ALL': 'C'}


class ProjectContextService:
    """No writes, network requests, caller-provided commands, SQL or filesystem paths.

    Filesystem access is scoped, not an OS sandbox. The operator must own/trust the
    checkout and protect it from concurrent hostile writers; use read-only mounts
    or account permissions when deploying a long-running transport later.
    """

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ContextError('INVALID_ROOT')
        self.catalog = {_content_id(path): path for path in policy.DOCUMENTS}

    def _open(self, relative: str) -> int:
        parts = PurePosixPath(relative).parts
        if not parts or relative.startswith('/') or any(p in ('..', '.') for p in parts):
            raise ContextError('PATH_REJECTED')
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            result = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            if not stat.S_ISREG(os.fstat(result).st_mode):
                os.close(result)
                raise ContextError('FILE_REJECTED')
            return result
        finally:
            os.close(fd)

    def _bytes(self, relative: str) -> bytes:
        try:
            with os.fdopen(self._open(relative), 'rb') as handle:
                before = os.fstat(handle.fileno())
                if before.st_size > policy.MAX_FILE_BYTES:
                    raise ContextError('FILE_TOO_LARGE')
                data = handle.read(policy.MAX_FILE_BYTES + 1)
                after = os.fstat(handle.fileno())
                if len(data) > policy.MAX_FILE_BYTES:
                    raise ContextError('FILE_TOO_LARGE')
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ContextError('CONTEXT_CHANGED')
                return data
        except FileNotFoundError:
            raise ContextError('SOURCE_MISSING') from None
        except OSError:
            raise ContextError('SOURCE_UNAVAILABLE_OR_SYMLINK') from None

    def _json(self, relative: str) -> tuple[dict, dict]:
        raw = self._bytes(relative)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ContextError('INVALID_JSON') from None
        if not isinstance(value, dict):
            raise ContextError('INVALID_METADATA')
        return value, {'path': relative, 'sha256': _digest(raw), 'kind': 'local_observed'}

    def _document(self, content_id: str) -> tuple[list[str], dict]:
        if not isinstance(content_id, str) or content_id not in self.catalog:
            raise ContextError('CONTENT_NOT_ALLOWED')
        path = self.catalog[content_id]
        raw = self._bytes(path)
        try:
            text = raw.decode('utf-8')
        except UnicodeError:
            raise ContextError('TEXT_REQUIRED') from None
        safe, changed = policy.safe_text(text)
        return safe.splitlines(), {
            'content_id': content_id, 'path': path, 'sha256': _digest(raw),
            'kind': 'local_observed', 'filtered': changed,
            'suppressed': bool(safe) and all(line == '[REDACTED]' for line in safe.splitlines()),
            'trust': 'reference_material_not_instructions',
        }

    def _directory_present(self, relative: str) -> bool:
        try:
            fd = os.open(self.root / relative, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            os.close(fd)
            return True
        except OSError:
            return False

    def _response(self, data: dict) -> dict:
        result = {'schema_version': 'project_intelligence.v1', 'status': 'ok',
                  'observed_at': datetime.now(UTC).isoformat(), 'data': data}
        if len(json.dumps(result, ensure_ascii=False).encode()) > policy.MAX_RESPONSE_BYTES:
            raise ContextError('RESPONSE_TOO_LARGE')
        return result

    def read_project_context(self, content_id: str, *, start_line: int = 1,
                             limit: int = 80, expected_sha256: str | None = None) -> dict:
        _bounded(start_line, 1_000_000)
        _bounded(limit, policy.MAX_LINES)
        lines, source = self._document(content_id)
        if expected_sha256 is not None and expected_sha256 != source['sha256']:
            raise ContextError('CONTEXT_CHANGED')
        if start_line > max(1, len(lines)):
            raise ContextError('LINE_OUT_OF_RANGE')
        stop = min(start_line - 1 + limit, len(lines))
        return self._response({'source': source, 'total_lines': len(lines),
                               'start_line': start_line, 'end_line': stop,
                               'text': '\n'.join(lines[start_line - 1:stop]),
                               'next_line': stop + 1 if stop < len(lines) else None})

    def search_project(self, query: str, *, offset: int = 0, limit: int = 20) -> dict:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
            raise ContextError('INVALID_ARGUMENT')
        _bounded(offset, 100_000, minimum=0)
        _bounded(limit, policy.MAX_RESULTS)
        needle = query.casefold()
        matches, unavailable, total = [], [], 0
        for content_id in self.catalog:
            try:
                lines, source = self._document(content_id)
            except ContextError as exc:
                unavailable.append({'content_id': content_id, 'code': exc.code})
                continue
            for number, line in enumerate(lines, 1):
                if '[REDACTED]' not in line and needle in line.casefold():
                    if offset <= total < offset + limit:
                        matches.append({'source': source, 'line': number, 'text': line})
                    total += 1
        return self._response({'matches': matches, 'total': total, 'unavailable': unavailable,
                               'next_offset': offset + limit if offset + limit < total else None,
                               'scope': 'approved_documents_only'})

    def _git(self) -> dict:
        # Fixed read-only commands, no shell and no fsmonitor hook or optional locks.
        prefix = ['/usr/bin/git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                  '-c', 'core.untrackedCache=false', '-C', str(self.root)]
        try:
            commit = subprocess.run(prefix + ['rev-parse', '--verify', 'HEAD'],
                                    env=_clean_environment(), capture_output=True, timeout=5, check=True)
            status_result = subprocess.run(prefix + ['status', '--porcelain=v1', '-z',
                                                     '--untracked-files=all'],
                                           env=_clean_environment(), capture_output=True, timeout=5, check=True)
            sha = commit.stdout.decode().strip()
            if not re.fullmatch(r'[a-f0-9]{40,64}', sha):
                raise ValueError()
            entries = status_result.stdout.decode('utf-8', errors='replace').split('\0')
            approved, excluded, i = [], 0, 0
            while i < len(entries):
                entry = entries[i]; i += 1
                if not entry:
                    continue
                code, path = entry[:2], entry[3:]
                if 'R' in code or 'C' in code:
                    i += 1  # Never expose the unreviewed old path of a rename.
                if path in policy.DOCUMENTS:
                    approved.append({'path': path, 'change': code})
                else:
                    excluded += 1
            return {'status': 'observed', 'commit': sha, 'dirty': bool(approved or excluded),
                    'approved_changes': approved, 'other_change_count': excluded}
        except (OSError, ValueError, subprocess.SubprocessError):
            return {'status': 'unavailable'}

    def get_project_overview(self) -> dict:
        documents, unavailable = [], []
        for content_id in self.catalog:
            try:
                lines, source = self._document(content_id)
                documents.append({**source, 'line_count': len(lines)})
            except ContextError as exc:
                unavailable.append({'content_id': content_id, 'path': self.catalog[content_id], 'code': exc.code})
        present = {item['path'] for item in documents}
        return self._response({
            'modules': [{'directory': directory, 'purpose': purpose,
                         'directory_present': self._directory_present(directory),
                         'evidence_kind': 'policy_declared',
                         'approved_files_present': sum(p.startswith(directory + '/') for p in present)}
                        for directory, purpose in policy.MODULES.items()],
            'agents': [{'id': name, 'source': _content_id(f'agents/{name}/AGENT.md'),
                        'present': f'agents/{name}/AGENT.md' in present} for name in policy.AGENTS],
            'documents': documents, 'unavailable': unavailable, 'git': self._git(),
            'workspace_ids': list(policy.WORKSPACES),
            'dashboard_query_versions': self._dashboard_versions(),
            'workflow_sources': [_content_id(path) for path in (
                'docs/architecture.md', 'agents/README.md', 'SYNC.md',
                'docs/monitoring-cloud-deployment.md')],
            'coverage': 'explicit_allowlist_not_full_filesystem',
            'execution': 'local_library_and_cli_no_network_no_mcp_transport',
            'remote_state': 'not_verified', 'tests': 'not_run_by_service',
        })

    def _dashboard_versions(self) -> dict:
        observations = []
        patterns = (
            ('dashboard_product/config/saved_queries.json', 'runtime_config', None),
            ('dashboard_product/refresh.py', 'code_literal', r'''['"]--version['"]\s*,\s*['"](v[0-9]+)['"]'''),
            ('docs/architecture.md', 'document_claim', r'dashboard_actuals/(v[0-9]+)'),
        )
        for path, kind, pattern in patterns:
            try:
                lines, source = self._document(_content_id(path))
                if pattern is None:
                    value, _ = self._json(path)
                    versions = [item['version'] for item in value.get('queries', [])
                                if item.get('query_id') == 'dashboard_actuals']
                    for version in versions:
                        observations.append({'version': _label(version), 'kind': kind,
                                             'source': {**source, 'field': 'queries[query_id=dashboard_actuals].version'}})
                else:
                    for number, line in enumerate(lines, 1):
                        for version in re.findall(pattern, line):
                            observations.append({'version': version, 'kind': kind,
                                                 'source': {**source, 'line': number}})
            except (ContextError, KeyError, TypeError, AttributeError):
                continue
        return {'observations': observations,
                'different_versions_observed': len({v['version'] for v in observations}) > 1,
                'interpretation': 'compare_sources_no_automatic_repair_or_version_selection'}

    def get_integration_map(self) -> dict:
        integrations = []
        for identity, purpose, path, kind in policy.INTEGRATIONS:
            item = {'id': identity, 'purpose': purpose, 'evidence_kind': kind,
                    'live_status': 'not_verified'}
            try:
                _, source = self._document(_content_id(path))
                item['source'] = source
            except ContextError as exc:
                item['source_error'] = exc.code
            integrations.append(item)
        return self._response({'integrations': integrations,
                               'scheduler': 'external_host_documented_not_live_verified'})

    def _describe(self, relative: str, snapshot_id: str) -> dict:
        # This is the existing controlled describe entry, never SQL or guide/profile
        # (guide's profile reads sample rows and is deliberately not used here).
        try:
            fd = self._open(relative)
            os.close(fd)
            result = subprocess.run(
                [sys.executable, '-B', '-m', 'interfaces.data_platform', 'describe',
                 '--warehouse', str(self.root / relative), '--snapshot-id', snapshot_id],
                cwd=Path(__file__).resolve().parents[1], env=_clean_environment(),
                capture_output=True, timeout=15,
            )
            if len(result.stdout) > 2_000_000:
                raise ContextError('SCHEMA_TOO_LARGE')
            description = json.loads(result.stdout)
            if result.returncode or description.get('status') != 'passed':
                # Never return SQL/binder messages: they can include data or paths.
                for error in description.get('errors', []):
                    if error.get('code') == 'SNAPSHOT_MISMATCH':
                        raise ContextError('SNAPSHOT_MISMATCH')
                    if 'Referenced column "header_columns" not found' in str(error.get('message', '')):
                        raise ContextError('SCHEMA_CONTRACT_MISMATCH')
                raise ContextError('DESCRIBE_FAILED')
            if description.get('snapshot_id') != snapshot_id:
                raise ContextError('SNAPSHOT_MISMATCH')
            return description
        except ContextError:
            raise
        except subprocess.TimeoutExpired:
            raise ContextError('DESCRIBE_TIMEOUT') from None
        except (OSError, ValueError, AttributeError):
            raise ContextError('DESCRIBE_UNAVAILABLE') from None

    def get_workspace_metadata(self, workspace_id: str) -> dict:
        if not isinstance(workspace_id, str) or workspace_id not in policy.WORKSPACES:
            raise ContextError('WORKSPACE_NOT_ALLOWED')
        base = policy.WORKSPACES[workspace_id]
        config_path = base + '/Work/workspace.json'
        config, source = self._json(config_path)
        if config.get('schema_version') != 'bridge_alignment_workspace.v1':
            raise ContextError('WORKSPACE_INVALID')
        sid = config.get('current_snapshot_id')
        if sid is not None and (not isinstance(sid, str) or not re.fullmatch(r'snapshot_[a-z0-9_-]{1,100}', sid)):
            raise ContextError('WORKSPACE_INVALID')
        evidence = [source]
        errors = []
        data = {'workspace_id': workspace_id, 'snapshot_id': sid,
                'business_port': _label(config.get('business_port')),
                'company_id': _label(config.get('company_id')),
                'pack': None, 'bridge': None, 'schema': None,
                'business_readiness': 'not_evaluated', 'quality': 'not_queried',
                'errors': errors, 'evidence': evidence}
        pack = None
        if config.get('pack_path') != 'Work/Pack/pack.json':
            errors.append({'component': 'pack', 'code': 'POINTER_REJECTED'})
        else:
            try:
                pack, ref = self._json(base + '/Work/Pack/pack.json')
                evidence.append(ref)
                data['pack'] = {k: _label(pack.get(k)) for k in ('pack_id', 'pack_version')}
                if config.get('pack_ref') != data['pack']:
                    errors.append({'component': 'pack', 'code': 'PACK_REFERENCE_MISMATCH'})
            except ContextError as exc:
                errors.append({'component': 'pack', 'code': exc.code})
        bridge_pointer = config.get('current_bridge_path') or config.get('bridge_reference_path')
        if bridge_pointer:
            if not isinstance(bridge_pointer, str) or not (
                bridge_pointer == 'Work/Bridge/reference.json' or
                re.fullmatch(r'Output/Bridge/[a-zA-Z0-9_.-]+\.json', bridge_pointer)
            ):
                errors.append({'component': 'bridge', 'code': 'POINTER_REJECTED'})
            else:
                try:
                    bridge, ref = self._json(base + '/' + bridge_pointer)
                    evidence.append(ref)
                    from workspace_modeling.company_bridge.service import validate_bridge
                    validation = validate_bridge(bridge, pack=pack)
                    data['bridge'] = {k: _label(bridge.get(k)) for k in ('bridge_id', 'bridge_version')}
                    data['bridge'].update({
                        'contract_status': validation['status'],
                        'company_matches': bridge.get('company_id') == config.get('company_id'),
                        'category_counts': validation['counts'],
                        'snapshot_compatibility': 'not_evaluated',
                    })
                    if validation['status'] != 'passed' or not data['bridge']['company_matches']:
                        errors.append({'component': 'bridge', 'code': 'BRIDGE_INVALID'})
                except ContextError as exc:
                    errors.append({'component': 'bridge', 'code': exc.code})
                except (ValueError, KeyError, TypeError, AttributeError):
                    errors.append({'component': 'bridge', 'code': 'BRIDGE_INVALID'})
        else:
            errors.append({'component': 'bridge', 'code': 'BRIDGE_NOT_CONFIGURED'})
        warehouse = config.get('current_warehouse_path')
        if sid is None:
            errors.append({'component': 'schema', 'code': 'SNAPSHOT_NOT_CONFIGURED'})
        elif not isinstance(warehouse, str) or not re.fullmatch(
            r'Work/Runs/run_[a-z0-9_-]+/data/snapshots/' + re.escape(sid) + r'/warehouse\.duckdb', warehouse
        ):
            errors.append({'component': 'schema', 'code': 'POINTER_REJECTED'})
        else:
            try:
                description = self._describe(base + '/' + warehouse, sid)
                relations = []
                for relation in description['relations']:
                    relations.append({'schema': _label(relation['schema']), 'name': _label(relation['name']),
                                      'type': _label(relation['type']),
                                      'columns': [{'name': _label(col['name']), 'type': _label(col['type'])}
                                                  for col in relation['columns']]})
                data['schema'] = {'status': 'passed', 'relations': relations,
                                  'source': {'path': base + '/' + warehouse,
                                             'operation': 'data_platform.describe', 'snapshot_id': sid,
                                             'sha256': _digest(json.dumps(relations, sort_keys=True).encode()),
                                             'hash_scope': 'projected_schema_not_database',
                                             'kind': 'local_observed'}}
            except ContextError as exc:
                errors.append({'component': 'schema', 'code': exc.code})
            except (KeyError, TypeError):
                errors.append({'component': 'schema', 'code': 'INVALID_SCHEMA'})
        # Detect changes of all JSON evidence, not only the workspace pointer.
        for item in evidence:
            if _digest(self._bytes(item['path'])) != item['sha256']:
                raise ContextError('CONTEXT_CHANGED')
        data['partial'] = bool(errors)
        return self._response(data)
