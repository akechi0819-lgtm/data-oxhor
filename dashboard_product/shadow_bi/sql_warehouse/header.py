"""用户只看到三个日期；费用日期不承担完整性门禁。"""
from datetime import date
from dashboard_product.shadow_bi.p35.coverage_note import coverage_note as _native_coverage_note


def update_date_label(dates):
    def label(value):
        if value is None:return '未更新'
        day=value if isinstance(value,date) else date.fromisoformat(str(value)[:10])
        return f'{day.month}.{day.day}'
    return '｜'.join((f"留学 {label(dates['abroad_through'])}",
                     f"语培 {label(dates['training_through'])}",
                     f"费用 {label(dates['expense_through'])}"))


def coverage_note(dates):
    """Add the expense through-date to the existing dashboard coverage note."""
    original = _native_coverage_note({
        'data_through': str(dates['training_through'])[:10],
        'study_abroad_source': {'through_date': str(dates['abroad_through'])[:10]},
    })
    expense_through = dates.get('expense_through')
    fee_note = (f' · 费用截至 {str(expense_through)[:10]}'
                if expense_through is not None else ' · 费用未更新')
    return original.replace(' · 金额单位：元', fee_note + ' · 金额单位：元', 1)
