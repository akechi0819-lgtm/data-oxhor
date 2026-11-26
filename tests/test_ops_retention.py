import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ops.retention import retain_candidates


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.candidates = root / 'candidates'
        self.candidates.mkdir()
        self.cold = root / 'cold'
        self.now = datetime(2026, 11, 26, tzinfo=timezone.utc)

    def candidate(self, name, *, created='2026-11-01T00:00:00+00:00', day='2026-11-01'):
        path = self.candidates / name
        path.mkdir()
        return {'path': str(path), 'created_at': created, 'biz_day': day, 'verified_release_id': 'release-' + name}

    def retain(self, entries, **kwargs):
        defaults = dict(current=None, predecessor=None, in_progress=[], referenced=[])
        defaults.update(kwargs)
        return retain_candidates(self.candidates, self.cold, enrolled=entries, now=self.now, **defaults)

    def test_only_expired_unreferenced_enrolled_non_month_end_moves(self):
        entries = [self.candidate(name) for name in ('expired', 'current', 'previous', 'running', 'referenced', 'young', 'month_end')]
        entries[5]['created_at'] = '2026-11-19T00:00:00+00:00'
        entries[6]['biz_day'] = '2026-10-31'
        unregistered = self.candidate('unregistered')
        nested = Path(entries[4]['path']) / 'evidence'
        nested.mkdir()
        pointer = self.candidates.parent / 'current-link'
        pointer.symlink_to(entries[1]['path'])
        moved = self.retain(entries, current=pointer, predecessor=entries[2]['path'], in_progress=[entries[3]['path']], referenced=[nested])
        self.assertEqual(moved, [str(self.cold / 'expired')])
        self.assertTrue((self.cold / 'expired').is_dir())
        for entry in entries[1:] + [unregistered]:
            self.assertTrue(Path(entry['path']).is_dir())

    def test_invalid_enrollment_or_reference_never_moves_candidates(self):
        valid = self.candidate('valid')
        invalid = self.candidate('invalid')
        invalid['verified_release_id'] = ''
        with self.assertRaises(ValueError):
            self.retain([valid, invalid])
        self.assertTrue(Path(valid['path']).exists())
        with self.assertRaises(FileNotFoundError):
            self.retain([valid], current=self.candidates / 'missing')
        self.assertTrue(Path(valid['path']).exists())

    def test_collision_prevents_any_move(self):
        first, second = self.candidate('first'), self.candidate('second')
        self.cold.mkdir()
        (self.cold / 'second').mkdir()
        with self.assertRaises(ValueError):
            self.retain([first, second])
        self.assertTrue(Path(first['path']).exists())
        self.assertTrue(Path(second['path']).exists())


if __name__ == '__main__':
    unittest.main()
