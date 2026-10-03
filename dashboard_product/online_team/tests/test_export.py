import json
from pathlib import Path
import tempfile
import unittest

from dashboard_product.online_team.export import export_site, validate_public_data


class ExportTest(unittest.TestCase):
    def test_export_embeds_assets_and_escapes_data_without_copying_local_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / 'site'
            site.mkdir()
            (site / 'index.html').write_text('<!doctype html><html><head><link rel="stylesheet" href="./styles.css" /><script src="./app.js" defer></script></head><body><main></main></body></html>')
            (site / 'styles.css').write_text('body { color: black; }')
            (site / 'app.js').write_text('const el = document.querySelector("main"); el.textContent = "ready";')
            data = {'schema_version': 'dashboard_rebuild.v1', 'metadata': {'run_id': 'run_test', 'snapshot_id': 'snapshot_test', 'data_through': '2026-09-28'}, 'periods': [{'label': '</script><script>alert(1)</script>'}]}
            (site / 'data.json').write_text(json.dumps(data))
            (root / 'details.json').write_text('PRIVATE_DETAIL_NOT_FOR_WEB')
            output = root / 'online_market_special.html'
            result = export_site(site, output)
            text = output.read_text()
            self.assertEqual(result['snapshot_id'], 'snapshot_test')
            self.assertNotIn('href="./styles.css"', text)
            self.assertNotIn('src="./app.js"', text)
            self.assertNotIn('</script><script>alert(1)', text)
            self.assertNotIn('PRIVATE_DETAIL_NOT_FOR_WEB', text)
            payload = text.split('type="application/json">', 1)[1].split('</script>', 1)[0]
            self.assertEqual(json.loads(payload), data)

    def test_private_fact_columns_cannot_be_embedded(self):
        data = {'schema_version':'dashboard_rebuild.v1', 'metadata':{'run_id':'r','snapshot_id':'s','data_through':'2026-09-28'},
                'periods':[{'accidental_details':[{'student_id':'private'}]}]}
        with self.assertRaises(ValueError):
            validate_public_data(data)

    def test_changed_template_cannot_silently_export_a_broken_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'index.html').write_text('<html></html>')
            (p / 'styles.css').write_text('')
            (p / 'app.js').write_text('')
            (p / 'data.json').write_text(json.dumps({'schema_version':'dashboard_rebuild.v1', 'metadata':{'snapshot_id':'s','data_through':'2026-09-28'},'periods':[{}]}))
            with self.assertRaises(ValueError):
                export_site(p, p / 'out.html')


if __name__ == '__main__':
    unittest.main()
