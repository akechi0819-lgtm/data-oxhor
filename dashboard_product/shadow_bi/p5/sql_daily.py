"""Build and activate one isolated SQL warehouse for the daily dashboard."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
import re
import subprocess
from pathlib import Path
import tarfile
from typing import Callable

from data_platform.query.evidence import read_query_result, resolve_file


ROOT = Path(__file__).resolve().parents[3]
RELEASES = "/var/lib/shadow-bi/releases"
_ARCHIVE_FILES = {
    "candidate.json", "warehouse.duckdb", "notification-preview.json",
    "superset-catalogue.json", "landing-description.json", "acceptance.json",
    "release.json",
}
_MIGRATION_CHECKS = ("numbers_match", "functions_match", "interface_match")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(f"{label} missing or invalid") from None
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def load_sql_current(workspace: str | Path) -> tuple[dict, dict, Path, dict, str]:
    """Require the explicit deployed pointer and validate its fee baseline."""
    state = Path(workspace).resolve() / "Output/ShadowDaily"
    pointer_path = state / "sql-current.json"
    if not pointer_path.is_file():
        raise ValueError("SQL daily pointer is missing; complete the initial SQL migration before daily publishing")
    pointer = _read_json(pointer_path, "SQL daily pointer")
    required = ("release", "batch_id", "candidate", "coverage", "warehouse_sha256", "migration_acceptance")
    if (pointer.get("schema_version") != "sql_daily_current.v1"
            or any(pointer.get(key) is None for key in required)):
        raise ValueError("SQL daily pointer is incomplete")
    if (not isinstance(pointer["release"], str)
            or not re.fullmatch(r"daily-[A-Za-z0-9_-]{1,90}", pointer["release"])
            or not isinstance(pointer["batch_id"], str)
            or not isinstance(pointer["coverage"], dict)):
        raise ValueError("SQL daily pointer identity is invalid")
    expected_sha = pointer["warehouse_sha256"]
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("SQL daily pointer warehouse hash is invalid")

    candidate = Path(pointer["candidate"])
    if not candidate.is_absolute():
        raise ValueError("SQL daily candidate pointer must be an absolute local path")
    candidate = candidate.resolve(strict=True)
    manifest = _read_json(candidate / "candidate.json", "SQL fee baseline candidate")
    if (manifest.get("schema_version") != "sql_warehouse_candidate.v1"
            or manifest.get("batch_id") != pointer["batch_id"]
            or manifest.get("database", {}).get("sha256") != expected_sha):
        raise ValueError("SQL daily fee baseline does not match its explicit pointer")
    database = resolve_file(candidate, manifest["database"])
    if sha256_file(database) != expected_sha:
        raise ValueError("SQL daily fee baseline warehouse hash mismatch")

    acceptance_path = Path(pointer["migration_acceptance"])
    if not acceptance_path.is_absolute():
        raise ValueError("migration acceptance path must be absolute")
    acceptance_path = acceptance_path.resolve(strict=True)
    migration = _read_json(acceptance_path, "migration acceptance")
    if any(migration.get(key) is not True for key in _MIGRATION_CHECKS):
        raise ValueError("migration acceptance must retain all three passed checks")
    migration_sha = sha256_file(acceptance_path)
    pinned_acceptance_sha = pointer.get("migration_acceptance_sha256")
    if pinned_acceptance_sha is not None and pinned_acceptance_sha != migration_sha:
        raise ValueError("migration acceptance hash differs from the daily pointer")
    return pointer, manifest, candidate, migration, migration_sha


def _remote_identity_script() -> str:
    return '''set -eu
set -a
. /etc/shadow-bi.env
set +a
cd /srv/shadow-bi/code
/srv/shadow-bi/venv/bin/python - <<'PY'
import hashlib, json
from pathlib import Path

base = Path('/var/lib/shadow-bi')
current = (base / 'current').resolve(strict=True)
releases = (base / 'releases').resolve(strict=True)
if current.parent != releases:
    raise SystemExit('current release path invalid')
library = current / 'library'
release = json.loads((library / 'release.json').read_text())
candidate_path = library / 'candidate.json'
candidate = json.loads(candidate_path.read_text())
database = library / 'warehouse.duckdb'
def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()
verification_path = base / 'app' / 'sql-cutover' / current.name / 'verification.json'
verification = json.loads(verification_path.read_text()) if verification_path.is_file() else None
catalogue = library / 'superset-catalogue.json'
print(json.dumps({
    'release': current.name,
    'release_id': release.get('release_id'),
    'release_candidate_sha256': release.get('candidate_sha256'),
    'candidate_sha256': sha(candidate_path),
    'batch_id': release.get('batch_id'),
    'candidate_batch_id': candidate.get('batch_id'),
    'snapshots': release.get('snapshots'),
    'candidate_snapshots': candidate.get('snapshots'),
    'as_of_date': release.get('as_of_date'),
    'candidate_as_of_date': candidate.get('as_of_date'),
    'through_date': release.get('coverage', {}).get('data_through'),
    'candidate_through_date': candidate.get('through_date'),
    'coverage': release.get('coverage'),
    'warehouse_sha256': sha(database),
    'manifest_warehouse_sha256': release.get('database_sha256'),
    'candidate_warehouse_sha256': candidate.get('database', {}).get('sha256'),
    'catalogue_sha256': sha(catalogue),
    'verification': verification,
}, ensure_ascii=False))
PY
'''


def remote_current(*, ssh: list[str], ssh_env: dict, log: Path,
                   command_result: Callable) -> dict:
    result = command_result(ssh + ["bash -s"], log, input=_remote_identity_script(),
                            text=True, env=ssh_env)
    if result.get("release") != result.get("release_id"):
        raise ValueError("remote SQL current release identity is invalid")
    if (result.get("batch_id") != result.get("candidate_batch_id")
            or result.get("candidate_sha256") != result.get("release_candidate_sha256")
            or result.get("snapshots") != result.get("candidate_snapshots")
            or result.get("as_of_date") != result.get("candidate_as_of_date")
            or result.get("through_date") != result.get("candidate_through_date")
            or result.get("warehouse_sha256") != result.get("manifest_warehouse_sha256")
            or result.get("warehouse_sha256") != result.get("candidate_warehouse_sha256")):
        raise ValueError("remote SQL current database identity or hash is invalid")
    verified = result.get("verification")
    if (not isinstance(verified, dict) or verified.get("status") != "passed"
            or verified.get("metrics_compared") != 18):
        raise ValueError("remote SQL current has no passed activation verification")
    return result


def verify_current_pointer(*, workspace: str | Path, ssh: list[str], ssh_env: dict,
                           log: Path, command_result: Callable) -> tuple[dict, dict, dict, Path, dict, str]:
    pointer, manifest, candidate, migration, migration_sha = load_sql_current(workspace)
    current = remote_current(ssh=ssh, ssh_env=ssh_env, log=log,
                             command_result=command_result)
    if (pointer["release"] != current["release"]
            or pointer["batch_id"] != current["batch_id"]
            or pointer["warehouse_sha256"] != current["warehouse_sha256"]
            or pointer["coverage"] != current["coverage"]):
        raise ValueError("local SQL daily pointer differs from remote current; refusing to guess or publish")
    return pointer, current, manifest, candidate, migration, migration_sha


def yearly_windows(start, end):
    while start < end:
        next_start = min(end, date(start.year + 1, 1, 1))
        yield start.isoformat(), next_start.isoformat()
        start = next_start


def _confirmed_adviser_lists(mapping):
    rows = mapping['mappings']
    return ([row['source_adviser'] for row in rows if row['labeled_team'] == '留学'],
            [row['source_adviser'] for row in rows if row['labeled_team'] == '留学预备'])


def source_order_receipts(*, workspace: str | Path, training_snapshot: str,
                          as_of_date: str, batch_id: str, output_root: str | Path,
                          execute_query: Callable | None = None) -> dict:
    """Create fresh controlled receipts for this batch's training traversal."""
    if execute_query is None:
        from data_platform.query.service import execute_query
    from dashboard_product.management.cutoff import calculation_cutoff
    from data_platform.query.evidence import resolve_file
    from workspace_modeling.operations.personnel import date_to_perf_month
    from dashboard_product.management.aggregate import _calendar_month_window

    workspace = Path(workspace).resolve(strict=True)
    root = Path(output_root).resolve()
    pointer = _read_json(workspace / "Work/workspace.json", "training workspace pointer")
    if pointer.get("current_snapshot_id") != training_snapshot:
        raise ValueError("training Snapshot changed before source-order receipts")
    warehouse = (workspace / pointer["current_warehouse_path"]).resolve(strict=True)
    mapping_path = ROOT / "dashboard_product/online_team/config/confirmed_team_mapping.json"
    mapping = _read_json(mapping_path, "confirmed adviser mapping")
    study_advisers, prep_advisers = _confirmed_adviser_lists(mapping)

    sql_root = ROOT / "dashboard_product/management/sql"
    coverage_response = execute_query(
        warehouse=warehouse, snapshot_id=training_snapshot,
        sql=(sql_root / "coverage.sql").read_text(encoding="utf-8"), parameters=[],
        run_id="run_sql_daily_" + hashlib.sha256((batch_id + as_of_date).encode()).hexdigest()[:20] + "_coverage",
        output_root=root, max_rows=1, max_result_bytes=50_000_000,
    )
    if coverage_response.get("status") != "passed":
        raise ValueError("controlled training coverage query failed")
    coverage_data = read_query_result(coverage_response, output_root=root)
    if len(coverage_data["rows"]) != 1:
        raise ValueError("training coverage query did not return one row")
    coverage = dict(zip(coverage_data["columns"], coverage_data["rows"][0]))
    if not all(coverage.get(key) for key in ("orders_start", "orders_end", "cash_start", "cash_end")):
        raise ValueError("training coverage dates are incomplete")
    through = calculation_cutoff(coverage, as_of_date)
    if not date(2026, 6, 1) <= through <= date(2027, 5, 31):
        raise ValueError("this dashboard covers FY27")
    start = min(date.fromisoformat(coverage[key]) for key in ("orders_start", "cash_start"))
    personal_month = date_to_perf_month(through.isoformat())
    personal_start, _ = _calendar_month_window({"kind": "month", "id": personal_month})
    attachment_start = min(through.replace(day=1), personal_start).isoformat()
    end = (through + timedelta(days=1)).isoformat()
    training_sql = (sql_root / "training_details.sql").read_text(encoding="utf-8")
    token = hashlib.sha256((batch_id + as_of_date).encode()).hexdigest()[:16]
    receipts = []
    evidence = []
    for index, (window_start, window_end) in enumerate(
            yearly_windows(start, through + timedelta(days=1))):
        response = execute_query(
            warehouse=warehouse, snapshot_id=training_snapshot,
            sql=training_sql,
            parameters=[window_start, window_end, attachment_start, study_advisers,
                        prep_advisers, ["主动", "被动"]],
            run_id=f"run_sqlord_{token}_{index}_training",
            output_root=root, max_rows=100_000, max_result_bytes=50_000_000,
        )
        if response.get("status") != "passed":
            raise ValueError("controlled training source-order query failed")
        receipt_path = resolve_file(root / response["run_id"], response["receipt"])
        receipts.append(str(receipt_path))
        evidence.append({"run_id": response["run_id"], "receipt": str(receipt_path),
                         "start_date": window_start, "end_date": window_end})
    return {"source_order_receipts": receipts, "evidence": evidence,
            "coverage": coverage, "through_date": through.isoformat(),
            "training_warehouse": str(warehouse)}


def _validate_candidate(candidate_dir: Path, *, batch_id: str,
                        training_snapshot: str, abroad_snapshot: str,
                        as_of_date: str) -> tuple[dict, Path, dict]:
    import duckdb
    from dashboard_product.shadow_bi.sql_warehouse.foundation import TABLES

    manifest = _read_json(candidate_dir / "candidate.json", "SQL daily candidate")
    if (manifest.get("schema_version") != "sql_warehouse_candidate.v1"
            or manifest.get("status") != "built_unreconciled"
            or manifest.get("published") is not False
            or manifest.get("batch_id") != batch_id
            or manifest.get("snapshots") != {"training": training_snapshot, "abroad": abroad_snapshot}
            or manifest.get("as_of_date") != as_of_date):
        raise ValueError("SQL daily candidate identity/date gate failed")
    database = resolve_file(candidate_dir, manifest.get("database", {}))
    if sha256_file(database) != manifest["database"]["sha256"]:
        raise ValueError("SQL daily candidate database hash mismatch")
    relations = manifest.get("relations")
    landing = {row["table_name"] for row in relations or [] if row.get("table_schema") == "landing"}
    expected_landing = set(TABLES["training"]) | set(TABLES["abroad"])
    if landing != expected_landing:
        raise ValueError("SQL daily candidate does not contain the five approved landing tables")
    with duckdb.connect(str(database), read_only=True) as con:
        identity = con.execute("SELECT batch_id FROM meta.identity").fetchone()
        if identity is None or identity[0] != batch_id:
            raise ValueError("SQL daily candidate warehouse identity mismatch")
        actual_landing = {row[0] for row in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='landing'").fetchall()}
        if actual_landing != expected_landing:
            raise ValueError("SQL daily candidate landing schema mismatch")
    preview_ref = manifest.get("notification_preview")
    preview_path = resolve_file(candidate_dir, preview_ref or {})
    preview = _read_json(preview_path, "SQL notification preview")
    if (preview.get("schema_version") != "management_notifications.v1"
            or preview.get("data_through") != manifest.get("through_date")
            or not isinstance(preview.get("messages"), list)
            or len(preview["messages"]) != 8):
        raise ValueError("SQL daily candidate notification preview is incomplete")
    return manifest, database, preview


def _validate_archive(path: Path, release_id: str) -> None:
    expected = {f"{release_id}/library/{name}" for name in _ARCHIVE_FILES}
    with tarfile.open(path, "r") as archive:
        members = archive.getmembers()
        files = set()
        for member in members:
            name = Path(member.name)
            if (name.is_absolute() or ".." in name.parts or not name.parts
                    or name.parts[0] != release_id or member.issym() or member.islnk()):
                raise ValueError("SQL release archive contains an unsafe path")
            if member.isfile():
                files.add(name.as_posix())
            elif not member.isdir():
                raise ValueError("SQL release archive contains a non-file member")
        if files != expected:
            raise ValueError("SQL release archive must contain exactly seven runtime files")


def publish(*, workspace: str | Path, day: str, pair: dict, run_id: str,
            release_id: str, folder: str | Path,
            advertising_manifest: str | Path | None, ssh: list[str], ssh_env: dict,
            command: Callable, command_result: Callable, before_publish: Callable | None = None,
            config_root: str | Path = ROOT, current_state: tuple | None = None,
            on_stage: Callable | None = None,
            candidate_root: str | Path | None = None, cloud_costs: dict | None = None) -> dict:
    """Receive the verified cloud build and activate it."""
    from data_platform.query.evidence import resolve_file

    workspace, folder = Path(workspace).resolve(strict=True), Path(folder).resolve()
    attempt = folder / "sql-attempts" / release_id
    attempt.mkdir(parents=True, exist_ok=False)
    sql_current_path = workspace / "Output/ShadowDaily/sql-current.json"
    if current_state is None:
        current_state = verify_current_pointer(
            workspace=workspace, ssh=ssh, ssh_env=ssh_env,
            log=attempt / "preflight-current.log", command_result=command_result)
    pointer, old_remote, baseline_manifest, baseline, migration, migration_sha = current_state
    training_snapshot = pair["sources"]["bi"]["snapshot_id"]
    abroad_snapshot = pair["sources"]["study_abroad"]["snapshot_id"]
    if not training_snapshot or not abroad_snapshot:
        raise ValueError("explicit source Snapshot pair is incomplete")
    if before_publish is not None:
        before_publish()
    if on_stage is not None:
        on_stage("build", "running")
    candidates = Path(candidate_root) if candidate_root is not None else Path(config_root) / ".local/sql-daily/candidates"
    candidate_dir = candidates.resolve() / release_id
    if cloud_costs is not None:
        from dashboard_product.shadow_bi.p5.cloud_foundation import prepare_remote_costs
        remote = prepare_remote_costs(
            workspace=workspace, day=day, pair=pair, run_id=run_id,
            release_id=release_id, attempt=attempt, candidate_dir=candidate_dir,
            ssh=ssh, ssh_env=ssh_env, command=command, command_result=command_result,
            current_state=current_state, costs=cloud_costs,
        )
        source = remote["source"]
    else:
        from dashboard_product.shadow_bi.p5.cloud_foundation import prepare_remote_business
        remote = prepare_remote_business(
            workspace=workspace, day=day, pair=pair, run_id=run_id,
            release_id=release_id, attempt=attempt, candidate_dir=candidate_dir,
            ssh=ssh, ssh_env=ssh_env, command=command, command_result=command_result,
            current_state=current_state, advertising_manifest=advertising_manifest,
        )
        source = remote["source"]
    candidate, database, preview = _validate_candidate(
        candidate_dir, batch_id=run_id, training_snapshot=training_snapshot,
        abroad_snapshot=abroad_snapshot, as_of_date=day)
    if remote["candidate"] != candidate:
        raise ValueError("retrieved cloud candidate differs from the staging receipt")
    from dashboard_product.shadow_bi.p5.release_guard import compare_releases

    comparison = compare_releases(
        baseline=resolve_file(baseline, baseline_manifest["database"]),
        candidate=database,
        baseline_through=old_remote["through_date"],
        candidate_through=candidate["through_date"],
    )
    _atomic_json(attempt / "release-comparison.json", comparison)
    if comparison["blocks"]:
        raise ValueError("SQL release comparison blocked: " + ", ".join(comparison["blocks"]))
    if on_stage is not None:
        on_stage("build", "passed", {"data_through": candidate["through_date"],
                                    "artifact_sha256": candidate["database"]["sha256"]})
        on_stage("publish", "running")
    if before_publish is not None:
        before_publish()

    # 日常数据更新沿用已验收目录；经重新验收的产品改动可显式更新该封口合同。
    accepted_catalogue_sha = migration["catalogue_sha256"]
    library = Path(remote["local_release_root"]).resolve(strict=True) / "library"
    from dashboard_product.shadow_bi.p4.sql_release import load_release
    sealed_release, sealed_candidate, sealed_database = load_release(library)
    if (sealed_release.get("release_id") != release_id
            or sealed_candidate != candidate
            or sealed_database != library / "warehouse.duckdb"):
        raise ValueError("sealed SQL release identity or database is invalid")
    release_manifest = _read_json(library / "release.json", "SQL release manifest")
    if remote["release_manifest"] != release_manifest:
        raise ValueError("retrieved cloud release differs from the staging receipt")
    catalogue_path = resolve_file(library, release_manifest["superset_catalogue"])
    catalogue_sha = sha256_file(catalogue_path)
    if catalogue_sha != accepted_catalogue_sha:
        raise ValueError("static SQL dataset and option contract changed; repeat migration acceptance before publishing")
    prepared = remote["prepared"]
    if (prepared.get("status") != "prepared" or prepared.get("release") != release_id
            or prepared.get("batch_id") != run_id
            or prepared.get("warehouse_sha256") != candidate["database"]["sha256"]):
        raise ValueError("remote SQL candidate preparation receipt is invalid")
    if before_publish is not None:
        before_publish()

    activation_script = f'''set -eu
set -a
. /etc/shadow-bi.env
set +a
cd /srv/shadow-bi/code
/srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.sql_release \
    {RELEASES}/{release_id} --expected-current {pointer["release"]}
'''
    activation_error = None
    try:
        activated = command_result(ssh + ["bash -s"], attempt / "activate.log",
                                  input=activation_script, text=True, env=ssh_env)
    except Exception as error:
        activation_error = error
        activated = None
    activation_receipt_valid = (
        isinstance(activated, dict)
        and activated.get("status") == "activated"
        and activated.get("current") == release_id
        and activated.get("batch_id") == run_id
        and isinstance(activated.get("verification"), dict)
        and activated["verification"].get("status") == "passed"
        and activated["verification"].get("metrics_compared") == 18
    )
    if not activation_receipt_valid:
        # SSH may lose or corrupt the acknowledgement after an atomic activation.
        # Confirm the explicit target and its 18-metric verification before deciding.
        current = remote_current(ssh=ssh, ssh_env=ssh_env,
                                 log=attempt / "activation-recheck.log",
                                 command_result=command_result)
        if (current["release"] == pointer["release"]
                and current["batch_id"] == pointer["batch_id"]
                and current["warehouse_sha256"] == pointer["warehouse_sha256"]):
            raise RuntimeError("SQL activation failed; the previous verified current remains active") from activation_error
        if (current["release"] != release_id or current["batch_id"] != run_id
                or current["warehouse_sha256"] != candidate["database"]["sha256"]):
            raise RuntimeError("SQL activation outcome is not confirmed; do not retry blindly") from activation_error
        activated = {"status": "activated", "current": release_id, "batch_id": run_id,
                     "verification": current["verification"], "recovered_acknowledgement": True}
    current = remote_current(ssh=ssh, ssh_env=ssh_env,
                             log=attempt / "activation-current.log",
                             command_result=command_result)
    if (current["release"] != release_id or current["batch_id"] != run_id
            or current["warehouse_sha256"] != candidate["database"]["sha256"]
            or current["catalogue_sha256"] != catalogue_sha
            or current["coverage"] != release_manifest["coverage"]):
        raise ValueError("remote SQL current changed after activation")

    new_pointer = {
        "schema_version": "sql_daily_current.v1",
        "release": release_id,
        "batch_id": run_id,
        "candidate": str(candidate_dir.resolve()),
        "local_release_root": str(library.parent),
        "release_manifest_sha256": sha256_file(library / "release.json"),
        "coverage": release_manifest["coverage"],
        "warehouse_sha256": candidate["database"]["sha256"],
        "migration_acceptance": str(Path(pointer["migration_acceptance"]).resolve()),
        "migration_acceptance_sha256": migration_sha,
        "superset_catalogue_sha256": catalogue_sha,
    }
    _atomic_json(sql_current_path, new_pointer)
    if on_stage is not None:
        on_stage("publish", "passed", {"release": release_id, "candidate": str(candidate_dir),
                    "predecessor": str(baseline.resolve()), "biz_day": day,
                    "data_through": candidate["through_date"],
                    "artifact_sha256": candidate["database"]["sha256"]})
    retirement_script = f'''set -eu
set -a
. /etc/shadow-bi.env
set +a
cd /srv/shadow-bi/code
/srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.sql_release \\
    {RELEASES}/{release_id} --retire-previous {pointer["release"]}
'''
    try:
        retention = command_result(ssh + ["bash -s"], attempt / "retirement.log",
                                   input=retirement_script, text=True, env=ssh_env)
        if retention.get('status') != 'retired' or retention.get('removed') != pointer['release']:
            raise ValueError('SQL retirement receipt is invalid')
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        # 业务已实际发布；维护回执未知应单独显式报告，不能阻断业务通知。
        retention = {'status': 'unconfirmed', 'error_type': type(error).__name__,
                     'evidence': str(attempt / 'retirement.log')}
    return {
        "status": "published", "day": day, "release": release_id,
        "predecessor_candidate": str(baseline.resolve()),

        "batch_id": run_id, "sources": pair,
        "candidate": str(candidate_dir.resolve()),
        "warehouse_sha256": candidate["database"]["sha256"],
        "coverage": release_manifest["coverage"],
        "expenses": candidate.get("expenses"),
        "source_order_receipts": source["source_order_receipts"],
        "sql_activation": activated,
        "server_retention": retention,
        "migration_acceptance_sha256": migration_sha,
        "completed_at": datetime.now().astimezone().isoformat(),
    }


def _atomic_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)
