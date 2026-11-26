"""Single local command for business operations."""
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys

from data_acquisition.ops_io import DailyBlocked
from .business import SHANGHAI
from .pipeline import ingest_costs, run_business
from .state import OpsState, RunActiveError

ROOT = Path(__file__).resolve().parents[1]


def _today():
    return datetime.now(SHANGHAI).date().isoformat()


def _day(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('Use YYYY-MM-DD')
    return value


def _parser():
    import argparse

    parser = argparse.ArgumentParser(prog='ops', description=__doc__)
    parser.add_argument('--workspace', type=Path, default=ROOT / 'customers/shadow_bi_daily')
    parser.add_argument('--runtime', type=Path, default=Path(os.environ.get('COWH_OPS_RUNTIME', ROOT / 'runtime')))
    commands = parser.add_subparsers(dest='command', required=True)
    sheets = commands.add_parser('sync-sheets')
    sheets.add_argument('--job', choices=('all', 'content', 'dianping', 'grade9'), default='all')
    sheets.add_argument('--day', type=_day, default=_today())
    sheets.add_argument('--snapshot-id')
    rules = commands.add_parser('render-rules')
    rules.add_argument('--check', action='store_true')
    status = commands.add_parser('status')
    status.add_argument('--day', type=_day, default=_today())
    run = commands.add_parser('run')
    jobs = run.add_subparsers(dest='job', required=True)
    business = jobs.add_parser('business')
    business.add_argument('--day', type=_day, default=_today())
    business.add_argument('--from-manual', action='store_true')
    business.add_argument('--no-notify', action='store_true')
    cost = commands.add_parser('ingest-cost')
    cost.add_argument('--input', type=Path, required=True)
    cost.add_argument('--platform', choices=('xhs', 'douyin', 'tencent', 'sem'), required=True)
    cost.add_argument('--confirm-zero', action='append', default=[])
    return parser


def _selected_status(runtime: Path, day: str):
    snapshot = OpsState(runtime).status(day)
    pointers = {row['domain']: row for row in snapshot['live_pointers']}
    newest_business = next((row for row in reversed(snapshot['runs']) if row['pipeline'] == 'business' and row['summary_json']), None)
    summary = json.loads(newest_business['summary_json']) if newest_business else {}
    outcome = summary.get('notification') or {}
    business = summary.get('business') or {}
    content = (business.get('sources') or {}).get('content_work_orders') or {}
    def pointer(label):
        value = pointers.get(label)
        if not value:
            return '尚无核验记录'
        return ' '.join(str(value[key]) for key in ('release_id', 'data_through')
                        if value[key] is not None)
    print(f'经营运行 {day}（台账最近核验）')
    print(f'语培 {pointer("business_bi")}　留学 {pointer("study_abroad")}')
    print(f'Superset {pointer("superset_live")}')
    print(f'钉钉 {outcome.get("message_status_counts", outcome.get("status", "尚无核验记录"))} '
          f'{outcome.get("reason", "")}'.rstrip())
    print(f'费用 {pointer("ad_costs")}')
    def sheet_status(name, fallback=None):
        recent = next((row for row in reversed(snapshot['runs']) if row['pipeline'] == 'sync_' + name), None)
        if recent:
            result = json.loads(recent['summary_json']) if recent['summary_json'] else {}
            status = result.get('status', recent['status'])
            details = [result.get('reason', ''), *result.get('missing_headers', [])]
            return ' '.join([status, *(detail for detail in details if detail)])
        if fallback and fallback.get('status'):
            return ' '.join(filter(None, (fallback['status'], fallback.get('error', ''))))
        return pointer('sync_' + name)

    print(f'腾讯表 投流 {sheet_status("content", content)}　点评 {sheet_status("dianping")}　初三 {sheet_status("grade9")}')
    active = [row for row in snapshot['runs'] if row['status'] in ('running', 'interrupted')]
    for row in active:
        print(f'{row["pipeline"]} {row["status"]} {row["run_id"]}')


def main(argv=None):
    args = _parser().parse_args(argv)
    workspace, runtime = args.workspace.resolve(), args.runtime.resolve()
    try:
        if args.command == 'render-rules':
            from .render_rules import render
            render(ROOT, check=args.check)
            return 0
        if args.command == 'status':
            _selected_status(runtime, args.day)
            return 0
        if args.command == 'run':
            result = run_business(workspace, runtime, day=args.day,
                                  from_manual=args.from_manual, no_notify=args.no_notify)
        elif args.command == 'sync-sheets':
            from .sheets import run_sheets
            result = run_sheets(workspace, runtime, job=args.job, day=args.day, snapshot_id=args.snapshot_id)
        elif args.command == 'ingest-cost':
            result = ingest_costs(workspace, runtime, day=_today(), input_path=args.input,
                                  platform=args.platform, confirmed_zero=args.confirm_zero)
        notice = result.get('notification') or {}
        if notice.get('reason') == 'already_sent_today':
            print('notify: skipped (already_sent_today)', file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 2 if result.get('status') in {'blocked', 'failed', 'partial'} else 0
    except (OSError, ValueError, DailyBlocked, RunActiveError) as error:
        print(f'ops: {error}', file=sys.stderr)
        return 2
