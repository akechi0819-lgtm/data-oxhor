"""Download Tencent Excel and replace explicit months using normalized history."""
from __future__ import annotations

import argparse
import json
import shutil
from types import SimpleNamespace
from data_platform.connectors.xlsx import sha256_file
from pathlib import Path

from data_acquisition.connectors.tencent_docs.export import download_tencent_doc_xlsx
from data_acquisition.jobs.build_study_abroad_warehouse import build
from interfaces.data_platform import RUN_ID


def update(*, workspace: Path, run_id: str, snapshot_id: str, through_date: str,
           refresh_months: list[str],
           source_file: Path | None = None) -> dict:
    workspace = workspace.resolve()
    if not RUN_ID.fullmatch(run_id):
        raise ValueError('run_id无效')
    if not refresh_months:
        raise ValueError('必须明确刷新月份')
    pointer = json.loads((workspace / 'Work/StudyAbroad/current.json').read_text(encoding='utf-8'))
    downloads = workspace / 'Work/StudyAbroad/Downloads' / run_id
    if downloads.exists():
        raise ValueError('该下载run已使用，请提供新的run_id')
    if source_file is None:
        config = json.loads((workspace / '.private/tencent-source.json').read_text(encoding='utf-8'))
        captured = download_tencent_doc_xlsx(
            file_id=config['file_id'], token_file=Path(config['token_file']), output_dir=downloads,
        )
    else:
        downloads.mkdir(parents=True)
        target = downloads / source_file.name
        shutil.copyfile(source_file, target)
        captured = SimpleNamespace(path=target, sha256=sha256_file(target), size_bytes=target.stat().st_size)
    result = build(workspace=workspace, source_file=captured.path, run_id=run_id,
                   snapshot_id=snapshot_id, through_date=through_date,
                   refresh_months=refresh_months, history_snapshot_id=pointer['snapshot_id'])
    result['capture'] = {'path': str(captured.path), 'sha256': captured.sha256,
                         'size_bytes': captured.size_bytes,
                         'method': 'mcp' if source_file is None else 'local_input'}
    if source_file is None:
        result['capture']['task_id'] = captured.task_id
    (downloads / 'capture_receipt.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='腾讯文档下载及留学仓月份刷新，不重读历史旧格式')
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--snapshot-id', required=True)
    parser.add_argument('--through-date', required=True)
    parser.add_argument('--refresh-month', dest='refresh_months', action='append', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps({'status': 'passed', **update(**vars(args))}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
