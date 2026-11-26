"""Single local command for business operations."""
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys

from dashboard_product.shadow_bi.p5.full_daily import DailyBlocked
from data_acquisition.jobs.business_first_daily import SHANGHAI
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
    fetch = commands.add_parser('fetch-cost-optional')
    fetch.add_argument('--batch-dir', type=Path, required=True)
    fetch.add_argument('--source-contracts', type=Path, required=True)
    fetch.add_argument('--xhs-scope', type=Path, required=True)
    sem = fetch.add_mutually_exclusive_group()
    sem.add_argument('--sem-receipt', type=Path)
    sem.add_argument('--sem-auto', action='store_true')
    fetch.add_argument('--sem-executable-path', type=Path)
    fetch.add_argument('--tencent-scope-confirmation', type=Path)
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
    print(f'腾讯表 投流 {content.get("status") or pointer("sync_content")} '
          f'{content.get("error", "")}　点评 {pointer("sync_dianping")}　初三 {pointer("sync_grade9")}')
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
        elif args.command == 'ingest-cost':
            result = ingest_costs(workspace, runtime, day=_today(), input_path=args.input,
                                  platform=args.platform, confirmed_zero=args.confirm_zero)
        else:
            from data_acquisition.jobs.prepare_full_daily import collector

            day = _today()
            acquire = collector(args.batch_dir, args.source_contracts, args.xhs_scope, args.sem_receipt,
                                sem_auto=args.sem_auto, sem_executable_path=args.sem_executable_path,
                                tencent_confirmation=args.tencent_scope_confirmation)
            capture = args.batch_dir / 'capture'
            capture.mkdir(parents=True, exist_ok=True)
            result = acquire(workspace, day, 'optional-fee-' + day, capture)
        notice = result.get('notification') or {}
        if notice.get('reason') == 'already_sent_today':
            print('notify: skipped (already_sent_today)', file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 2 if result.get('status') in {'blocked', 'failed', 'partial'} else 0
    except (OSError, ValueError, DailyBlocked, RunActiveError) as error:
        print(f'ops: {error}', file=sys.stderr)
        return 2
