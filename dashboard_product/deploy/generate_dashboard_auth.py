#!/usr/bin/env python3
"""Maintain the C-layer htpasswd consumed by the native BI account verifier.

Passwords are read from the xlsx password book (mode 600). They are never
printed. Do not commit deploy/secrets/. Do not upload initial-passwords to
the web root.
"""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_PASSWORD_BOOK = Path(__file__).resolve().parent / 'secrets' / 'password-book-20260907.xlsx'
REQUIRED_COLUMNS = ('用户名', '密码', '权限')


def _apr1_hash(password: str) -> str:
    proc = subprocess.run(
        ['openssl', 'passwd', '-apr1', '-stdin'],
        input=password + '\n',
        capture_output=True,
        text=True,
        check=True,
    )
    hashed = proc.stdout.strip()
    if not hashed.startswith('$apr1$'):
        raise RuntimeError('openssl passwd did not return an apr1 hash')
    return hashed


def _write_private(path: Path, body: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(body)
            if not body.endswith('\n'):
                handle.write('\n')
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _cell_str(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


def load_password_book(path: Path) -> list[dict]:
    try:
        import openpyxl
    except ImportError as exc:
        raise SystemExit(
            'openpyxl is required to read the password book; '
            'use the warehouse venv (export PATH=/home/box/oxhor/warehouse/.venv/bin:$PATH)'
        ) from exc
    if not path.is_file():
        raise SystemExit(f'password book not found: {path}')
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(workbook.active.iter_rows(values_only=True))
    finally:
        workbook.close()
    if not rows:
        raise SystemExit('password book is empty')
    header = [_cell_str(cell) for cell in rows[0]]
    missing = [name for name in REQUIRED_COLUMNS if name not in header]
    if missing:
        raise SystemExit('password book missing columns: ' + ', '.join(missing))
    index = {name: header.index(name) for name in REQUIRED_COLUMNS}
    accounts = []
    seen = set()
    for row_number, row in enumerate(rows[1:], start=2):
        cells = list(row or ())

        def column(name: str) -> str:
            position = index[name]
            return _cell_str(cells[position] if position < len(cells) else None)

        username = column('用户名')
        password = column('密码')
        permission = column('权限')
        if not username and not password and not permission:
            continue
        if not username or not password or not permission:
            raise SystemExit(f'password book row {row_number} is incomplete')
        if username in seen:
            raise SystemExit(f'duplicate username in password book: {username}')
        seen.add(username)
        accounts.append(
            {'username': username, 'password': password, 'permission': 'all'}
        )
    if not accounts:
        raise SystemExit('password book has no accounts')
    return accounts


def generate(
    dest: Path,
    force: bool = False,
    password_book: Path | None = None,
    write_initial_passwords: bool = False,
) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    password_book = Path(password_book) if password_book is not None else DEFAULT_PASSWORD_BOOK
    paths = {
        'htpasswd': dest / 'htpasswd',
        'passwords': dest / 'initial-passwords',
    }
    existing = [path for path in (paths['htpasswd'],) if path.exists()]
    if existing and not force:
        names = ', '.join(path.name for path in existing)
        raise SystemExit(f'secrets already exist ({names}); pass --force to rotate')

    accounts = load_password_book(password_book)
    htpasswd_lines = []
    password_lines = [
        '# dashboard passwords copied from the password book. mode 600.',
        '# do not commit, do not upload, do not paste into chat.',
        f'# generated_at={datetime.now(timezone.utc).isoformat()}',
        '# columns: username<TAB>permission<TAB>password',
        '',
    ]
    public_rows = []
    for account in accounts:
        hashed = _apr1_hash(account['password'])
        public_rows.append(
            {
                'username': account['username'],
                'permission': 'all',
                'permission': account['permission'],
            }
        )
        htpasswd_lines.append(f"{account['username']}:{hashed}")
        password_lines.append(f"{account['username']}\tall\t{account['password']}")

    _write_private(paths['htpasswd'], '\n'.join(htpasswd_lines) + '\n')
    if write_initial_passwords:
        _write_private(paths['passwords'], '\n'.join(password_lines) + '\n')
    elif paths['passwords'].exists():
        paths['passwords'].unlink()

    written = ['htpasswd']
    if write_initial_passwords:
        written.append('initial-passwords')
    return {
        'status': 'generated',
        'directory': str(dest),
        'password_book': str(password_book),
        'accounts': public_rows,
        'files': {key: str(path) for key, path in paths.items() if key != 'passwords' or write_initial_passwords},
        'written': written,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--dest',
        type=Path,
        default=Path(__file__).resolve().parent / 'secrets',
        help='C-layer directory (default: deploy/secrets)',
    )
    parser.add_argument(
        '--password-book',
        type=Path,
        default=DEFAULT_PASSWORD_BOOK,
        help='xlsx password book with columns 用户名 / 密码 / 权限',
    )
    parser.add_argument('--force', action='store_true', help='replace existing htpasswd and map')
    parser.add_argument(
        '--write-initial-passwords',
        action='store_true',
        help='also write a local plaintext TSV (mode 600); off by default',
    )
    args = parser.parse_args()
    result = generate(
        args.dest,
        force=args.force,
        password_book=args.password_book,
        write_initial_passwords=args.write_initial_passwords,
    )
    # Print paths and usernames only — never passwords.
    usernames = ', '.join(item['username'] for item in result['accounts'])
    sys.stdout.write(
        f"wrote {', '.join(result['written'])} (mode 600) under {result['directory']}\n"
        f"password book: {result['password_book']}\n"
        f'usernames: {usernames}\n'
        'effective permission: all\n'
        'passwords are not printed\n'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
