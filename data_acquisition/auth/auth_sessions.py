from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping
import time
import os
import tempfile

AUTH_SERVICES = frozenset({"bi", "xhs", "ocean", "tencent_ads", "dingtalk_sem"})


class AuthSessionError(RuntimeError):
    pass


class AuthSessionMissingError(AuthSessionError):
    pass


class AuthSessionExpiredError(AuthSessionError):
    pass


@dataclass(frozen=True, slots=True)
class AuthSessionPaths:
    repo_root: Path
    service: str

    def __post_init__(self) -> None:
        if self.service not in AUTH_SERVICES:
            raise ValueError(f"unsupported auth service: {self.service}")
        object.__setattr__(self, "repo_root", Path(self.repo_root).expanduser())

    @property
    def root(self) -> Path:
        return self.repo_root / "data_acquisition" / "storage" / "auth_sessions" / self.service

    @property
    def cookies(self) -> Path:
        return self.root / "cookies.json"

    @property
    def local_storage(self) -> Path:
        return self.root / "localStorage.json"

    @property
    def browser_profile(self) -> Path:
        return self.repo_root / "data_acquisition" / "storage" / "browser_profiles" / self.service


def write_auth_session(service: str, *, cookies: list[Mapping[str, Any]], local_storage: Mapping[str, Any], paths: AuthSessionPaths | None = None) -> AuthSessionPaths:
    session_paths = paths or AuthSessionPaths(Path("."), service)
    if session_paths.service != service:
        raise ValueError("auth service/path mismatch")
    session_paths.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    session_paths.root.chmod(0o700)
    # New files are private before any credential bytes are written. Keep the
    # existing JSON formats and replace atomically; never print their contents.
    for path, value in ((session_paths.cookies, [dict(item) for item in cookies]),
                        (session_paths.local_storage, dict(local_storage))):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=session_paths.root,
                                         prefix=".auth-", delete=False) as handle:
            temporary = Path(handle.name)
            try:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return session_paths


def import_auth_session_file(service: str, *, source: Path, expected_sha256: str,
                             paths: AuthSessionPaths, save: bool = False) -> dict[str, Any]:
    """Receive one explicit browser transfer; never return cookie/storage values.

    Defaults to validation only. The browser owner supplies the exact path and
    digest; this function does not search Downloads or browser profile storage.
    """
    import hashlib
    import re
    if service not in AUTH_SERVICES or paths.service != service:
        raise AuthSessionError('auth_transfer_service_mismatch')
    if not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
        raise AuthSessionError('auth_transfer_digest_invalid')
    source = Path(source)
    if not source.is_absolute() or source.is_symlink() or not source.is_file():
        raise AuthSessionError('auth_transfer_explicit_file_required')
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise AuthSessionError('auth_transfer_digest_mismatch')
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise AuthSessionError('auth_transfer_json_invalid') from None
    if (not isinstance(value, dict) or set(value) != {'cookies', 'localStorage'}
            or not isinstance(value['cookies'], list)
            or not isinstance(value['localStorage'], dict)
            or any(not isinstance(c, dict) or not isinstance(c.get('name'), str)
                   or not isinstance(c.get('value'), str) for c in value['cookies'])
            or any(not isinstance(k, str) or not isinstance(v, str)
                   for k, v in value['localStorage'].items())):
        raise AuthSessionError('auth_transfer_format_invalid')
    if save:
        write_auth_session(service, cookies=value['cookies'],
                           local_storage=value['localStorage'], paths=paths)
    return {'format_valid': True, 'service': service, 'cookie_count': len(value['cookies']),
            'local_storage_key_count': len(value['localStorage']), 'credentials_written': save}


def _all_cookie_expirations_are_past(cookies: list[dict[str, Any]]) -> bool:
    expirations = []
    for cookie in cookies:
        try:
            expiry = float(cookie.get("expirationDate", cookie.get("expires")))
        except (TypeError, ValueError):
            continue
        if expiry > 0:
            expirations.append(expiry)
    return bool(expirations) and all(expiry <= datetime.now().timestamp() for expiry in expirations)
