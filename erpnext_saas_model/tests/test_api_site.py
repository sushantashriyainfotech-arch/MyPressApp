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

		with patch.object(api_site, "_authenticate_billing_site", return_value=site), patch.object(
			api_site,
			"validate_site_user_seat_limit",
			return_value=None,
		) as validate_limit:
			result = api_site.check_user_creation_eligibility()

		validate_limit.assert_called_once_with(site, enabled=True)
		self.assertTrue(result)

	def test_check_user_creation_eligibility_blocks_at_limit(self):
		site = SimpleNamespace(name="SITE-001", subscription="SUB-001")

		with patch.object(api_site, "_authenticate_billing_site", return_value=site), patch.object(
			api_site,
			"validate_site_user_seat_limit",
			side_effect=Exception("Please upgrade your plan."),
		) as validate_limit:
			with self.assertRaises(Exception) as excinfo:
				api_site.check_user_creation_eligibility()

		validate_limit.assert_called_once_with(site, enabled=True)
		self.assertIn("Please upgrade your plan.", str(excinfo.exception))

	def test_check_user_creation_eligibility_fails_without_active_plan(self):
		site = SimpleNamespace(name="SITE-001", subscription=None)

		with patch.object(api_site, "_authenticate_billing_site", return_value=site), patch.object(
			api_site,
			"validate_site_user_seat_limit",
			side_effect=Exception("No active subscription found."),
		):
			with self.assertRaises(Exception) as excinfo:
				api_site.check_user_creation_eligibility()

		self.assertIn("No active subscription found.", str(excinfo.exception))

	def test_sync_site_user_upserts_mirror_row(self):
		site = SimpleNamespace(name="SITE-001")
		with patch.object(api_site, "_authenticate_billing_site", return_value=site), patch.object(
			api_site, "upsert_site_user", return_value=SimpleNamespace(name="SU-001")
		) as upsert:
			result = api_site.sync_site_user(user="user@example.com", enabled=1, operation="upsert")

		upsert.assert_called_once_with("SITE-001", "user@example.com", True)
		self.assertTrue(result)

	def test_sync_site_user_disables_on_delete(self):
		site = SimpleNamespace(name="SITE-001")
		with patch.object(api_site, "_authenticate_billing_site", return_value=site), patch.object(
			api_site, "upsert_site_user", return_value=SimpleNamespace(name="SU-001")
		) as upsert:
			result = api_site.sync_site_user(user="user@example.com", enabled=1, operation="delete")

		upsert.assert_called_once_with("SITE-001", "user@example.com", False)
		self.assertTrue(result)
