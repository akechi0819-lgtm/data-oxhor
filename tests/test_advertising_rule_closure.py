import unittest
from pathlib import Path
from dashboard_product.shadow_bi.library import code_files as library_rules
from dashboard_product.shadow_bi.p5.full_daily import code_files as daily_rules
class AdvertisingRuleClosureTests(unittest.TestCase):
 def test_native_advertising_parser_and_authority_rules_are_frozen_by_both_paths(self):
  root=Path(__file__).resolve().parents[1]
  expected=[root/'dashboard_product/management/tencent_sources.py',root/'dashboard_product/management/candidate_sources.py',root/'data_acquisition/connectors/advertising/tencent_native.py',root/'data_acquisition/connectors/advertising/ocean_requests.py']
  for actual in [set(library_rules()),set(daily_rules(root))]:
   for path in expected:self.assertIn(path,actual)
