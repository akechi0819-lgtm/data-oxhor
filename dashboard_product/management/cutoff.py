"""Separate observed transaction dates from a reviewed source completion cutoff."""
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class VerifiedCompletion:
    # Internal value produced by the protected evidence reader, never HTTP JSON.
    as_of_date: str
    complete_through: str
    batch_id: str
    archive_sha256: str
    approval_sha256: str

    def metadata(self):
        return {'status': 'verified', 'scope': 'bi_orders_and_cash',
                'complete_through': self.complete_through, 'batch_id': self.batch_id,
                'archive_sha256': self.archive_sha256, 'approval_sha256': self.approval_sha256}


def calculation_cutoff(coverage, as_of, completion=None):
    """Legacy calls retain their cutoff; verified zero-row days need no fake facts."""
    observed = min(date.fromisoformat(coverage[k]) for k in ('orders_end', 'cash_end'))
    yesterday = date.fromisoformat(as_of) - timedelta(days=1)
    if completion is None:
        return min(observed, yesterday)
    if (not isinstance(completion, VerifiedCompletion) or completion.as_of_date != as_of
            or completion.complete_through != yesterday.isoformat()):
        raise ValueError('verified source completion must match the calculation day')
    return yesterday


def observed_dates(coverage):
    return {'orders_max_date': coverage['orders_end'], 'cash_max_date': coverage['cash_end']}


def personnel_coverage(coverage, through, completion=None):
    """Keep observed maxima intact; pass calculation coverage to capacity rules."""
    if completion is not None:
        calculation_cutoff(coverage, completion.as_of_date, completion)
        if through.isoformat() != completion.complete_through:
            raise ValueError('personnel cutoff differs from verified completion')
    return {**coverage, **{key: through.isoformat() if completion is not None
                          else min(coverage[key], through.isoformat())
                          for key in ('orders_end', 'cash_end')}}
