"""Strict fixed notification requests; shared by receiver and privileged worker."""
from datetime import date, datetime, timedelta
import hashlib
import json
import re
from zoneinfo import ZoneInfo

RELEASE = re.compile(r"daily-[A-Za-z0-9_-]{1,96}")
JOB = re.compile(r"[0-9a-f]{64}")

class Rejected(ValueError):
    def __init__(self, reason, status=400):
        super().__init__(reason)
        self.status = status


def normalize(payload):
    if not isinstance(payload, dict) or set(payload) - {'operation','expected_release','as_of_date','retry'}:
        raise Rejected('unsupported request fields')
    if not {'operation','expected_release','as_of_date'} <= set(payload):
        raise Rejected('required request fields missing')
    if payload['operation'] not in ('preview','send-scheduled'):
        raise Rejected('unsupported fixed operation')
    if not isinstance(payload['expected_release'], str) or not RELEASE.fullmatch(payload['expected_release']):
        raise Rejected('invalid release')
    try:
        value = payload['as_of_date']
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise Rejected('invalid date') from None
    if type(payload.get('retry', False)) is not bool:
        raise Rejected('invalid retry flag')
    return {key: payload[key] for key in ('operation','expected_release','as_of_date')}


def job_id(payload):
    return hashlib.sha256(json.dumps(normalize(payload), sort_keys=True, separators=(',',':')).encode()).hexdigest()


def validate(payload, release, manifest, policy, now=None):
    item = normalize(payload)
    now = (now or datetime.now(ZoneInfo('Asia/Shanghai'))).astimezone(ZoneInfo('Asia/Shanghai'))
    if item['expected_release'] != release or item['as_of_date'] != manifest['as_of_date']:
        raise Rejected('formal release changed', 409)
    if item['as_of_date'] != now.date().isoformat():
        raise Rejected('today formal release required', 409)
    if manifest.get('coverage',{}).get('data_through') != (now.date()-timedelta(days=1)).isoformat():
        raise Rejected('yesterday complete cutoff required', 409)
    if item['operation'] == 'send-scheduled':
        if (not policy.get('imported_state_ready') or policy.get('no_backfill') is not True
                or policy.get('history_complete') is not False):
            raise Rejected('imported state and cutover proof required', 423)
        try:
            start = date.fromisoformat(policy['send_start_date'])
        except (ValueError, KeyError, TypeError):
            raise Rejected('cutover policy missing', 423) from None
        if now.date() < start:
            raise Rejected('before authorized no-backfill start', 403)
        if now.hour != 10:
            raise Rejected('outside Shanghai 10:00 hour', 403)
    return item
