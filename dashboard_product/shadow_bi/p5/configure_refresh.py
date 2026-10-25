"""对现有原生看板应用15分钟自动刷新，沿用P4跨批次自动重载。"""
import json
from superset.app import create_app


def main():
    app = create_app()
    with app.app_context():
        from superset import db
        from superset.models.dashboard import Dashboard
        dashboard = db.session.query(Dashboard).filter_by(slug='shadow-bi-native').one()
        metadata = json.loads(dashboard.json_metadata)
        before = dict(metadata)
        metadata['refresh_frequency'] = 900
        dashboard.json_metadata = json.dumps(metadata, ensure_ascii=False)
        db.session.commit()
        assert {k: v for k, v in before.items() if k != 'refresh_frequency'} == {
            k: v for k, v in metadata.items() if k != 'refresh_frequency'}
        print(json.dumps({'dashboard_id': dashboard.id, 'refresh_frequency_seconds': 900,
                          'other_metadata_unchanged': True}))


if __name__ == '__main__':
    main()
