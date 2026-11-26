from datetime import date
import pytest
from dashboard_product.management.cutoff import VerifiedCompletion, calculation_cutoff, observed_dates, personnel_coverage

DAY = '2026-10-26'

def test_declared_dict_cannot_select_a_calculation_cutoff():
    with pytest.raises(ValueError,match='verified source completion'):
        calculation_cutoff({'orders_end':'2026-10-24','cash_end':'2026-10-24'},DAY,{'complete_through':'2026-10-25'})


@pytest.mark.parametrize('asof,observed,expected,month,start,end',[
    ('2026-10-26','2026-10-24','2026-10-25','2026-10','2026-09-26','2026-10-25'),
    ('2026-10-27','2026-10-24','2026-10-26','2026-11','2026-10-26','2026-11-25'),
    ('2027-01-01','2026-12-30','2026-12-31','2027-01','2026-12-26','2027-01-25'),
])
def test_verified_zero_day_preserves_real_personal_26_to_25_rules(asof,observed,expected,month,start,end):
    from workspace_modeling.operations.personnel import date_to_perf_month
    from dashboard_product.management.aggregate import _calendar_month_window
    coverage={'orders_start':'2025-03-01','cash_start':'2024-06-01','orders_end':observed,'cash_end':observed}
    proof=VerifiedCompletion(asof,expected,'raw-calendar','a'*64,'b'*64)
    through=calculation_cutoff(coverage,asof,proof)
    assert date_to_perf_month(through.isoformat())==month
    period={'kind':'month','id':month}
    actual_start,actual_end=_calendar_month_window(period)
    assert (actual_start.isoformat(),actual_end.isoformat())==(start,end)
    assert observed_dates(coverage)=={'orders_max_date':observed,'cash_max_date':observed}
    assert personnel_coverage(coverage,through,proof)['orders_end']==expected
    assert coverage['orders_end']==observed  # no mutation or fabricated transactions
    assert calculation_cutoff(coverage,asof).isoformat()==observed  # legacy unchanged
    assert personnel_coverage(coverage,through)['cash_end']==observed


def test_verified_proof_cannot_be_reused_for_another_asof_day():
    proof=VerifiedCompletion(DAY,'2026-10-25','raw-calendar','a'*64,'b'*64)
    with pytest.raises(ValueError):calculation_cutoff({'orders_end':'2026-10-24','cash_end':'2026-10-24'},'2026-10-27',proof)
