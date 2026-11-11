"""Explicit local candidate command; has no publish/schedule/send option."""
import argparse
import json
from pathlib import Path

from .build import build_local


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--batch-id',required=True)
    parser.add_argument('--training-snapshot',required=True)
    parser.add_argument('--abroad-snapshot',required=True)
    parser.add_argument('--as-of-date',required=True)
    parser.add_argument('--source-order-receipt',dest='source_order_receipts',type=Path,action='append',required=True,
                        help='同批原始training查询receipt，可重复；只导入来源遍历血缘，不读取旧业务结果')
    parser.add_argument('--expense-baseline',type=Path,help='显式上一候选目录：只继承两张费用表')
    parser.add_argument('--advertising-manifest',type=Path,help='本次独立费用manifest；失败会记录并保留基线费用')
    args=parser.parse_args()
    result=build_local(**vars(args),config_root=Path(__file__).resolve().parents[3])
    print(json.dumps({k:result[k] for k in ('status','published','batch_id','through_date','display_label','expenses','timings')},ensure_ascii=False))


if __name__=='__main__':main()
