"""Small file-backed bearer-key registry for the business data MCP service."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import uuid
from typing import Any

import fcntl


REGISTRY_SCHEMA = "business_data_mcp_keys.v1"
KEYS_FILE_ENV = "BUSINESS_DATA_MCP_KEYS_FILE"
KEY_ID_PATTERN = re.compile(r"^key_[0-9a-f]{32}$")


class KeyStoreError(ValueError):
    """The configured key registry cannot be safely read or updated."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _empty_registry() -> dict[str, Any]:
    return {"schema_version": REGISTRY_SCHEMA, "keys": []}


def _read_registry(path: Path, *, create_if_missing: bool = False) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if create_if_missing:
            return _empty_registry()
        raise KeyStoreError("KEY_REGISTRY_NOT_FOUND") from None
    except OSError:
        raise KeyStoreError("KEY_REGISTRY_UNREADABLE") from None
    try:
        registry = json.loads(raw)
    except json.JSONDecodeError:
        raise KeyStoreError("KEY_REGISTRY_INVALID") from None
    if (not isinstance(registry, dict) or registry.get("schema_version") != REGISTRY_SCHEMA
            or not isinstance(registry.get("keys"), list)):
        raise KeyStoreError("KEY_REGISTRY_INVALID")
    seen: set[str] = set()
    for item in registry["keys"]:
        if (not isinstance(item, dict) or not isinstance(item.get("key_id"), str)
                or not KEY_ID_PATTERN.fullmatch(item["key_id"]) or item["key_id"] in seen
                or not isinstance(item.get("label"), str)
                or not isinstance(item.get("token_sha256"), str)
                or len(item["token_sha256"]) != 64
                or not isinstance(item.get("created_at"), str)
                or (item.get("revoked_at") is not None and not isinstance(item.get("revoked_at"), str))):
            raise KeyStoreError("KEY_REGISTRY_INVALID")
        seen.add(item["key_id"])
    return registry


def _write_registry(path: Path, registry: dict[str, Any]) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(raw_temporary)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(registry, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError:
        raise KeyStoreError("KEY_REGISTRY_WRITE_FAILED") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


@contextmanager
def _registry_lock(path: Path):
    """Serialize CLI read-modify-write cycles through a stable sidecar lock.

    The JSON registry itself is atomically replaced, so it cannot safely be the
    locked inode: another process could replace it while a waiter holds the old
    inode. The sidecar stays in place across every registry update.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(path.name + ".lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
    except OSError:
        raise KeyStoreError("KEY_REGISTRY_LOCK_FAILED") from None


def issue_key(path: Path, label: str) -> dict[str, str]:
    label = label.strip()
    if not label or len(label) > 100:
        raise KeyStoreError("KEY_LABEL_INVALID")
    with _registry_lock(path):
        registry = _read_registry(path, create_if_missing=True)
        token = "bdmcp_" + secrets.token_urlsafe(32)
        entry = {
            "key_id": "key_" + uuid.uuid4().hex,
            "label": label,
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "created_at": _now(),
            "revoked_at": None,
        }
        registry["keys"].append(entry)
        _write_registry(path, registry)
    return {"key_id": entry["key_id"], "label": label, "token": token}


def revoke_key(path: Path, key_id: str) -> dict[str, str]:
    with _registry_lock(path):
        registry = _read_registry(path)
        for entry in registry["keys"]:
            if entry["key_id"] == key_id:
                if entry["revoked_at"] is None:
                    entry["revoked_at"] = _now()
                    _write_registry(path, registry)
                return {"key_id": key_id, "status": "revoked"}
        raise KeyStoreError("KEY_ID_NOT_FOUND")


def list_keys(path: Path) -> list[dict[str, str]]:
    registry = _read_registry(path)
    return [
        {"key_id": item["key_id"], "label": item["label"], "created_at": item["created_at"],
         "status": "revoked" if item["revoked_at"] is not None else "active"}
        for item in registry["keys"]
    ]


def key_id_for_token(path: Path, token: str) -> str | None:
    """Return the active key identity for a presented token, if any.

    The registry is read for every request so a revocation is effective without
    restarting the MCP process. Only a digest is compared and stored.
    """
    registry = _read_registry(path)
    candidate = hashlib.sha256(token.encode("utf-8")).hexdigest()
    match: str | None = None
    for entry in registry["keys"]:
        if entry["revoked_at"] is None and hmac.compare_digest(entry["token_sha256"], candidate):
            match = entry["key_id"]
    return match


def _registry_path(argument: str | None) -> Path:
    value = argument or os.environ.get(KEYS_FILE_ENV)
    if not value:
        raise KeyStoreError("KEY_REGISTRY_PATH_REQUIRED")
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="business-data-mcp-keys")
    parser.add_argument("--registry", help=f"registry path (defaults to ${KEYS_FILE_ENV})")
    subcommands = parser.add_subparsers(dest="command", required=True)
    issue = subcommands.add_parser("issue", help="create one independent bearer key")
    issue.add_argument("--label", required=True, help="person or client label")
    revoke = subcommands.add_parser("revoke", help="revoke a key immediately")
    revoke.add_argument("key_id")
    subcommands.add_parser("list", help="show key labels and status, never key material")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        registry_path = _registry_path(args.registry)
        if args.command == "issue":
            result: Any = issue_key(registry_path, args.label)
        elif args.command == "revoke":
            result = revoke_key(registry_path, args.key_id)
        else:
            result = list_keys(registry_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except KeyStoreError as exc:
        print(f"business-data-mcp-keys: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
