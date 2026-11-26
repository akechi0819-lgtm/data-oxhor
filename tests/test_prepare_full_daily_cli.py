from pathlib import Path
from unittest.mock import patch

import pytest

from data_acquisition.jobs.prepare_full_daily import main


ARGS = ['--workspace', '/tmp/workspace', '--batch-dir', '/tmp/batch']


def test_scheduled_publish_delegates_to_ops():
    with patch('ops.pipeline.run_business', return_value={'status': 'complete'}) as business:
        assert main([*ARGS, '--publish', '--business-only']) == 0
    assert business.call_args.kwargs['batch_dir'] == Path('/tmp/batch')
    assert 'collect' not in business.call_args.kwargs


@pytest.mark.parametrize('options', [[], ['--prepare'], ['--publish', '--orders-start-date', '2026-11-25'],
                                     ['--publish', '--business-inputs', 'inputs.json']])
def test_retired_or_incomplete_invocation_is_rejected(options):
    with pytest.raises(SystemExit) as error:
        main([*ARGS, *options])
    assert error.value.code == 2


def test_recovery_dates_reach_ops():
    with patch('ops.pipeline.run_business', return_value={'status': 'complete'}) as business:
        assert main([*ARGS, '--publish', '--orders-start-date', '2026-11-25',
                     '--orders-end-date', '2026-11-25']) == 0
    assert business.call_args.kwargs['orders_start_date'] == '2026-11-25'
    assert business.call_args.kwargs['orders_end_date'] == '2026-11-25'
