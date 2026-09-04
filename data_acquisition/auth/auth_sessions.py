from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping
import time

AUTH_SERVICES = frozenset({"bi"})


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
    session_paths.root.mkdir(parents=True, exist_ok=True)
    session_paths.cookies.write_text(json.dumps([dict(item) for item in cookies], ensure_ascii=False, indent=2), encoding="utf-8")
    session_paths.local_storage.write_text(json.dumps(dict(local_storage), ensure_ascii=False, indent=2), encoding="utf-8")
    session_paths.cookies.chmod(0o600)
    session_paths.local_storage.chmod(0o600)
    return session_paths


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
