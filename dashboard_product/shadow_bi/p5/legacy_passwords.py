"""只读原htpasswd；APR1交给系统OpenSSL，不保存或自行实现密码算法。"""
import hmac
from pathlib import Path
import re
import subprocess

APR1 = re.compile(r'\$apr1\$([./A-Za-z0-9]{1,8})\$[./A-Za-z0-9]{22}')

def read_accounts(path):
    accounts = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        name, separator, encoded = line.partition(':')
        if not separator or not name or name in accounts or not APR1.fullmatch(encoded):
            raise ValueError('原账号库格式无效或密码格式不支持')
        accounts[name] = encoded
    if not accounts:
        raise ValueError('原账号库为空')
    return accounts

def verify_password(encoded, password, executable='/usr/bin/openssl'):
    match = APR1.fullmatch(encoded)
    if not match or not isinstance(password, str) or not password or any(c in password for c in '\x00\r\n'):
        return False
    try:
        result = subprocess.run([executable, 'passwd', '-apr1', '-salt', match[1], '-stdin'],
            input=(password+'\n').encode('utf-8'), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=5, check=False)
        return result.returncode == 0 and hmac.compare_digest(result.stdout.strip(), encoded.encode('ascii'))
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False
