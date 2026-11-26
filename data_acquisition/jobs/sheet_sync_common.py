"""Pure helpers shared by Tencent sheet synchronization jobs."""
from __future__ import annotations


def map_columns(required_headers: list[str], remote_headers: list[object]) -> dict[str, int]:
    """Locate known columns by name; reject ambiguous or missing required headers."""
    result = {}
    for header in required_headers:
        matches = [index for index, value in enumerate(remote_headers) if value == header]
        if len(matches) != 1:
            raise ValueError("remote_header_mismatch")
        result[header] = matches[0]
    return result


def readback_matches(cells: dict[tuple[int, int], object],
                     expected: dict[tuple[int, int], object]) -> bool:
    """Compare the requested cells, treating the two empty representations alike."""
    for coordinate, value in expected.items():
        actual = cells.get(coordinate)
        if actual != value and not (actual in (None, "") and value in (None, "")):
            return False
    return True


def batch_values(*, columns: list[str], column_map: dict[str, int],
                 records: list[list[object]], row_numbers: list[int],
                 id_field: str, manual_fields: frozenset[str],
                 before: dict[tuple[int, int], object], remote_width: int
                 ) -> tuple[dict[tuple[int, int], object], dict[tuple[int, int], object], dict[tuple[int, int], object]]:
    """Partition a batch into source cells, commit keys, and protected cells."""
    writable = {column_map[header] for header in columns if header not in manual_fields}
    protected = {(row, col): before.get((row, col))
                 for row in row_numbers for col in range(remote_width) if col not in writable}
    source, keys = {}, {}
    for row, record in zip(row_numbers, records):
        for header, value in zip(columns, record):
            if header in manual_fields:
                continue
            target = keys if header == id_field else source
            target[(row, column_map[header])] = value
    return source, keys, protected


def commit_with_readback(write, read, source, keys, protected):
    """Verify source and protected values before and after publishing commit keys."""
    if source:
        write(source)
    if not readback_matches(read(), {**protected, **source}):
        raise ValueError('source_readback_mismatch')
    if keys:
        write(keys)
        if not readback_matches(read(), {**protected, **source, **keys}):
            raise ValueError('commit_readback_mismatch')
