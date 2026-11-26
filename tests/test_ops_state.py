import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ops.state import OpsState, RunActiveError


class OpsStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = OpsState(Path(self.tmp.name))

    def test_empty_and_complete_ledger(self):
        self.assertEqual(self.state.status(), {'runs': [], 'stage_events': [], 'live_pointers': []})
        self.state.acquire('r1', 'business', '2026-11-26')
        self.state.heartbeat('r1')
        self.state.record_stage('r1', 'validate', 'passed', row_count=3, detail={'source': 'manual'})
        self.state.observe_pointer('superset_live', 'release1', '2026-11-25', verified=True)
        self.state.end('r1', 'passed', summary={'ok': True})
        result = self.state.status('2026-11-26')
        self.assertEqual(result['runs'][0]['status'], 'passed')
        self.assertEqual(result['stage_events'][0]['row_count'], 3)
        self.assertEqual(result['live_pointers'][0]['release_id'], 'release1')
        self.assertEqual(self.state.status('2026-11-25')['runs'], [])
        with self.assertRaises(ValueError):
            self.state.heartbeat('r1')

    def test_only_stale_and_dead_run_is_recovered(self):
        self.state.acquire('old', 'business', '2026-11-26', pid=12345)
        with patch('ops.state._pid_is_dead', return_value=True):
            with self.assertRaises(RunActiveError):
                self.state.acquire('new', 'business', '2026-11-26')
        with sqlite3.connect(self.state.path) as db:
            db.execute("UPDATE pipeline_runs SET heartbeat_at='2000-01-01T00:00:00+00:00' WHERE run_id='old'")
        with patch('ops.state._pid_is_dead', return_value=False):
            with self.assertRaises(RunActiveError):
                self.state.acquire('new', 'business', '2026-11-26')
        with patch('ops.state._pid_is_dead', return_value=True):
            self.state.acquire('new', 'business', '2026-11-26')
        runs = {run['run_id']: run for run in self.state.status()['runs']}
        self.assertEqual(runs['old']['status'], 'interrupted')
        self.assertEqual(runs['old']['error_code'], 'STALE_PROCESS')
        self.assertEqual(runs['new']['status'], 'running')

    def test_independent_pipelines_and_observed_pointers(self):
        self.state.acquire('r1', 'business', '2026-11-26')
        self.state.acquire('r2', 'cost', '2026-11-26')
        self.state.observe_pointer('business_bi', 'first', '2026-11-24', verified=True)
        self.state.observe_pointer('business_bi', None, None, verified=False)
        pointer = self.state.status()['live_pointers'][0]
        self.assertIsNone(pointer['release_id'])
        self.assertEqual(pointer['verified_bool'], 0)

    def test_concurrent_acquire_has_one_winner(self):
        barrier = threading.Barrier(2)
        outcomes = []

        def acquire(run_id):
            barrier.wait()
            try:
                self.state.acquire(run_id, 'business', '2026-11-26')
                outcomes.append('acquired')
            except RunActiveError:
                outcomes.append('blocked')

        threads = [threading.Thread(target=acquire, args=(f'r{i}',)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ['acquired', 'blocked'])
        self.assertEqual(len(self.state.status()['runs']), 1)


if __name__ == '__main__':
    unittest.main()
