"""Shared local receipt I/O for the daily and advertising runs."""
import hashlib
import json
from pathlib import Path


class DailyBlocked(ValueError):
    """Safe, fixed diagnostic codes only; dependency exceptions may contain secrets."""


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)
