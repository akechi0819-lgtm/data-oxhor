"""独立日更：既有双仓采集→业务重算→封存表→服务器验版发布。"""
import argparse
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]


def write(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    tmp.replace(path)


def command(args, log, **kwargs):
    with log.open('a') as output:
        subprocess.run(args, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                       check=True, **kwargs)


def ssh_config(private):
    ssh = ['ssh', '-o', 'NumberOfPasswordPrompts=1', '-o', 'PreferredAuthentications=password',
           '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=20',
           '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
           'root@38.76.161.233']
    env = dict(os.environ, SSH_ASKPASS=str(Path(__file__).with_name('ssh_askpass.sh')),
               SSH_ASKPASS_REQUIRE='force', DISPLAY='shadow-bi-p5',
               SHADOW_SSH_PASSWORD_FILE=str(private/'server-password'))
    return ssh, env


def package_tables(source, presentation, destination):
    """只封装manifest列明的封存JSONL，不上传客户库或查询回执。"""
    manifest = json.loads((presentation/'library_manifest.json').read_text())
    destination.mkdir()
    for spec in manifest['tables'].values():
        relative = Path(spec['data']['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('封存表路径无效')
        file = presentation/relative
        if not file.exists():
            file = source/relative
        if hashlib.sha256(file.read_bytes()).hexdigest() != spec['data']['sha256']:
            raise ValueError('封存表摘要不符')
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
    write(destination/'library_manifest.json', manifest)
    return manifest


def run(workspace, day, resume=None, publish_prepared=False):
    from data_acquisition.jobs.daily_warehouses import refresh_daily, assert_daily_ready
    import certifi
    private = workspace/'.private'
    config = json.loads((private/'tencent-source.json').read_text())
    if day != datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat():
        raise ValueError('日更只采集上海当天；历史回放不计连续日更')
    state = workspace/'Output/ShadowDaily'
    state.mkdir(parents=True, exist_ok=True)
    with (state/'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = state/(day+'.json')
        if not publish_prepared and not resume and completed.exists() and json.loads(completed.read_text()).get('status') == 'published':
            previous = json.loads(completed.read_text())
            ssh, ssh_env = ssh_config(private)
            script = '''set -eu
set -a
. /etc/shadow-bi.env
set +a
cd /srv/shadow-bi/code
/srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.activate --verify-only /var/lib/shadow-bi/current
runuser -u shadowbi --preserve-environment -- /srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p5.verify_daily --output /var/lib/shadow-bi/app/audit/p3/evidence/p5-daily-recheck.json
'''
            command(ssh+['bash -s'], state/('recheck-'+day+'.log'), input=script, text=True, env=ssh_env)
            # 实际current身份再与当天成功回执比对，不把恢复旧版误称为已更新。
            current = subprocess.run(ssh+['basename "$(readlink -f /var/lib/shadow-bi/current)"'],
                                     env=ssh_env, check=True, capture_output=True, text=True).stdout.strip()
            if current != previous['release']:
                raise ValueError('服务器当前版本与当天成功回执不同')
            return previous
        stamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%H%M%S')
        prepared = assert_daily_ready(workspace, day) if publish_prepared else None
        if publish_prepared and resume:
            raise ValueError('已准备批次发布与失败续跑不可同时指定')
        run_id = (prepared['run_id'] if prepared else resume) or 'run_shadow_daily_'+day.replace('-', '')+'_'+stamp
        if not run_id.startswith('run_shadow_daily_'+day.replace('-', '')+'_') or not run_id.replace('_', '').isalnum():
            raise ValueError('续跑批次身份无效')
        suffix = run_id.removeprefix('run_shadow_daily_')
        folder = state/run_id
        if resume:
            report = json.loads((folder/'result.json').read_text())
            if report['day'] != day or report['status'] != 'failed' or 'sources' not in report:
                raise ValueError('仅续跑同日已完成双仓采集的失败批次')
        else:
            folder.mkdir()
            report = {'day': day, 'run_id': run_id,
                      'started_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
        report['status'] = 'running'
        write(folder/'result.json', report)
        try:
            # 下层已有导出重试；失败后此入口不重复登录或伪造来源成功。
            if not resume and not publish_prepared:
                captured = refresh_daily(workspace=workspace, as_of_date=day, run_id=run_id,
                    bi_snapshot_id='snapshot_bi_operations_'+suffix,
                    study_snapshot_id='snapshot_study_abroad_'+suffix,
                    doc_id=config['doc_id'], page_url=config['page_url'],
                    cookie_file=private/'tencent-cookies.json', ca_file=Path(certifi.where()))
                if captured['status'] != 'passed':
                    raise RuntimeError('双仓采集未同时成功；保留当前服务器批次，需检查登录或来源回执')
            pair = assert_daily_ready(workspace, day)
            if resume and pair != report['sources']:
                raise ValueError('续跑时双仓身份已改变，拒绝混用批次')
            report['sources'] = pair
            if publish_prepared:
                report['reused_capture'] = True
                report['repair_of'] = pair.get('repair_of')
            base_batch = run_id+'_business'
            source = workspace/'Output/ShadowBI'/base_batch/'library'
            if not source.exists():
                command([sys.executable, '-m', 'dashboard_product.shadow_bi.library', 'build',
                     '--workspace', str(workspace), '--snapshot-id', pair['sources']['bi']['snapshot_id'],
                     '--study-abroad-snapshot-id', pair['sources']['study_abroad']['snapshot_id'],
                     '--run-id', base_batch, '--as-of-date', day], folder/'build.log')
            presentation = folder/'presentation'
            env = dict(os.environ, SHADOW_BI_SOURCE_LIBRARY=str(source),
                       SHADOW_BI_SOURCE_BATCH=base_batch, SHADOW_BI_LIBRARY=str(presentation),
                       SHADOW_BI_BATCH=run_id, SHADOW_BI_AUDIT=str(folder))
            if not presentation.exists():
                command([sys.executable, '-m', 'dashboard_product.shadow_bi.p3.build_projection'],
                        folder/'projection.log', env=env)
            from data_platform.business_library import load_library
            load_library(source, base_batch)
            manifest, _, _ = load_library(presentation, run_id)
            if not (folder/'transfer').exists():
                package_tables(source, presentation, folder/'transfer')
            archive = folder/'tables.tar.gz'
            with tarfile.open(archive, 'w:gz') as out:
                for file in sorted((folder/'transfer').rglob('*')):
                    if file.is_file():
                        out.add(file, arcname=file.relative_to(folder/'transfer'))
            ssh, ssh_env = ssh_config(private)
            release = 'daily-'+suffix+('-retry'+stamp if resume else '')
            incoming = '/var/lib/shadow-bi/incoming/'+release
            target = '/var/lib/shadow-bi/releases/'+release
            with archive.open('rb') as content:
                command(ssh+[f'umask 077; mkdir -p {incoming}; tar -xzf - -C {incoming}'],
                        folder/'transfer.log', stdin=content, env=ssh_env)
            # 调用P4既有构建、备份、验版与失败回滚，不修改旧服务任务。
            script = f'''set -eu
set -a
. /etc/shadow-bi.env
set +a
cd /srv/shadow-bi/code
old=$(readlink -f /var/lib/shadow-bi/current)
old_previous=$(readlink -f /var/lib/shadow-bi/previous)
mkdir {target}
/srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.rebuild --incoming {incoming} --target {target}/library
chown -R root:shadowbi {target}
find {target} -type d -exec chmod 750 {{}} +
find {target} -type f -exec chmod 640 {{}} +
bash dashboard_product/shadow_bi/p4/backup.sh
/srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.activate {target}
if ! runuser -u shadowbi --preserve-environment -- /srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p5.verify_daily --output /var/lib/shadow-bi/app/audit/p3/evidence/p5-daily-{suffix}.json; then
    /srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.activate "$old"
    if [ -d "$old_previous" ]; then ln -sfn "$old_previous" /var/lib/shadow-bi/previous; fi
    exit 1
fi
'''
            command(ssh+['bash -s'], folder/'publish.log', input=script, text=True, env=ssh_env)
            report.pop('error_type', None)
            report.pop('action', None)
            report.update(status='published', release=release, batch_id=manifest['batch_id'],
                          coverage=manifest['coverage'], completed_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat())
            write(completed, report)
        except Exception as error:
            # 不把依赖异常文本（可能含URL凭据）写入通用结果。
            report.update(status='failed', error_type=type(error).__name__,
                          action='检查本批来源/构建/发布日志；未成功批次不计入连续日更')
            raise
        finally:
            write(folder/'result.json', report)
            write(state/'current.json', report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--date', default=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
    parser.add_argument('--resume', help='续跑同日已完成双仓的失败发布批次，不重复采集')
    parser.add_argument('--publish-prepared', action='store_true',
                        help='发布已通过联合回执校验的新批次，不重新采集；同日修复仍只计一天')
    args = parser.parse_args()
    result = run(args.workspace.resolve(), args.date, args.resume, args.publish_prepared)
    print(json.dumps({'status': result['status'], 'day': result['day'],
                      'release': result.get('release')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
