"""Read verified Tencent native account CSVs without inferring product overlap.

Account and product identity are supplied by the host's native export evidence;
the six-column CSV itself does not encode them. This is not a fee registration.
"""
from __future__ import annotations
import csv
from datetime import date,timedelta
from decimal import Decimal,InvalidOperation
import io
from pathlib import Path

HEADERS=('日期','曝光次数','点击次数','点击率','点击均价','花费')
SCOPES={'legacy_search','display_plus'}


def read_native_rows(raw):
    try:
        table=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'),newline=''),strict=True))
    except (UnicodeError,csv.Error):
        raise ValueError('tencent_csv_invalid') from None
    if not table or tuple(table[0])!=HEADERS:
        raise ValueError('tencent_csv_headers_changed')
    rows,seen=[],set()
    for number,cells in enumerate(table[1:],2):
        if not cells or all(not c.strip() for c in cells):continue
        if len(cells)!=len(HEADERS):raise ValueError('tencent_csv_column_count')
        try:
            day=date.fromisoformat(cells[0]).isoformat()
            amount=Decimal(cells[5].replace(',',''))
            if not amount.is_finite() or amount<0:raise ValueError()
        except (ValueError,InvalidOperation):
            raise ValueError('tencent_csv_date_or_spend_invalid') from None
        if day in seen:raise ValueError('tencent_csv_duplicate_day')
        seen.add(day)
        rows.append({'date':day,'spend':str(amount),'source_row':number})
    if not rows:raise ValueError('tencent_csv_empty')
    return rows


def inspect_report(path,*,account_id,product_scope,time_basis,start_date,through_date):
    if account_id!='74749810' or product_scope not in SCOPES or time_basis!='播放口径':
        raise ValueError('tencent_scope_unverified')
    start,end=date.fromisoformat(start_date),date.fromisoformat(through_date)
    if start>end:raise ValueError('tencent_window_reversed')
    rows=read_native_rows(Path(path).read_bytes())
    if any(not start_date<=r['date']<=through_date for r in rows):
        raise ValueError('tencent_native_outside_selected_window')
    present={r['date'] for r in rows};missing=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1) if (start+timedelta(days=i)).isoformat() not in present]
    return {'account_id':account_id,'product_scope':product_scope,'time_basis':time_basis,
        'selected_window':[start_date,through_date],'actual_first_date':min(present),'actual_last_date':max(present),
        'rows':len(rows),'total':str(sum((Decimal(r['spend']) for r in rows),Decimal(0))),
        'missing_selected_dates':missing,'scope_dates_complete':not missing,'whole_account_complete':False,
        'rows_data':rows,'aggregation_performed':False,'identity_basis':'host_verified_native_export_not_embedded_in_csv',
        'registration_performed':False}
