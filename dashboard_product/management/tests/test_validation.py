"""Native BI aggregate privacy and identity boundary; synthetic models only."""
from copy import deepcopy
import pytest
from dashboard_product.management.validation import validate_public_data


@pytest.fixture
def model():
    return {'schema_version': 'dashboard_rebuild.v1',
            'metadata': {'run_id': 'run_fixture', 'snapshot_id': 'snapshot_fixture', 'data_through': '2026-10-25'},
            'periods': [{'id': 'FY27', 'teams': []}]}


def test_valid_aggregate_is_accepted_without_changing_it(model):
    original = deepcopy(model)
    validate_public_data(model)
    assert model == original


@pytest.mark.parametrize('field', ['run_id', 'snapshot_id', 'data_through'])
def test_missing_batch_identity_or_cutoff_is_rejected(model, field):
    model['metadata'].pop(field)
    with pytest.raises(ValueError, match='identity or cutoff'):
        validate_public_data(model)


@pytest.mark.parametrize('field', ['work_order_id', 'student_id', 'source_row_number', 'resource_description', 'query_receipts', 'details_ref'])
def test_nested_private_fact_or_evidence_never_enters_public_model(model, field):
    model['periods'][0]['teams'] = [{'nested': [{field: 'synthetic-private'}]}]
    with pytest.raises(ValueError, match='private detail or evidence'):
        validate_public_data(model)


@pytest.mark.parametrize('change', ['schema', 'empty_periods'])
def test_unsupported_or_empty_model_is_rejected(model, change):
    if change == 'schema':
        model['schema_version'] = 'unrecognized'
    else:
        model['periods'] = []
    with pytest.raises(ValueError, match='unsupported or empty'):
        validate_public_data(model)
