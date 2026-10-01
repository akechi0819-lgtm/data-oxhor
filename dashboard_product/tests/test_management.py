"""Include isolated P2 business-rule tests in the dashboard regression suite."""
from dashboard_product.management.tests.test_aggregate import ManagementAggregateTest
from dashboard_product.management.tests.test_facts import NormalizeFactsTests

from dashboard_product.management.tests.test_breakdowns import BreakdownTests

from dashboard_product.management.tests.test_enhancements import EnhancementTests

from dashboard_product.management.tests.test_notifications import ManagementNotificationsTest
