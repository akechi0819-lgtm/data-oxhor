"""Independent daily SQL warehouse build and single-warehouse activation."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[3]


class FeeRefreshFailed(RuntimeError):
    """The new business warehouse is active, but this batch's fee refresh failed."""


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def command(args, log, **kwargs):
    return_output = kwargs.pop('return_output', False)
    if return_output:
        with Path(log).open('a') as output:
            result = subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, check=False, **kwargs)
            captured = result.stdout
            if isinstance(captured, bytes):
                captured = captured.decode(errors='replace')
            output.write(captured or '')
            if result.returncode:
                raise subprocess.CalledProcessError(result.returncode, args, output=captured)
            return captured
    with Path(log).open('a') as output:
        subprocess.run(args, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                       check=True, **kwargs)


def command_result(args, log, **kwargs):
    """Run one JSON-producing command and return its final JSON line."""
    output = command(args, log, return_output=True, **kwargs)
    try:
        result = json.loads(output.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        raise ValueError('SQL release command receipt is missing') from None
    if not isinstance(result, dict):
        raise ValueError('SQL release command receipt is invalid')
    return result


def ssh_config(private):
    ssh = ['ssh', '-o', 'NumberOfPasswordPrompts=1', '-o', 'PreferredAuthentications=password',
           '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=20',
           '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
           'root@38.76.161.233']
    env = dict(os.environ, SSH_ASKPASS=str(Path(__file__).with_name('ssh_askpass.sh')),
               SSH_ASKPASS_REQUIRE='force', DISPLAY='shadow-bi-p5',
               SHADOW_SSH_PASSWORD_FILE=str(Path(private) / 'server-password'))
    return ssh, env


def package_tables(source, presentation, destination):
    """Keep the existing full-daily preview package utility for its caller."""
    manifest = json.loads((Path(presentation) / 'library_manifest.json').read_text())
    source, presentation, destination = map(Path, (source, presentation, destination))
    destination.mkdir()
    for spec in manifest['tables'].values():
        relative = Path(spec['data']['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('封存表路径无效')
        file = presentation / relative
        if not file.exists():
            file = source / relative
        if hashlib.sha256(file.read_bytes()).hexdigest() != spec['data']['sha256']:
            raise ValueError('封存表摘要不符')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
    write(destination / 'library_manifest.json', manifest)
    return manifest


@contextmanager
def production_lock(state, held=None):
    """Reuse a full-daily lock only when its open descriptor is this lock inode."""
    state = Path(state)
    path = state / '.lock'
    if held is None:
        with path.open('a') as owned:
            fcntl.flock(owned, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield owned
    else:
        if held.closed or Path(held.name).resolve() != path.resolve():
            raise ValueError('共享日更锁身份不符')
        stat, actual = os.fstat(held.fileno()), path.stat()
        if (stat.st_dev, stat.st_ino) != (actual.st_dev, actual.st_ino):
            raise ValueError('共享日更锁文件已改变')
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield held


def _release_id(day, run_id, stamp):
    import hashlib
    suffix = hashlib.sha256(f'{day}:{run_id}:{stamp}'.encode()).hexdigest()[:10]
    return f'daily-sql-{day.replace("-", "")}-{stamp}-{suffix}'


def _fee_refresh_expected(workspace, advertising_manifest):
    path = (Path(advertising_manifest) if advertising_manifest is not None else
            Path(workspace) / 'Input/AdvertisingCosts/sources.json')
    try:
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return True
    if not isinstance(manifest, dict) or not isinstance(manifest.get('sources'), list):
        return True
    return bool(manifest['sources'])


def run(workspace, day, resume=None, publish_prepared=False, *, held_lock=None,
        prepared_sources=None, run_id_override=None, before_publish=None,
        advertising_manifest=None, force_refresh=False, bi_start_date=None,
        input_paths=None, orders_start_date=None, orders_end_date=None):
    from data_acquisition.jobs.daily_warehouses import refresh_daily, assert_daily_ready
    from . import sql_daily

    private = Path(workspace).resolve() / '.private'
    workspace = Path(workspace).resolve()
    if day != datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat():
        raise ValueError('日更只采集上海当天；历史回放不计连续日更')
    state = workspace / 'Output/ShadowDaily'
    state.mkdir(parents=True, exist_ok=True)
    if prepared_sources is not None and (resume or publish_prepared):
        raise ValueError('完整日更已备来源与旧续跑模式不可混用')
    if input_paths is not None:
        if bi_start_date is None:
            raise ValueError('显式BI来源必须指定bi_start_date')
        if not force_refresh:
            raise ValueError('显式来源必须使用force_refresh')
        if resume or publish_prepared or prepared_sources is not None:
            raise ValueError('显式来源不可与续跑或已准备来源混用')
    if run_id_override is not None and prepared_sources is None:
        raise ValueError('指定新批次必须提供已校验来源')

    with production_lock(state, held_lock):
        completed = state / (day + '.json')
        previous = json.loads(completed.read_text()) if completed.is_file() else None
        if previous and previous.get('day') != day:
            raise ValueError('日更回执日期不符')
        if resume:
            folder = state / resume
            report = json.loads((folder / 'result.json').read_text())
            if report.get('day') != day or report.get('status') != 'failed' or 'sources' not in report:
                raise ValueError('仅续跑同日已完成双仓采集的失败批次')
            run_id = resume
        else:
            stamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%H%M%S')
            prepared = prepared_sources if prepared_sources is not None else (
                assert_daily_ready(workspace, day) if publish_prepared else None)
            run_id = (run_id_override or (prepared['run_id'] if prepared else None)
                      or 'run_shadow_daily_' + day.replace('-', '') + '_' + stamp)
            if (not run_id.startswith('run_shadow_daily_' + day.replace('-', '') + '_')
                    or not run_id.replace('_', '').isalnum()):
                raise ValueError('日更批次身份无效')
            folder = state / run_id
            report = {'day': day, 'run_id': run_id,
                      'started_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
        try:
            ssh, ssh_env = ssh_config(private)
            # Read the explicit prior deployment before acquiring another batch.
            # There is deliberately no latest-release fallback.
            current_state = sql_daily.verify_current_pointer(
                workspace=workspace, ssh=ssh, ssh_env=ssh_env,
                log=state / ('sql-current-preflight-' + run_id + '.log'),
                command_result=command_result)
            pointer = current_state[0]
            if (previous and previous.get('status') == 'published'
                    and not (prepared_sources is not None or publish_prepared or resume or force_refresh)):
                if previous.get('release') != pointer['release']:
                    raise ValueError('当天日更回执与显式SQL current不一致')
                return previous

            if not resume:
                folder.mkdir()
            report['status'] = 'running'
            write(folder / 'result.json', report)

            if not resume and not publish_prepared and prepared_sources is None:
                refresh_kwargs = {}
                if bi_start_date is not None:
                    refresh_kwargs['bi_start_date'] = bi_start_date
                if input_paths is not None:
                    refresh_kwargs['input_paths'] = input_paths
                if orders_start_date is not None:
                    refresh_kwargs.update(orders_start_date=orders_start_date,
                                          orders_end_date=orders_end_date)
                captured = refresh_daily(
                    workspace=workspace, as_of_date=day, run_id=run_id,
                    bi_snapshot_id='snapshot_bi_operations_' + run_id.removeprefix('run_shadow_daily_'),
                    study_snapshot_id='snapshot_study_abroad_' + run_id.removeprefix('run_shadow_daily_'),
                    **refresh_kwargs)
                if captured.get('status') != 'passed':
                    raise RuntimeError('双仓采集未同时成功；保留当前SQL版本，需检查来源回执')
            pair = assert_daily_ready(workspace, day)
            if prepared_sources is not None and pair != prepared_sources:
                raise ValueError('完整日更双仓身份已改变')
            if resume and pair != report.get('sources'):
                raise ValueError('续跑时双仓身份已改变，拒绝混用批次')
            report['sources'] = pair
            if publish_prepared:
                report['reused_capture'] = True
                report['repair_of'] = pair.get('repair_of')
            if before_publish is not None:
                before_publish()

            stamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%H%M%S%f')
            release_id = _release_id(day, run_id, stamp)
            publication = sql_daily.publish(
                workspace=workspace, day=day, pair=pair, run_id=run_id,
                release_id=release_id, folder=folder,
                advertising_manifest=advertising_manifest, ssh=ssh, ssh_env=ssh_env,
                command=command, command_result=command_result,
                before_publish=before_publish, config_root=ROOT,
                current_state=current_state)
            if publication.get('status') != 'published' or publication.get('release') != release_id:
                raise ValueError('SQL warehouse publication was not confirmed')
            report.update(publication)
            report.pop('error_type', None)
            report.pop('action', None)
            report['completed_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
            write(completed, report)
            fee_refresh = publication.get('expenses') or {}
            if (_fee_refresh_expected(workspace, advertising_manifest)
                    and fee_refresh.get('status') == 'failed'):
                report['fee_refresh_failure'] = {
                    'status': 'failed', 'error_type': fee_refresh.get('error_type'),
                    'retained_rows': fee_refresh.get('retained_rows'),
                }
                write(completed, report)
                raise FeeRefreshFailed('SQL business release is active; fee refresh failed and prior fees were retained')
        except FeeRefreshFailed:
            # Business is already activated and the explicit fee failure is recorded.
            raise
        except Exception as error:
            # Exception text may contain source paths or SSH details; persist only its class.
            if not folder.exists():
                folder.mkdir()
            report.update(status='failed', error_type=type(error).__name__,
                          action='检查本批来源、SQL构建和发布回执；未确认发布的批次不计入连续日更')
            raise
        finally:
            if folder.exists():
                write(folder / 'result.json', report)
                if report.get('status') == 'published':
                    write(state / 'current.json', report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--date', default=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
    parser.add_argument('--resume', help='续跑同日已完成双仓的失败SQL发布批次，不重复采集')
    parser.add_argument('--publish-prepared', action='store_true',
                        help='发布已通过联合回执校验的新批次，不重新采集；同日修复仍只计一天')
    args = parser.parse_args()
    result = run(args.workspace.resolve(), args.date, args.resume, args.publish_prepared)
    print(json.dumps({'status': result['status'], 'day': result['day'],
                      'release': result.get('release')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
