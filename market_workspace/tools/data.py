"""Bound, read-only CLI for the local marketing workspace; no database connection here."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MARKET = Path(__file__).resolve().parents[1]
REPO = MARKET.parent
SOURCE = REPO / 'customers' / 'bi_operations'
RUN_ID = re.compile(r'run_[a-z0-9][a-z0-9_-]{2,67}')


def call(module, args):
    completed = subprocess.run(
        [sys.executable, '-m', module, *map(str, args)],
        cwd=REPO, capture_output=True, text=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{module} did not return JSON (exit {completed.returncode})') from exc
    return completed.returncode, payload


def source_file(pointer):
    if not isinstance(pointer, str) or not pointer or Path(pointer).is_absolute():
        raise ValueError('source pointer must be a workspace-relative path')
    path = (SOURCE / pointer).resolve()
    if not path.is_relative_to(SOURCE.resolve()) or not path.is_file():
        raise ValueError('source pointer must name a file within the bound data workspace')
    return path


def context():
    code, route = call('interfaces.casebook', ['guide', '--workspace', SOURCE])
    config = json.loads((SOURCE / 'Work/workspace.json').read_text(encoding='utf-8'))
    return code, route, config


def parser():
    result = argparse.ArgumentParser(description='市场工作区：绑定 bi_operations 的只读入口')
    commands = result.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='检查数据/Bridge 状态并显示实际授权路径')
    for name in ('describe', 'quality', 'query', 'saved-query', 'cases', 'verify-case'):
        command = commands.add_parser(name)
        command.add_argument('--snapshot-id', required=True)
        command.add_argument('--run-id', required=True)
        if name in ('quality', 'query', 'saved-query'):
            command.add_argument('--max-rows', type=int, default=1000)
            command.add_argument('--max-result-bytes', type=int, default=1_000_000)
        if name in ('query', 'saved-query'):
            command.add_argument('--params-json', default='null')
        if name == 'query':
            command.add_argument('--sql-file', type=Path, required=True)
        if name == 'saved-query':
            command.add_argument('--query-id', required=True)
            command.add_argument('--version', required=True)
        if name == 'cases':
            command.add_argument('--category')
        if name == 'verify-case':
            command.add_argument('--case-id', required=True)
    return result


def execute(args):
    code, route, config = context()
    if args.command == 'status':
        return code, {
            **route, 'working_role': 'marketing', 'business_port': config.get('business_port'),
            'paths': {
                'market_workspace': str(MARKET), 'data_workspace': str(SOURCE),
                'workspace_config': str(SOURCE / 'Work/workspace.json'),
                'pack': str(source_file(config['pack_path'])),
                'bridge': str(source_file(config.get('current_bridge_path') or config.get('bridge_reference_path'))),
                'evidence': str(MARKET / 'Evidence'), 'reports': str(MARKET / 'Reports'),
            },
        }
    if code or route.get('next_step') != 'analyze':
        raise ValueError(f"analysis blocked: {route.get('next_step')}; use workspace_setup")
    if args.snapshot_id != route.get('snapshot_id') or args.snapshot_id != config.get('current_snapshot_id'):
        raise ValueError('Snapshot changed or mismatched; check status and explicitly bind a new run')
    if not RUN_ID.fullmatch(args.run_id):
        raise ValueError('invalid run_id')
    warehouse = source_file(config['current_warehouse_path'])
    evidence = MARKET / 'Evidence'
    if evidence.is_symlink() or evidence.resolve() != MARKET / 'Evidence':
        raise ValueError('Evidence must be a real directory inside market_workspace')
    run = evidence / args.run_id
    sql_path = None
    if args.command == 'query':
        sql_path = args.sql_file.resolve()
        if not sql_path.is_relative_to(MARKET) or not sql_path.is_file():
            raise ValueError('SQL must be a local file within market_workspace')
    # One invocation per evidence directory: do not overwrite a previous result.
    run.mkdir(parents=True, exist_ok=False)
    if args.command in ('cases', 'verify-case'):
        command = ['case-search' if args.command == 'cases' else 'case-verify', '--workspace', SOURCE]
        if args.command == 'cases':
            command += ['--company-id', config['company_id'], '--primary-role', 'marketing']
            if args.category:
                command += ['--question-category', args.category]
        else:
            command += ['--case-id', args.case_id]
        module = 'interfaces.casebook'
    else:
        name = 'run-saved-query' if args.command == 'saved-query' else args.command
        command = [name, '--warehouse', warehouse, '--snapshot-id', args.snapshot_id]
        if args.command != 'describe':
            command += ['--run-id', args.run_id, '--output-root', evidence,
                        '--max-rows', args.max_rows, '--max-result-bytes', args.max_result_bytes]
        if args.command in ('query', 'saved-query'):
            command += ['--params-json', args.params_json]
        if sql_path:
            frozen_sql = run / 'query.sql'
            frozen_sql.write_bytes(sql_path.read_bytes())
            command += ['--sql-file', frozen_sql]
        if args.command == 'saved-query':
            registry = SOURCE / 'Work/SavedQueries'
            if not registry.resolve().is_relative_to(SOURCE.resolve()):
                raise ValueError('saved query registry escapes the bound workspace')
            command += ['--registry-root', registry, '--query-id', args.query_id, '--version', args.version]
        module = 'interfaces.data_platform'
    code, payload = call(module, command)
    if code == 0 and args.command in ('query', 'quality', 'saved-query'):
        from data_platform.query.evidence import read_query_result
        read_query_result(payload, output_root=evidence)

    receipt = {'run_id': args.run_id, 'snapshot_id': args.snapshot_id,
               'data_workspace': str(SOURCE), 'working_role': 'marketing',
               'command': args.command, 'exit_code': code, 'result': payload}
    (run / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return code, receipt


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        code, result = execute(args)
    except (OSError, ValueError, KeyError) as exc:
        code, result = 1, {'status': 'failed', 'error': str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
