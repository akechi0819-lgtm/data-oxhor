"""Package an explicit paired foundation Snapshot and its calculation inputs."""
from __future__ import annotations

from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tempfile
from typing import Any

from data_acquisition.jobs.daily_warehouses import assert_daily_ready
from data_platform.query.evidence import read_query_result, resolve_file
from data_platform.snapshots.ingest import SNAPSHOT_ID
from interfaces.data_platform import RUN_ID


SCHEMA_VERSION = "shadow_foundation_bundle.v1"
REMOTE_RELEASE_ROOT = "/var/lib/shadow-bi/releases"
HISTORY_KINDS = ("resources", "contracts", "languages")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is missing or invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _relative(value: str, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be a workspace-relative path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"{label} is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError(f"{label} is unsafe")
    return path


def _iso_date(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("as_of_date must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("as_of_date must be an ISO date") from error
    if parsed.isoformat() != value:
        raise ValueError("as_of_date must be an ISO date")
    return value


def _snapshot_ids(value: dict[str, Any]) -> tuple[str, str]:
    """Accept daily_warehouses IDs or its returned explicit source record."""
    sources = value.get("sources", value)

    def get(keys: tuple[str, ...]) -> str:
        for key in keys:
            candidate = sources.get(key) if isinstance(sources, dict) else None
            if isinstance(candidate, dict):
                candidate = candidate.get("snapshot_id")
            if isinstance(candidate, str) and SNAPSHOT_ID.fullmatch(candidate):
                return candidate
        raise ValueError("explicit BI and study-abroad Snapshot IDs are required")

    training = get(("bi", "training"))
    abroad = get(("study_abroad", "abroad"))
    if training == abroad:
        raise ValueError("paired foundation Snapshots must be distinct")
    return training, abroad


def _sha_size(path: Path) -> tuple[str, int]:
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("transfer source must be a regular file")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("transfer source changed while opening")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
        after = os.fstat(stream.fileno())
    current = path.stat(follow_symlinks=False)
    stable_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if (stable_before != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or stable_before != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            or size != before.st_size):
        raise ValueError("transfer source changed while hashing")
    return digest.hexdigest(), size


class _Bundle:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve(strict=True)
        self.files: dict[str, tuple[Path, str, int]] = {}
        self.generated: dict[str, bytes] = {}

    def add(self, source: Path, member: str, *, allow_external: bool = False) -> tuple[str, int]:
        member_path = _relative(member, "archive member")
        if not member_path.parts[0] == "workspace":
            raise ValueError("payload files must be rooted below workspace/")
        source = source.absolute()
        if source.is_symlink():
            raise ValueError("transfer source cannot be a symbolic link")
        resolved = source.resolve(strict=True)
        if not allow_external and not resolved.is_relative_to(self.workspace):
            raise ValueError("transfer source escapes the selected workspace")
        digest, size = _sha_size(resolved)
        name = member_path.as_posix()
        prior = self.files.get(name)
        entry = (resolved, digest, size)
        if prior is not None and prior != entry:
            raise ValueError(f"duplicate archive member: {name}")
        self.files[name] = entry
        return digest, size

    def add_generated(self, member: str, payload: bytes) -> None:
        name = _relative(member, "archive member").as_posix()
        if not name.startswith("workspace/"):
            raise ValueError("payload files must be rooted below workspace/")
        self.files[name] = (self.workspace, "__generated__" + hashlib.sha256(payload).hexdigest(), len(payload))
        self.generated[name] = payload

    def add_workspace_path(self, relative: str, member: str | None = None) -> Path:
        safe = _relative(relative, "workspace path")
        source = self.workspace.joinpath(*safe.parts)
        self.add(source, member or (PurePosixPath("workspace") / safe).as_posix())
        return source


def _snapshot_root(workspace: Path, snapshot_id: str, *, study_abroad: bool) -> Path:
    base = workspace / "Work" / "StudyAbroad" / "Runs" if study_abroad else workspace / "Work" / "Runs"
    matches = list(base.glob(f"*/data/snapshots/{snapshot_id}"))
    if len(matches) != 1:
        raise ValueError(f"explicit Snapshot {snapshot_id} must resolve to one workspace directory")
    root = matches[0].resolve(strict=True)
    if not root.is_relative_to(base.resolve(strict=True)):
        raise ValueError("Snapshot directory escapes its designated run root")
    return root


def _add_snapshot(bundle: _Bundle, workspace: Path, snapshot_id: str, *, study_abroad: bool) -> tuple[Path, dict]:
    root = _snapshot_root(workspace, snapshot_id, study_abroad=study_abroad)
    manifest_path = root / "snapshot_manifest.json"
    manifest = _json(manifest_path, "Snapshot manifest")
    if (manifest.get("schema_version") != "warehouse_snapshot.v2"
            or manifest.get("snapshot_id") != snapshot_id
            or not isinstance(manifest.get("run_id"), str)
            or not RUN_ID.fullmatch(manifest["run_id"])):
        raise ValueError(f"Snapshot manifest identity is invalid: {snapshot_id}")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Snapshot manifest has no artifacts: {snapshot_id}")
    root_member = PurePosixPath(root.relative_to(workspace).as_posix())
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size_bytes"}:
            raise ValueError(f"Snapshot artifact entry is invalid: {snapshot_id}")
        relative = _relative(item["path"], "Snapshot artifact path")
        if relative.as_posix() in seen or not _SHA256.fullmatch(str(item["sha256"])):
            raise ValueError(f"Snapshot artifact identity is invalid: {snapshot_id}")
        if type(item["size_bytes"]) is not int or item["size_bytes"] < 0:
            raise ValueError(f"Snapshot artifact size is invalid: {snapshot_id}")
        seen.add(relative.as_posix())
        source = root.joinpath(*relative.parts)
        digest, size = bundle.add(source, (PurePosixPath("workspace") / root_member / relative).as_posix())
        if digest != item["sha256"] or size != item["size_bytes"]:
            raise ValueError(f"Snapshot artifact hash or size does not match: {snapshot_id}")
    digest, size = bundle.add(manifest_path, (PurePosixPath("workspace") / root_member / "snapshot_manifest.json").as_posix())
    return root, {**manifest, "_bundle_manifest_sha256": digest, "_bundle_manifest_size_bytes": size}


def _add_fee_manifest(bundle: _Bundle, workspace: Path, manifest_path: Path, *,
                      release_id: str, explicit: bool) -> str:
    manifest_path = manifest_path.resolve(strict=True)
    if not manifest_path.is_file():
        raise ValueError("advertising manifest must be a regular file")
    manifest_hash, manifest_size = _sha_size(manifest_path)
    raw = _json(manifest_path, "advertising manifest")
    if not isinstance(raw.get("sources"), list):
        raise ValueError("advertising manifest must contain sources[]")
    if explicit:
        from dashboard_product.management.candidate_sources import load_candidate_sources
        # Run the existing contract before rewriting paths for the remote workspace.
        load_candidate_sources(manifest_path)
        target_rel = PurePosixPath("Input/AdvertisingCosts/candidate-sources.json")
        asset_dir = PurePosixPath("candidate-assets")
    else:
        from dashboard_product.management.advertising_sources import load_sources
        # Validate registered inputs through the existing parser before rebasing.
        load_sources(manifest_path)
        target_rel = PurePosixPath("Input/AdvertisingCosts/sources.json")
        asset_dir = PurePosixPath("assets")

    if _sha_size(manifest_path) != (manifest_hash, manifest_size):
        raise ValueError("advertising manifest changed while validating")
    remote_root = Path(REMOTE_RELEASE_ROOT) / release_id / "foundation"

    def add_asset(path_value: Any) -> tuple[str, str]:
        if not isinstance(path_value, str) or not path_value:
            raise ValueError("advertising asset path is missing")
        candidate = Path(path_value)
        if not candidate.is_absolute():
            candidate = manifest_path.parent / candidate
        candidate = candidate.resolve(strict=True)
        digest, _ = _sha_size(candidate)
        if not _SHA256.fullmatch(digest):
            raise ValueError("advertising asset hash is invalid")
        suffix = candidate.suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            suffix = ".dat"
        filename = digest + suffix
        relative = (asset_dir / filename).as_posix()
        archive_relative = (PurePosixPath("Input/AdvertisingCosts") / relative).as_posix()
        bundle.add(candidate, (PurePosixPath("workspace") / archive_relative).as_posix(), allow_external=True)
        remote = (remote_root / archive_relative).as_posix()
        return relative, remote

    for entry in raw["sources"]:
        if not isinstance(entry, dict):
            raise ValueError("advertising source entry must be an object")
        relative, _ = add_asset(entry.get("path"))
        entry["path"] = relative
        expected = entry.get("sha256")
        actual = bundle.files[(PurePosixPath("workspace/Input/AdvertisingCosts") / relative).as_posix()][1]
        if expected is not None and str(expected).lower() != actual:
            raise ValueError(f"advertising source hash mismatch: {entry.get('source_id', 'unknown')}")
        entry["sha256"] = actual
        capture = entry.get("capture_evidence")
        if capture is not None:
            if not isinstance(capture, dict) or set(capture) != {"path", "sha256"}:
                raise ValueError("advertising capture evidence reference is invalid")
            evidence_rel, evidence_remote = add_asset(capture["path"])
            capture["path"] = evidence_remote
            if capture["sha256"] != bundle.files[(PurePosixPath("workspace/Input/AdvertisingCosts") / evidence_rel).as_posix()][1]:
                raise ValueError("advertising capture evidence hash mismatch")

    confirmation = raw.get("business_scope_confirmation")
    if confirmation is not None:
        if not isinstance(confirmation, dict):
            raise ValueError("advertising scope confirmation is invalid")
        evidence = confirmation.get("evidence")
        if evidence is not None:
            if not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}:
                raise ValueError("advertising scope evidence reference is invalid")
            evidence_rel, evidence_remote = add_asset(evidence["path"])
            evidence["path"] = evidence_remote
            if evidence["sha256"] != bundle.files[(PurePosixPath("workspace/Input/AdvertisingCosts") / evidence_rel).as_posix()][1]:
                raise ValueError("advertising scope evidence hash mismatch")

    payload = json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    # The caller writes this rewritten file directly into the TAR; it is recorded
    # in a temporary member slot until the final manifest is computed.
    bundle.add_generated((PurePosixPath("workspace") / target_rel).as_posix(), payload)
    return target_rel.as_posix()


def prepare_bundle(workspace: Path, snapshot_ids: dict[str, Any], run_id: str,
                   as_of_date: str, output_dir: Path, *, release_id: str,
                   advertising_manifest: Path | None = None) -> dict[str, Any]:
    """Create a deterministic TAR for the explicit pair and calculation closure.

    The TAR contains ``manifest.json`` and only selected Snapshot artifacts,
    workspace contracts, required study-abroad evidence, and fee inputs used by
    this calculation. It performs no network or SSH operations.
    """
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("run_id is invalid")
    if not isinstance(release_id, str) or not _SAFE_RELEASE_ID.fullmatch(release_id):
        raise ValueError("release_id is invalid")
    as_of_date = _iso_date(as_of_date)
    training_id, abroad_id = _snapshot_ids(snapshot_ids)
    workspace = Path(workspace).resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("workspace must be a directory")
    bundle = _Bundle(workspace)

    workspace_config_path = bundle.add_workspace_path("Work/workspace.json")
    workspace_config = _json(workspace_config_path, "workspace configuration")
    company_id = workspace_config.get("company_id")
    if not isinstance(company_id, str) or not company_id:
        raise ValueError("workspace company identity is missing")
    if workspace_config.get("current_snapshot_id") != training_id:
        raise ValueError("explicit training Snapshot must match the workspace pointer")

    bi_root, bi_manifest = _add_snapshot(bundle, workspace, training_id, study_abroad=False)
    abroad_root, abroad_manifest = _add_snapshot(bundle, workspace, abroad_id, study_abroad=True)
    if bi_manifest.get("run_id") != bi_root.parent.parent.parent.name:
        raise ValueError("training Snapshot run identity does not match its path")
    if abroad_manifest.get("run_id") != abroad_root.parent.parent.parent.name:
        raise ValueError("study-abroad Snapshot run identity does not match its path")

    expected_bi_warehouse = bi_root.relative_to(workspace) / "warehouse.duckdb"
    configured_bi_warehouse = _relative(workspace_config.get("current_warehouse_path", ""), "BI warehouse pointer")
    if configured_bi_warehouse.as_posix() != expected_bi_warehouse.as_posix():
        raise ValueError("workspace BI warehouse path does not match the selected Snapshot")

    for key in ("pack_path", "bridge_reference_path", "current_bridge_path"):
        value = workspace_config.get(key)
        if key == "current_bridge_path" and not value:
            continue
        if key == "bridge_reference_path" and not value:
            continue
        if key == "pack_path" and not value:
            raise ValueError("workspace pack path is missing")
        path = _relative(value, key)
        if path.parts[0:2] not in (("Work", "Pack"), ("Work", "Bridge")):
            raise ValueError(f"{key} must point to the selected Pack or Bridge")
        bundle.add_workspace_path(path.as_posix())
    # The daily receipt is the authoritative pairing and cutoff evidence.
    daily_pointer_path = bundle.add_workspace_path("Work/DailyWarehouseRefresh/current.json")
    daily_pointer = _json(daily_pointer_path, "daily warehouse pointer")
    receipt_rel = daily_pointer.get("receipt_path")
    receipt_safe = _relative(receipt_rel, "daily receipt path")
    if (len(receipt_safe.parts) != 3 or receipt_safe.parts[0] != "Runs"
            or receipt_safe.parts[2] != "receipt.json"):
        raise ValueError("daily receipt must be within Work/DailyWarehouseRefresh")
    receipt_workspace_rel = PurePosixPath("Work/DailyWarehouseRefresh") / receipt_safe
    receipt_path = bundle.add_workspace_path(receipt_workspace_rel.as_posix())
    verified_receipt = assert_daily_ready(
        workspace, as_of_date, bi_snapshot_id=training_id, study_snapshot_id=abroad_id,
    )
    if verified_receipt != _json(receipt_path, "daily warehouse receipt"):
        raise ValueError("daily pairing receipt changed while preparing transfer")

    study_pointer_path = bundle.add_workspace_path("Work/StudyAbroad/current.json")
    study_pointer = _json(study_pointer_path, "study-abroad current pointer")
    if study_pointer.get("snapshot_id") != abroad_id or study_pointer.get("company_id") != company_id:
        raise ValueError("study-abroad pointer does not match the explicit Snapshot")
    study_lineage_rel = _relative(study_pointer.get("source_lineage", ""), "study-abroad lineage path")
    study_lineage_path = bundle.add_workspace_path(study_lineage_rel.as_posix())
    study_lineage = _json(study_lineage_path, "study-abroad source lineage")
    if (study_lineage.get("snapshot_id") != abroad_id
            or study_lineage.get("run_id") != study_pointer.get("run_id")
            or study_lineage.get("company_id") != company_id):
        raise ValueError("study-abroad source lineage identity is invalid")
    normalized = study_lineage.get("normalized_history")
    if isinstance(normalized, dict) and isinstance(normalized.get("source_run_id"), str) and isinstance(normalized.get("source_snapshot_id"), str):
        # The producer host path is not a usable reference after extraction.
        normalized = dict(normalized)
        normalized["warehouse"] = (
            Path(REMOTE_RELEASE_ROOT) / release_id / "foundation" / "Work" / "StudyAbroad" / "Runs"
            / normalized["source_run_id"] / "data" / "snapshots" / normalized["source_snapshot_id"] / "warehouse.duckdb"
        ).as_posix()
        study_lineage["normalized_history"] = normalized
        payload = json.dumps(study_lineage, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
        bundle.add_generated((PurePosixPath("workspace") / study_lineage_rel).as_posix(), payload)
    study_run_root = study_lineage_path.parent
    for field in ("origin_file", "prepared_file"):
        relative = _relative(study_lineage.get(field, ""), f"study-abroad {field}")
        source = study_run_root.joinpath(*relative.parts)
        source_hash, _ = _sha_size(source)
        expected_hash = study_lineage.get("source_hashes", {}).get("source") if field == "origin_file" else None
        if field == "origin_file" and expected_hash and expected_hash != source_hash:
            raise ValueError("study-abroad origin source hash is invalid")
        bundle.add(source, (PurePosixPath("workspace") / study_lineage_rel.parent / relative).as_posix())
    roster_files = study_lineage.get("roster_files")
    if not isinstance(roster_files, dict) or set(roster_files) != {"people", "abroad_people"}:
        raise ValueError("study-abroad lineage roster closure is invalid")
    for key, relative_value in roster_files.items():
        relative = _relative(relative_value, f"study-abroad {key} roster")
        source = study_run_root.joinpath(*relative.parts)
        source_hash, _ = _sha_size(source)
        if study_lineage.get("source_hashes", {}).get(key) != source_hash:
            raise ValueError(f"study-abroad {key} roster hash is invalid")
        bundle.add(source, (PurePosixPath("workspace") / study_lineage_rel.parent / relative).as_posix())
    for item in study_lineage.get("origin_files", []) or []:
        if not isinstance(item, dict):
            raise ValueError("study-abroad origin file entry is invalid")
        relative = _relative(item.get("path", ""), "study-abroad origin file")
        source = study_run_root.joinpath(*relative.parts)
        digest, size = bundle.add(source, (PurePosixPath("workspace") / study_lineage_rel.parent / relative).as_posix())
        if item.get("sha256") != digest or ("size_bytes" in item and item["size_bytes"] != size):
            raise ValueError("study-abroad origin file hash is invalid")

    normalized = study_lineage.get("normalized_history")
    if not isinstance(normalized, dict):
        raise ValueError("study-abroad lineage lacks normalized-history evidence")
    parent_run = normalized.get("source_run_id")
    parent_snapshot = normalized.get("source_snapshot_id")
    if (not isinstance(parent_run, str) or not RUN_ID.fullmatch(parent_run)
            or not isinstance(parent_snapshot, str) or not SNAPSHOT_ID.fullmatch(parent_snapshot)
            or normalized.get("company_id") != company_id):
        raise ValueError("normalized-history identity is invalid")
    parent_run_root = workspace / "Work/StudyAbroad/Runs" / parent_run
    parent_manifest = parent_run_root / "data/snapshots" / parent_snapshot / "snapshot_manifest.json"
    parent_lineage = parent_run_root / "source_lineage.json"
    if hashlib.sha256(parent_manifest.read_bytes()).hexdigest() != normalized.get("snapshot_manifest_sha256"):
        raise ValueError("normalized-history Snapshot manifest hash is invalid")
    if hashlib.sha256(parent_lineage.read_bytes()).hexdigest() != normalized.get("source_lineage_sha256"):
        raise ValueError("normalized-history source lineage hash is invalid")
    parent_manifest_doc = _json(parent_manifest, "normalized-history Snapshot manifest")
    parent_lineage_doc = _json(parent_lineage, "normalized-history source lineage")
    if (parent_manifest_doc.get("snapshot_id") != parent_snapshot
            or parent_manifest_doc.get("run_id") != parent_run
            or parent_lineage_doc.get("snapshot_id") != parent_snapshot
            or parent_lineage_doc.get("run_id") != parent_run
            or parent_lineage_doc.get("company_id") != company_id):
        raise ValueError("normalized-history parent identity is invalid")
    bundle.add(parent_manifest, (PurePosixPath("workspace") / parent_manifest.relative_to(workspace)).as_posix())
    bundle.add(parent_manifest.parent / "warehouse.duckdb", (PurePosixPath("workspace") / parent_manifest.parent.relative_to(workspace) / "warehouse.duckdb").as_posix())
    bundle.add(parent_lineage, (PurePosixPath("workspace") / parent_lineage.relative_to(workspace)).as_posix())

    query_receipts = normalized.get("query_receipts")
    query_run_ids = normalized.get("query_run_ids")
    if (not isinstance(query_receipts, dict) or set(query_receipts) != set(HISTORY_KINDS)
            or not isinstance(query_run_ids, dict) or set(query_run_ids) != set(HISTORY_KINDS)):
        raise ValueError("normalized-history query evidence is incomplete")
    history_output = workspace / "Output/StudyAbroad/历史查询回执"
    for kind in HISTORY_KINDS:
        query_run_id = query_run_ids[kind]
        if not isinstance(query_run_id, str) or not RUN_ID.fullmatch(query_run_id):
            raise ValueError("normalized-history query run identity is invalid")
        reference = query_receipts[kind]
        response = {"schema_version": "controlled_query_result.v2", "status": "passed",
                    "snapshot_id": parent_snapshot, "run_id": query_run_id, "receipt": reference}
        read_query_result(response, output_root=history_output)
        receipt_file = resolve_file(history_output / query_run_id, reference)
        receipt = _json(receipt_file, "historical query receipt")
        if receipt.get("run_id") != query_run_id or receipt.get("snapshot_id") != parent_snapshot:
            raise ValueError("historical query receipt identity is invalid")
        bundle.add(receipt_file, (PurePosixPath("workspace/Output/StudyAbroad/历史查询回执") / query_run_id / reference["path"]).as_posix())
        for field in ("sql", "parameters", "result"):
            referenced = resolve_file(receipt_file.parent, receipt[field])
            bundle.add(referenced, (PurePosixPath("workspace/Output/StudyAbroad/历史查询回执") / query_run_id / reference["path"]).parent.joinpath(receipt[field]["path"]).as_posix())

    # Calculation references outside Snapshot data are included individually.
    bundle.add_workspace_path("Input/Reference/留学-FY26-资源表.xlsx")
    scorecard = workspace / "Input/Reference/留学板块-官方记分卡.json"
    if scorecard.is_file():
        bundle.add(scorecard, "workspace/Input/Reference/留学板块-官方记分卡.json")
    from workspace_modeling.operations.personnel import RESOURCE_FILENAME, SOURCE_DIRECTORY
    from dashboard_product.management.personnel_history import HISTORY_FILENAME
    for filename in (RESOURCE_FILENAME, HISTORY_FILENAME):
        optional = workspace / SOURCE_DIRECTORY / filename
        if optional.is_file():
            bundle.add(optional, (PurePosixPath("workspace") / SOURCE_DIRECTORY / filename).as_posix())

    selected_advertising = Path(advertising_manifest).resolve(strict=True) if advertising_manifest is not None else workspace / "Input/AdvertisingCosts/sources.json"
    advertising_rel = _add_fee_manifest(bundle, workspace, selected_advertising,
                                        release_id=release_id,
                                        explicit=advertising_manifest is not None)

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": run_id,
        "release_id": release_id,
        "company_id": company_id,
        "as_of_date": as_of_date,
        "snapshots": {"bi": training_id, "study_abroad": abroad_id},
        "files": {},
    }
    if advertising_manifest is not None:
        manifest["advertising_manifest"] = advertising_rel

    generated = bundle.generated
    for name, (source, digest, size) in sorted(bundle.files.items()):
        if name in generated:
            manifest["files"][name] = {
                "sha256": hashlib.sha256(generated[name]).hexdigest(),
                "size_bytes": len(generated[name]),
            }
        else:
            if digest.startswith("__generated__"):
                raise ValueError("generated manifest member is missing")
            manifest["files"][name] = {"sha256": digest, "size_bytes": size}

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / "payload.tar"
    fd, temporary_name = tempfile.mkstemp(prefix=".payload-", suffix=".tmp", dir=output_dir)
    os.close(fd)
    temporary = Path(temporary_name)
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    try:
        with tarfile.open(temporary, mode="w", format=tarfile.PAX_FORMAT) as out:
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest_bytes)
            info.mode = 0o600
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            out.addfile(info, fileobj=io.BytesIO(manifest_bytes))
            for name, (source, digest, size) in sorted(bundle.files.items()):
                payload = generated.get(name)
                info = tarfile.TarInfo(name)
                info.size = len(payload) if payload is not None else size
                info.mode = 0o600
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                if payload is not None:
                    out.addfile(info, fileobj=io.BytesIO(payload))
                    continue
                if info.size != size or _sha_size(source) != (digest, size):
                    raise ValueError(f"transfer source changed before archive write: {name}")
                with source.open("rb") as content:
                    out.addfile(info, fileobj=content)
                if _sha_size(source) != (digest, size):
                    raise ValueError(f"transfer source changed during archive write: {name}")
        archive_sha256, archive_size = _sha_size(temporary)
        if archive.exists():
            if archive.is_symlink() or not archive.is_file():
                raise ValueError("existing foundation bundle is not a regular file")
            if _sha_size(archive) != (archive_sha256, archive_size):
                raise ValueError("existing foundation bundle does not match the current retry inputs")
            temporary.unlink()
        else:
            os.replace(temporary, archive)
            archive_sha256, archive_size = _sha_size(archive)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"schema_version": SCHEMA_VERSION, "status": "prepared", "bundle_path": archive,
            "manifest": manifest, "sha256": archive_sha256, "size_bytes": archive_size,
            "file_count": len(manifest["files"])}
