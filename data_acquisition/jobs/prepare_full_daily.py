"""Run the scheduled business publish entry through ops."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path

from data_acquisition.ops_io import DailyBlocked
from ops.business import SHANGHAI


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--batch-dir', type=Path, required=True)
    parser.add_argument('--publish', action='store_true', required=True)
    parser.add_argument('--business-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--refresh-business', action='store_true')
    parser.add_argument('--orders-start-date')
    parser.add_argument('--orders-end-date')
    parser.add_argument('--business-inputs', type=Path)
    args = parser.parse_args(argv)
    if bool(args.orders_start_date) != bool(args.orders_end_date):
        parser.error('order recovery requires both dates')
    if args.business_inputs and not args.refresh_business:
        parser.error('--business-inputs requires --refresh-business')
    from ops.pipeline import run_business

    runtime = Path(os.environ.get('COWH_OPS_RUNTIME', Path(__file__).resolve().parents[2] / 'runtime'))
    try:
        result = run_business(args.workspace.resolve(), runtime.resolve(),
                              day=datetime.now(SHANGHAI).date().isoformat(), batch_dir=args.batch_dir,
                              business_inputs=args.business_inputs, force_refresh=args.refresh_business,
                              orders_start_date=args.orders_start_date, orders_end_date=args.orders_end_date)
    except DailyBlocked as error:
        result = {'status': 'blocked', 'reason': str(error)}
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result.get('status') in {'blocked', 'failed', 'partial'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
