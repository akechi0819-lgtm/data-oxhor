"""Local CLI for the context service. No server socket or MCP transport."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .service import ContextError, ProjectContextService


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ContextError('INVALID_ARGUMENT')


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description='Project Intelligence 本地只读上下文（无网络监听）')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='由本机操作者指定的项目根目录，不是模型工具参数')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('overview')
    search = commands.add_parser('search')
    search.add_argument('query')
    search.add_argument('--offset', type=int, default=0)
    search.add_argument('--limit', type=int, default=20)
    read = commands.add_parser('read')
    read.add_argument('content_id')
    read.add_argument('--start-line', type=int, default=1)
    read.add_argument('--limit', type=int, default=80)
    read.add_argument('--expected-sha256')
    workspace = commands.add_parser('workspace')
    workspace.add_argument('workspace_id')
    commands.add_parser('integrations')
    try:
        args = parser.parse_args(argv)
        service = ProjectContextService(args.root)
        if args.command == 'overview':
            result = service.get_project_overview()
        elif args.command == 'search':
            result = service.search_project(args.query, offset=args.offset, limit=args.limit)
        elif args.command == 'read':
            result = service.read_project_context(args.content_id, start_line=args.start_line,
                                                  limit=args.limit, expected_sha256=args.expected_sha256)
        elif args.command == 'workspace':
            result = service.get_workspace_metadata(args.workspace_id)
        else:
            result = service.get_integration_map()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ContextError, OSError, ValueError):
        exc = sys.exception()
        code = exc.code if isinstance(exc, ContextError) else 'CONTEXT_UNAVAILABLE'
        print(json.dumps({'schema_version': 'project_intelligence.v1', 'status': 'error',
                          'error': {'code': code}}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    # Avoid module bytecode writes in subprocess consumers; prefer python -B at startup.
    raise SystemExit(main())
