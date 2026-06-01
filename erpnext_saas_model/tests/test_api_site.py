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
		site.set_plan.assert_called_once_with("PLAN-001", billable_seats=4, price_usd=None)
		fallback.assert_not_called()

	def test_change_plan_forwards_price_usd(self):
		site = SimpleNamespace(set_plan=Mock())

		with patch.object(api_site.frappe, "get_doc", return_value=site), patch.object(
			api_site, "change_press_plan"
		) as fallback:
			api_site.change_plan("SITE-001", "PLAN-001", billable_seats=4, price_usd=42)

		site.set_plan.assert_called_once_with("PLAN-001", billable_seats=4, price_usd=42)
		fallback.assert_not_called()

	def test_change_plan_falls_back_without_seats(self):
		with patch.object(api_site, "change_press_plan", return_value="ok") as fallback:
			result = api_site.change_plan("SITE-001", "PLAN-001")

		fallback.assert_called_once_with("SITE-001", "PLAN-001")
		self.assertEqual(result, "ok")

	def test_check_user_creation_eligibility_allows_within_limit(self):
		site = SimpleNamespace(name="SITE-001", subscription="SUB-001")
		plan = SimpleNamespace(
			name="PRO",
			plan_title="Pro",
			billing_type="Seat Based",
			next_plan="BUSINESS",
		)

		with patch.object(api_site, "_authenticate_billing_site", return_value=site), patch.object(
			api_site,
			"get_site_seat_limit_context",
			return_value={"plan": "PRO", "billable_seats": 4, "suggested_plan": "BUSINESS"},
		), patch.object(api_site.frappe, "get_cached_doc", return_value=plan):
			result = api_site.check_user_creation_eligibility(active_user_count=3)

		self.assertTrue(result["can_create_user"])
		self.assertEqual(result["reason"], "WITHIN_LIMIT")
		self.assertEqual(result["billable_seats"], 4)
		self.assertEqual(result["active_user_count"], 3)
		self.assertEqual(result["suggested_plan"], "BUSINESS")

	def test_check_user_creation_eligibility_blocks_at_limit(self):
		site = SimpleNamespace(name="SITE-001", subscription="SUB-001")
		plan = SimpleNamespace(
			name="PRO",
			plan_title="Pro",
			billing_type="Seat Based",
			next_plan="BUSINESS",
		)

		with patch.object(api_site, "_authenticate_billing_site", return_value=site), patch.object(
			api_site,
			"get_site_seat_limit_context",
			return_value={"plan": "PRO", "billable_seats": 4, "suggested_plan": "BUSINESS"},
		), patch.object(api_site.frappe, "get_cached_doc", return_value=plan):
			result = api_site.check_user_creation_eligibility(active_user_count=4)

		self.assertFalse(result["can_create_user"])
		self.assertEqual(result["reason"], "SEAT_LIMIT_REACHED")
		self.assertIn("Please upgrade to BUSINESS", result["message"])

	def test_check_user_creation_eligibility_fails_without_active_plan(self):
		site = SimpleNamespace(name="SITE-001", subscription=None)

		with patch.object(api_site, "_authenticate_billing_site", return_value=site), patch.object(
			api_site,
			"get_site_seat_limit_context",
			return_value={"plan": None, "billable_seats": 0, "suggested_plan": None},
		):
			result = api_site.check_user_creation_eligibility(active_user_count=1)

		self.assertFalse(result["can_create_user"])
		self.assertEqual(result["reason"], "NO_ACTIVE_PLAN")
