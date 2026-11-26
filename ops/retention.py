"""Move explicitly enrolled, unreferenced release candidates to cold staging."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def retain_candidates(candidate_root, cold_root, *, enrolled, current, predecessor,
                      in_progress, referenced, now=None):
    """Stage eligible candidates only after the caller verifies release and references.

    Each enrollment is a dict with path, created_at, biz_day and verified_release_id.
    The caller must supply the current and predecessor observations explicitly;
    None means the caller verified there is no such local reference.
    """
    if Path(candidate_root).is_symlink():
        raise ValueError('candidate root cannot be a symlink')
    root = Path(candidate_root).resolve(strict=True)
    cold = Path(cold_root).absolute()
    if not root.is_dir() or cold.parent.resolve(strict=True) != root.parent or cold == root:
        raise ValueError('cold staging must be a sibling of the candidate root')
    if cold.is_symlink() or (cold.exists() and not cold.is_dir()):
        raise ValueError('invalid cold staging directory')
    if not isinstance(enrolled, list) or not isinstance(in_progress, (list, tuple, set)) or not isinstance(referenced, (list, tuple, set)):
        raise ValueError('enrollment and reference lists are required')
    if any(value is None for value in (*in_progress, *referenced)):
        raise ValueError('reference lists cannot contain unknown paths')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must include a timezone')

    def reference(value):
        path = Path(value)
        return path.resolve(strict=True)

    protected = {reference(value) for value in [current, predecessor, *in_progress, *referenced] if value is not None}
    eligible = []
    seen = set()
    for entry in enrolled:
        if not isinstance(entry, dict) or set(entry) != {'path', 'created_at', 'biz_day', 'verified_release_id'}:
            raise ValueError('invalid candidate enrollment schema')
        if not isinstance(entry['verified_release_id'], str) or not entry['verified_release_id'].strip():
            raise ValueError('verified release ID is required')
        source = Path(entry['path'])
        if source.is_symlink() or not source.is_dir():
            raise ValueError('candidate must be a real directory')
        source = source.resolve(strict=True)
        if source.parent != root or source in seen:
            raise ValueError('candidate must be a unique direct child')
        seen.add(source)
        created = datetime.fromisoformat(entry['created_at'])
        business_day = date.fromisoformat(entry['biz_day'])
        if created.tzinfo is None:
            raise ValueError('candidate creation time must include a timezone')
        month_end = business_day.day == calendar.monthrange(business_day.year, business_day.month)[1]
        is_protected = any(ref == source or ref.is_relative_to(source) for ref in protected)
        if not is_protected and not month_end and created < now - timedelta(days=7):
            destination = cold / source.name
            if destination.exists() or destination.is_symlink():
                raise ValueError('cold staging destination already exists')
            eligible.append((source, destination))
    if eligible:
        cold.mkdir(exist_ok=True)
        for source, destination in eligible:
            source.rename(destination)
    return [str(destination) for _, destination in eligible]
