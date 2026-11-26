import pytest

from data_acquisition.jobs.build_study_abroad_warehouse import (
    _apply_cash_team_confirmations, _JUNE_ORIGINS,
)


def row(**changes):
    result = dict(origin_sha256='0' * 64, origin_sheet='语培签约 (核算)',
                  origin_row_number=53, amount='6800.00', source_group='线上',
                  market_group='', owner='', segment_id='excluded',
                  team_eligible='false', market_eligible='false', personal_eligible='false',
                  ownership_mapping_source='source_owner_column')
    result.update(changes)
    return result


def test_explicit_cash_team_preserves_owner_and_existing_mappings():
    blank = row()
    historical_blank = row(market_group='线上组')
    unknown = row(owner='未知人员')
    excluded = row(owner='非市场')
    mapped = row(owner='已映射', market_group='线下组', segment_id='study_abroad_offline')
    resource = row()
    tables = {'contracts': [blank, historical_blank, unknown, excluded, mapped], 'languages': [], 'resources': [resource]}
    _apply_cash_team_confirmations(tables)
    for item in (blank, historical_blank, unknown):
        assert item['segment_id'] == 'study_abroad_online'
        assert item['market_eligible'] == item['team_eligible'] == 'true'
        assert item['personal_eligible'] == 'false'
        assert item['ownership_mapping_source'] == 'explicit_source_team_without_person_mapping'
    assert unknown['owner'] == '未知人员'
    assert excluded['segment_id'] == resource['segment_id'] == 'excluded'
    assert mapped['segment_id'] == 'study_abroad_offline'


@pytest.mark.parametrize('sha', sorted(_JUNE_ORIGINS))
def test_june_confirmed_rows_and_ssc(sha):
    contract = row(origin_sha256=sha, origin_sheet='留学签约', origin_row_number=57,
                   amount='50000', source_group='', owner='')
    language1 = row(origin_sha256=sha, origin_sheet='语培签约', origin_row_number=54,
                    amount='7000', source_group='', owner='')
    language2 = row(origin_sha256=sha, origin_sheet='语培签约', origin_row_number=55,
                    amount='6300', source_group='', owner='')
    ssc = row(origin_sha256=sha, origin_sheet='留学签约', origin_row_number=54,
              amount='13000', source_group='SSC', market_group='SSC', segment_id='ssc')
    _apply_cash_team_confirmations({'contracts': [contract, ssc], 'languages': [language1, language2]})
    assert contract['segment_id'] == 'study_abroad_offline'
    assert language1['segment_id'] == language2['segment_id'] == 'study_abroad_online'
    assert ssc['segment_id'] == 'ssc'
    assert all(x['personal_eligible'] == 'false' for x in (contract, language1, language2))
    language1['amount'] = '7001'
    with pytest.raises(ValueError, match='金额不符'):
        _apply_cash_team_confirmations({'contracts': [], 'languages': [language1]})


def test_new_team_only_cash_is_validated_before_admission():
    from data_acquisition.jobs.build_study_abroad_warehouse import normalize_sources

    raw = dict(owner='', source_group='线上组', source_row_number=2,
               date='2026-11-01', amount='100', student_id='123')
    source = dict(source_sha256='1' * 64, source_path='current.xlsx',
                  group_mapping=[], resources=[], contracts=[], languages=[raw])
    tables, _ = normalize_sources(source, {'teams': []}, {'people': []})
    assert tables['languages'][0]['market_eligible'] == 'true'
    for field, message in [('date', '缺少日期'), ('amount', '缺少金额'), ('student_id', '客户编号和姓名')]:
        invalid = {**raw, field: None}
        with pytest.raises(ValueError, match=message):
            normalize_sources({**source, 'languages': [invalid]}, {'teams': []}, {'people': []})
