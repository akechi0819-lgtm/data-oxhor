from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def write_manifest(*, output: Path, source_id: str, connector_id: str, requested_window: dict[str, str] | None, source_file: Path, status: str = "retrieved", errors: list[str] | None = None) -> Path:
    payload = {"schema_version": "data_acquisition_manifest.v1", "source_id": source_id, "connector_id": connector_id, "requested_window": requested_window or {}, "retrieved_at": datetime.now(timezone.utc).isoformat(), "source_file": str(source_file.resolve()), "sha256": sha256_file(source_file) if source_file.is_file() else None, "status": status, "errors": errors or []}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
