"""Validate the aggregate BI model without exposing private facts or query evidence."""

def validate_public_data(data):
    if data.get('schema_version') != 'dashboard_rebuild.v1' or not data.get('periods'):
        raise ValueError('unsupported or empty dashboard data')
    metadata = data.get('metadata', {})
    if not all(metadata.get(k) for k in ('snapshot_id', 'data_through', 'run_id')):
        raise ValueError('dashboard data has no explicit identity or cutoff')
    forbidden = {'work_order_id', 'student_id', 'source_row_number', 'resource_description', 'query_receipts', 'details_ref'}
    def visit(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError('private detail or evidence fields cannot be published')
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(data)
