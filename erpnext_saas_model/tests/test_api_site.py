from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe.tests.utils import FrappeTestCase

from erpnext_saas_model.api import site as api_site


class TestSiteApi(FrappeTestCase):
	def test_change_plan_forwards_billable_seats(self):
		site = SimpleNamespace(set_plan=Mock())

		with patch.object(api_site.frappe, "get_doc", return_value=site) as get_doc, patch.object(
			api_site, "change_press_plan"
		) as fallback:
			api_site.change_plan("SITE-001", "PLAN-001", billable_seats=4)

		get_doc.assert_called_once_with("Site", "SITE-001")
		site.set_plan.assert_called_once_with("PLAN-001", billable_seats=4)
		fallback.assert_not_called()

	def test_change_plan_falls_back_without_seats(self):
		with patch.object(api_site, "change_press_plan", return_value="ok") as fallback:
			result = api_site.change_plan("SITE-001", "PLAN-001")

		fallback.assert_called_once_with("SITE-001", "PLAN-001")
		self.assertEqual(result, "ok")
