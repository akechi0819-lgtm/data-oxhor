"""Remove verified local releases that are no longer needed."""

from datetime import date, datetime
from pathlib import Path
import shutil


def retain_candidates(candidate_root, *, enrolled, current, predecessor, referenced):
    """Keep the current and previous local releases and explicitly referenced releases."""
    if Path(candidate_root).is_symlink():
        raise ValueError('candidate root cannot be a symlink')
    root = Path(candidate_root).resolve(strict=True)
    if not root.is_dir() or not isinstance(enrolled, list) or not isinstance(referenced, list):
        raise ValueError('candidate root, enrollment and references are required')

    protected = set()
    for value in (current, predecessor, *referenced):
        if value is None:
            raise ValueError('release references cannot be unknown')
        path = Path(value)
        if path.is_symlink():
            raise ValueError('release reference cannot be a symlink')
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or resolved == root:
            raise ValueError('release reference must be inside the candidate root')
        protected.add(resolved.relative_to(root).parts[0])

    eligible = []
    seen = set()
    for entry in enrolled:
        if not isinstance(entry, dict) or set(entry) != {'path', 'created_at', 'biz_day', 'verified_release_id'}:
            raise ValueError('invalid candidate enrollment schema')
        source = Path(entry['path'])
        if not source.is_absolute() or source.parent != root or source.name in seen:
            raise ValueError('candidate must be a unique direct child')
        if entry['verified_release_id'] != source.name:
            raise ValueError('candidate identity does not match enrollment')
        created = datetime.fromisoformat(entry['created_at'])
        date.fromisoformat(entry['biz_day'])
        if created.tzinfo is None:
            raise ValueError('candidate creation time must include a timezone')
        if source.is_symlink():
            raise ValueError('candidate cannot be a symlink')
        if source.exists() and not source.is_dir():
            raise ValueError('candidate must be a directory')
        if not source.exists() and source.name in protected:
            raise ValueError('protected candidate is missing')
        seen.add(source.name)
        if source.name not in protected:
            eligible.append(source)

    for source in eligible:
        if source.exists():
            shutil.rmtree(source)
    return [str(source) for source in eligible]
