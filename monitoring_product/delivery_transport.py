"""Small transport-only primitives for shared-result notification delivery.

This module has no warehouse, business-rule, roster, or query dependencies.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request


DEFAULT_ORIGIN = 'http://dashboard.apinova.cn'
ALLOWED_CHANNELS = frozenset({
    'offline_youth', 'offline_high_school', 'offline_university',
    'online_private', 'online_platform',
})
UPLOAD_ATTEMPTS_DEFAULT = 8
UPLOAD_BACKOFF_SECONDS = (10, 20, 30, 45, 60, 60, 60)
SECRET_KEY_HINTS = ('PASSWORD', 'SECRET', 'WEBHOOK', 'TOKEN', 'KEY')
TOKEN_PATTERN = re.compile(r'^[0-9a-f]{32}$')


class UploadStepError(RuntimeError):
    def __init__(self, message, returncode=None):
        super().__init__(message)
        self.returncode = returncode


def webhook_env_name(channel_id: str) -> str:
    return f'DINGTALK_WEBHOOK_{channel_id.upper()}'


def secret_env_name(channel_id: str) -> str:
    return f'DINGTALK_SECRET_{channel_id.upper()}'


def public_urls(origin: str, token: str, channel_id: str) -> tuple[str, str]:
    base = f'{origin.rstrip("/")}/notify/{token}/{channel_id}'
    return f'{base}/people.png', f'{base}/details.xlsx'


def load_env_file(path: str | Path) -> None:
    """Load simple KEY=VALUE entries without overriding existing environment."""
    for raw in Path(path).read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())


def _secret_values(env_file: str | Path | None = None) -> set[str]:
    values = {
        value for key, value in os.environ.items()
        if any(hint in key.upper() for hint in SECRET_KEY_HINTS) and value and len(value) >= 4
    }
    if env_file:
        try:
            for raw in Path(env_file).read_text(encoding='utf-8').splitlines():
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                value = value.strip().strip('"').strip("'")
                if any(hint in key.upper() for hint in SECRET_KEY_HINTS) and len(value) >= 4:
                    values.add(value)
        except OSError:
            pass
    return values


def redact_secrets(text: object, env_file: str | Path | None = None,
                   limit: int = 1500) -> str:
    """Remove credential values from diagnostics and keep only the tail."""
    result = str(text or '').replace('\r', '')
    for value in sorted(_secret_values(env_file), key=len, reverse=True):
        result = result.replace(value, '<redacted>')
    result = '\n'.join(line for line in result.splitlines() if line.strip())
    return result[-limit:]


def signed_webhook(url: str, secret: str = '') -> str:
    if not secret:
        return url
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f'{timestamp}\n{secret}'.encode('utf-8')
    digest = hmac.new(secret.encode('utf-8'), string_to_sign, digestmod=hashlib.sha256).digest()
    signature = urllib.parse.quote_plus(base64.b64encode(digest))
    joiner = '&' if '?' in url else '?'
    return f'{url}{joiner}timestamp={timestamp}&sign={signature}'


def post_dingtalk(webhook: str, secret: str, title: str, text: str) -> dict:
    """Post one Markdown message; only an explicit errcode 0 confirms delivery."""
    url = signed_webhook(webhook, secret)
    payload = json.dumps({
        'msgtype': 'markdown',
        'markdown': {'title': title, 'text': text},
    }, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        url, data=payload,
        headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST',
    )
    import ssl
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=20, context=context) as response:
        body = json.loads(response.read().decode('utf-8'))
    if not isinstance(body, dict) or type(body.get('errcode')) is not int or body['errcode'] != 0:
        error = body.get('errmsg') if isinstance(body, dict) else None
        raise ValueError(f'dingtalk did not confirm success: {error or body}')
    return {'status': 'sent'}


def run_password_command(command: list[str], env_file: str | Path | None = None,
                         timeout: int = 180) -> None:
    """Run one existing SSH/SCP argv with pexpect and the configured password."""
    if (not isinstance(command, list) or not command
            or command[0] not in {'/usr/bin/ssh', '/usr/bin/scp'}
            or any(not isinstance(argument, str) for argument in command)):
        raise ValueError('password command must be an argv list for /usr/bin/ssh or /usr/bin/scp')
    if env_file:
        load_env_file(env_file)
    password = os.environ.get('SERVER_PASSWORD')
    if not password:
        raise ValueError('missing SERVER_PASSWORD')

    import pexpect
    child = pexpect.spawn(command[0], command[1:], env=os.environ.copy(),
                          encoding='utf-8', timeout=timeout)
    transcript = []
    while True:
        index = child.expect([r'(?i)assword:', pexpect.EOF, pexpect.TIMEOUT])
        transcript.append(child.before or '')
        if index == 0:
            child.sendline(password)
            continue
        if index == 1:
            child.close()
            if child.exitstatus != 0:
                diagnostic = redact_secrets(''.join(transcript), env_file) or '<empty>'
                raise UploadStepError(
                    f'upload step failed status={child.exitstatus}: {command[0]}; output: {diagnostic}',
                    returncode=child.exitstatus,
                )
            return
        child.close(force=True)
        diagnostic = redact_secrets(''.join(transcript), env_file) or '<empty>'
        raise UploadStepError(
            f'upload timed out: {command[0]}; output: {diagnostic}', returncode=124,
        )


def _validate_stage(stage_dir: str | Path, token: str) -> Path:
    if not TOKEN_PATTERN.fullmatch(str(token)):
        raise ValueError('NOTIFY_TOKEN must be 32 lowercase hex characters')
    if Path(stage_dir).is_symlink():
        raise ValueError('stage dir must not be a symlink')
    stage = Path(stage_dir).resolve()
    if not stage.is_dir():
        raise ValueError(f'missing stage dir {stage}')
    found: dict[str, set[str]] = {}
    for path in stage.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'refusing to upload symlink {path.relative_to(stage).as_posix()}')
        if path.is_dir():
            relative = path.relative_to(stage)
            if len(relative.parts) != 1 or relative.parts[0] not in ALLOWED_CHANNELS:
                raise ValueError(f'refusing to upload directory {relative.as_posix()}')
            continue
        relative = path.relative_to(stage)
        if (len(relative.parts) != 2 or relative.parts[0] not in ALLOWED_CHANNELS
                or relative.name not in {'people.png', 'details.xlsx'}):
            raise ValueError(f'refusing to upload {relative.as_posix()}')
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'empty upload asset {relative.as_posix()}')
        found.setdefault(relative.parts[0], set()).add(relative.name)
    if not found:
        raise ValueError('stage has no notify files')
    if any(names != {'people.png', 'details.xlsx'} for names in found.values()):
        raise ValueError('each channel upload must contain people.png and details.xlsx')
    return stage


def _upload_notify_assets_pexpect(stage_dir: str | Path, token: str,
                                  env_file: str | Path | None = None) -> str:
    """Use pexpect directly, so upload works without the optional expect binary."""
    stage = _validate_stage(stage_dir, token)
    if env_file:
        load_env_file(env_file)
    host = os.environ['SERVER_HOST']
    port = os.environ.get('SERVER_PORT', '22')
    user = os.environ['SERVER_USER']
    remote_tmp = f'/tmp/dashboard-notify-{token}'
    ssh_options = [
        '-o', 'StrictHostKeyChecking=yes',
        '-o', 'PreferredAuthentications=password',
        '-o', 'PubkeyAuthentication=no',
        '-o', 'GSSAPIAuthentication=no',
    ]

    run_password_command(
        ['/usr/bin/ssh', *ssh_options, '-p', str(port), f'{user}@{host}',
         f'mkdir -p {remote_tmp} && chmod 700 {remote_tmp}'],
        env_file=env_file, timeout=60,
    )
    run_password_command(
        ['/usr/bin/scp', *ssh_options, '-r', '-P', str(port),
         f'{stage}/.', f'{user}@{host}:{remote_tmp}/'],
        env_file=env_file, timeout=180,
    )
    install_command = (
        'set -euo pipefail; '
        f"src='{remote_tmp}'; dest='/var/www/dashboard/notify/{token}'; "
        'install -d -m 0755 /var/www/dashboard/notify "$dest"; '
        'for channel in offline_youth offline_high_school offline_university online_private online_platform; do '
        'if test -d "$src/$channel"; then '
        'test -s "$src/$channel/people.png"; test -s "$src/$channel/details.xlsx"; '
        'install -d -m 0755 "$dest/$channel"; '
        'install -m 0644 "$src/$channel/people.png" "$dest/$channel/people.png"; '
        'install -m 0644 "$src/$channel/details.xlsx" "$dest/$channel/details.xlsx"; '
        'fi; done; rm -rf "$src"'
    )
    run_password_command(
        ['/usr/bin/ssh', *ssh_options, '-p', str(port), f'{user}@{host}', install_command],
        env_file=env_file, timeout=60,
    )
    return f'published notify assets token={token} via=pexpect'


def upload_notify_assets(stage_dir: str | Path, token: str,
                         env_file: str | Path | None = None,
                         attempts: int | None = None, sleep=time.sleep) -> str:
    """Retry the pexpect uploader while redacting credential-bearing diagnostics."""
    _validate_stage(stage_dir, token)
    if attempts is None:
        attempts = int(os.environ.get('NOTIFY_UPLOAD_ATTEMPTS') or UPLOAD_ATTEMPTS_DEFAULT)
    attempts = max(1, attempts)
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            result = _upload_notify_assets_pexpect(stage_dir, token, env_file)
            if errors:
                result = f'{result} (attempt {attempt}; earlier failures: {len(errors)})'
            return result
        except Exception as error:  # retries are limited to asset upload, never message POSTs
            errors.append(f'attempt {attempt}: {redact_secrets(error, env_file, limit=600)}')
            if attempt < attempts:
                sleep(UPLOAD_BACKOFF_SECONDS[min(attempt - 1, len(UPLOAD_BACKOFF_SECONDS) - 1)])
    raise RuntimeError('notify asset upload failed after retries: ' + ' | '.join(errors[-4:]))
