"""Retire superseded notification bundles without changing delivery records."""
from contextlib import ExitStack
from datetime import date
import fcntl
import json
from pathlib import Path
import re
import shutil

from monitoring_product import release_notifications, shared_delivery
from monitoring_product.notification_job_reconcile import read_receipt
from monitoring_product.receiver_notify_worker import read_request
from dashboard_product.shadow_bi.p5 import notification_contract


def retire_obsolete_bundles(*, warehouse=Path('/var/lib/shadow-bi'),
                            home=Path('/var/lib/shadow-bi-notify'),
                            entry_lock=Path('/run/shadow-bi-notify-entry.lock'),
                            dispatch_lock=Path('/run/shadow-bi-notify-dispatch.lock')):
    """Remove superseded generated bundles after confirmed sends or old previews.

    Caller must hold the warehouse publication lock and have verified the active
    SQL release. Nonblocking notification locks keep pending and in-flight work
    stable while the delivery ledger and job states are inspected.
    """
    try:
        return _retire_obsolete_bundles(warehouse=warehouse, home=home,
                                        entry_lock=entry_lock, dispatch_lock=dispatch_lock)
    except BlockingIOError:
        return {'status': 'skipped', 'reason': 'notification_busy', 'removed': []}


def _retire_obsolete_bundles(*, warehouse, home, entry_lock, dispatch_lock):
    warehouse, home = Path(warehouse), Path(home)
    bundle_root = home/'bundles'
    if bundle_root.is_symlink():
        raise ValueError('notification bundle directory is invalid')
    if not bundle_root.exists() or (bundle_root.is_dir() and not any(bundle_root.iterdir())):
        return {'status': 'passed', 'current': (warehouse/'current').resolve(strict=True).name,
                'removed': [], 'retained': []}
    queue = warehouse/'receiver'
    control = warehouse/'notify-control'
    state_dir = home/'state'
    locks = (Path(dispatch_lock), Path(entry_lock), home/'.run.lock',
             queue/'.notify.lock', state_dir/shared_delivery.LOCK_FILENAME)
    with ExitStack() as stack:
        for index, path in enumerate(locks):
            if path.is_symlink():
                raise ValueError('notification lock cannot be a symlink')
            # Both /run locks are created by root-owned entry scripts on demand.
            lock = stack.enter_context(path.open('a+b' if index < 2 else 'r+b'))
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        releases = warehouse/'releases'
        current = (warehouse/'current').resolve(strict=True)
        if current.parent != releases.resolve(strict=True):
            raise ValueError('current release is outside the release directory')
        protected = {path.name for path in releases.iterdir()}
        for name in ('current', 'previous', 'next'):
            link = warehouse/name
            if link.is_symlink():
                target = link.resolve(strict=True)
                if target.parent != releases.resolve(strict=True):
                    raise ValueError('active release is outside the release directory')
                protected.add(target.name)
        state = release_notifications.require_imported_state(state_dir)
        ledger = state['deliveries']
        if not isinstance(ledger, dict):
            raise ValueError('invalid notification delivery ledger')
        current_manifest = json.loads((current/'library/release.json').read_bytes())
        current_day = date.fromisoformat(current_manifest['as_of_date'])

        pending = queue/'notify-pending'
        for marker in pending.iterdir() if pending.exists() else ():
            if not notification_contract.JOB.fullmatch(marker.name):
                raise ValueError('invalid pending notification identity')
            request = read_request(queue/'notify-requests', marker.name+'.json')
            if notification_contract.job_id(request) != marker.name:
                raise ValueError('notification request identity mismatch')
            protected.add(request['expected_release'])

        for result_path in (control/'results').glob('*.json'):
            if result_path.is_symlink() or not notification_contract.JOB.fullmatch(result_path.stem):
                raise ValueError('invalid notification job result')
            raw = result_path.read_bytes()
            result = json.loads(raw)
            if result.get('status') not in {'running', 'unknown', 'partial'} and not result.get('retryable'):
                continue
            name = result.get('expected_release') or result.get('release_id')
            if not isinstance(name, str) or not notification_contract.RELEASE.fullmatch(name):
                request = read_request(queue/'notify-requests', result_path.name)
                if notification_contract.job_id(request) != result_path.stem:
                    raise ValueError('notification request identity mismatch')
                name = request['expected_release']
            if result.get('status') == 'unknown' and (control/'reconciliations'/result_path.name).exists():
                receipt = read_receipt(control, result_path.stem, raw)
                if receipt.get('release_id') == name and receipt.get('as_of_date') == result.get('as_of_date'):
                    continue
            protected.add(name)

        if bundle_root.is_symlink() or not bundle_root.is_dir():
            raise ValueError('notification bundle directory is invalid')
        removed, retained = [], []
        for bundle in sorted(bundle_root.iterdir()):
            manifest = bundle/'bundle.json'
            if bundle.is_symlink() or not bundle.is_dir() or manifest.is_symlink() or not manifest.is_file():
                retained.append(bundle.name)
                continue
            try:
                payload = json.loads(manifest.read_bytes())
                expected_files = {'bundle.json', 'shared_result.json', 'notifications.json'}
                if (set(path.name for path in bundle.iterdir()) != expected_files
                        or any(path.is_symlink() or not path.is_file() for path in bundle.iterdir())
                        or payload.get('source_mode') != 'sql_warehouse'):
                    raise ValueError('unrecognized bundle footprint')
                for key, expected in (('shared_result', 'shared_result.json'),
                                      ('notifications', 'notifications.json')):
                    reference = payload[key]
                    if reference['path'] != expected:
                        raise ValueError('invalid bundle reference')
                    release_notifications._bound_file(bundle, reference)
                source = payload['source']
                release, day = source['release_id'], source['as_of_date']
                if (payload['schema_version'] != release_notifications.SCHEMA
                        or not isinstance(release, str) or not notification_contract.RELEASE.fullmatch(release)
                        or not re.fullmatch(re.escape(release)+r'-[0-9a-f]{16}', bundle.name)
                        or not isinstance(day, str) or date.fromisoformat(day).isoformat() != day):
                    raise ValueError('invalid bundle identity')
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                retained.append(bundle.name)
                continue
            if release in protected:
                retained.append(bundle.name)
                continue
            keys = [shared_delivery._message_key(day, channel, message)
                    for message, channel in shared_delivery.EXPECTED_MESSAGES.items()]
            day_rows = [row for key, row in ledger.items() if key.startswith(day+'|')]
            sent = all(isinstance(ledger.get(key), dict) and ledger[key].get('status') == 'sent' for key in keys)
            historical_preview = not day_rows and date.fromisoformat(day) < current_day
            if not (sent or historical_preview) or any(not isinstance(row, dict) or row.get('status') != 'sent'
                                                       for row in day_rows):
                retained.append(bundle.name)
                continue
            shutil.rmtree(bundle)
            removed.append(bundle.name)
        return {'status': 'passed', 'current': current.name, 'removed': removed, 'retained': retained}
