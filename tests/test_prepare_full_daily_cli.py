import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch

from data_acquisition.jobs.prepare_full_daily import main


class PrepareFullDailyCliTests(unittest.TestCase):
    def args(self, *extra):
        return [
            '--workspace', '/tmp/workspace',
            '--batch-dir', '/tmp/batch',
            '--source-contracts', '/tmp/contracts',
            '--xhs-scope', '/tmp/xhs-scope.json',
            '--sem-auto',
            *extra,
        ]

    def test_default_mode_is_isolated_prepare(self):
        run = Mock(return_value={'status': 'prepared', 'published': False})
        self.assertEqual(main(self.args(), run_fn=run), 0)
        self.assertTrue(run.call_args.kwargs['prepare'])
        self.assertEqual(run.call_args.args[0], Path('/tmp/workspace').resolve())

    def test_publish_flag_selects_existing_gated_publish_path(self):
        run = Mock(return_value={'status': 'published', 'published': True})
        self.assertEqual(main(self.args('--publish'), run_fn=run), 0)
        self.assertFalse(run.call_args.kwargs['prepare'])

    def test_formal_publish_delegates_to_ops_without_a_fee_collector(self):
        with patch('ops.pipeline.run_business', return_value={'status': 'complete'}) as business:
            with patch('data_acquisition.jobs.prepare_full_daily.collector') as collector:
                self.assertEqual(main(self.args('--publish')), 0)
        collector.assert_not_called()
        self.assertEqual(business.call_args.kwargs['batch_dir'], Path('/tmp/batch'))
        self.assertNotIn('collect', business.call_args.kwargs)

    def test_explicit_prepare_flag_keeps_preview_mode(self):
        run = Mock(return_value={'status': 'prepared', 'published': False})
        self.assertEqual(main(self.args('--prepare'), run_fn=run), 0)
        self.assertTrue(run.call_args.kwargs['prepare'])

    def test_prepare_and_publish_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            main(self.args('--prepare', '--publish'), run_fn=Mock())

    def test_unconfirmed_publish_exception_does_not_claim_no_business_publication(self):
        with patch('builtins.print') as printed:
            code = main(self.args('--publish'), run_fn=Mock(side_effect=RuntimeError('private detail')))
        result = json.loads(printed.call_args.args[0])
        self.assertEqual(code, 1)
        self.assertNotIn('published', result)
        self.assertEqual(result['pipeline_report'], '/tmp/batch/pipeline-result.json')
        self.assertNotIn('private detail', str(result))


if __name__ == '__main__':
    unittest.main()
