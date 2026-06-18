from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_saas_model.doctype.site.site import Site
from erpnext_saas_model.doctype.site import site as site_module


class TestSiteSeatPlanChanges(FrappeTestCase):
	def test_set_plan_updates_seat_count_without_changing_plan(self):
		site = Site.__new__(Site)
		site.name = "SITE-001"
		site.plan = "PLAN-001"
		site.team = "TEAM-001"
		site.billable_seats = 2

		plan = SimpleNamespace(name="PLAN-001", billing_type="Seat Based", min_seats=1, max_seats=10)
		subscription = SimpleNamespace(
			team="TEAM-001",
			site="SITE-001",
			update_billable_seats=Mock(return_value={"subscription": "SUB-001", "billable_seats": 4})
		)

		with patch.object(site_module.frappe, "get_cached_doc", return_value=plan), patch.object(
			site_module, "validate_seat_selection_for_plan", return_value={"billable_seats": 4}
		), patch.object(site_module.frappe, "get_doc", return_value=subscription), patch.object(
			site_module.frappe.db, "set_value"
		) as set_value, patch.object(site, "change_plan") as change_plan, patch.object(
			Site, "subscription", new_callable=PropertyMock, return_value=subscription
		):
			result = site.set_plan("PLAN-001", billable_seats=4)

		set_value.assert_called_once_with("Site", "SITE-001", "billable_seats", 4, update_modified=False)
		subscription.update_billable_seats.assert_called_once_with(4)
		change_plan.assert_not_called()
		self.assertEqual(result, {"subscription": "SUB-001", "billable_seats": 4})

	def test_set_plan_rejects_seat_counts_above_plan_max(self):
		site = Site.__new__(Site)
		site.name = "SITE-001"
		site.plan = "PLAN-001"
		site.team = "TEAM-001"
		site.billable_seats = 2

		plan = SimpleNamespace(name="PLAN-001", billing_type="Seat Based", min_seats=1, max_seats=10)

		with patch.object(site_module.frappe, "get_cached_doc", return_value=plan), patch.object(
			site_module,
			"validate_seat_selection_for_plan",
			return_value={
				"error_code": "SEATS_EXCEED_PLAN_LIMIT",
				"next_plan": "BUSINESS",
				"message": "Requested seats exceed the current plan limit.",
			},
		), patch.object(site_module.frappe.db, "set_value") as set_value, patch.object(
			site, "change_plan"
		) as change_plan:
			with self.assertRaises(frappe.ValidationError) as context:
				site.set_plan("PLAN-001", billable_seats=12)

		self.assertIn("Please choose BUSINESS or fewer seats", str(context.exception))
		set_value.assert_not_called()
		change_plan.assert_not_called()

	def test_set_plan_clears_billable_seats_for_resource_based_plan(self):
		site = Site.__new__(Site)
		site.name = "SITE-001"
		site.plan = "PLAN-001"
		site.team = "TEAM-001"
		site.billable_seats = 5

		plan = SimpleNamespace(name="PLAN-002", billing_type="Resource Based")

		with patch.object(site_module.frappe, "get_cached_doc", return_value=plan), patch.object(
			site_module.PressSite, "set_plan", return_value="ok"
		) as base_set_plan, patch.object(site_module.frappe.db, "set_value") as set_value:
			result = site.set_plan("PLAN-002")

		base_set_plan.assert_called_once_with("PLAN-002")
		set_value.assert_called_once_with("Site", "SITE-001", "billable_seats", 0, update_modified=False)
		self.assertEqual(site.billable_seats, 0)
		self.assertEqual(result, "ok")

	def test_update_seat_count_rejects_cross_team_subscription(self):
		site = Site.__new__(Site)
		site.name = "SITE-001"
		site.team = "TEAM-001"

		subscription = SimpleNamespace(
			team="TEAM-999",
			site="SITE-001",
			update_billable_seats=Mock(),
		)

		with patch.object(Site, "subscription", new_callable=PropertyMock, return_value=subscription), patch.object(
			site_module.frappe, "get_doc", return_value=subscription
		), patch.object(
			site_module.frappe, "throw", side_effect=frappe.ValidationError("linked subscription mismatch")
		):
			with self.assertRaises(frappe.ValidationError) as context:
				site._update_seat_count_for_current_plan(4)

		self.assertIn("linked subscription mismatch", str(context.exception))
		subscription.update_billable_seats.assert_not_called()

	def test_subscription_property_prefers_explicit_site_link(self):
		site = Site.__new__(Site)
		site.name = "SITE-001"
		site.team = "TEAM-001"

		with patch.object(site_module.frappe.db, "get_value", side_effect=["SUB-SITE-001"]) as get_value, patch.object(
			site_module.frappe, "get_doc", return_value=SimpleNamespace(name="SUB-SITE-001")
		) as get_doc:
			result = site.subscription

		self.assertEqual(result.name, "SUB-SITE-001")
		get_value.assert_called_once_with(
			"Subscription",
			{"site": "SITE-001", "document_type": "Site"},
			"name",
			order_by="modified desc",
		)
		get_doc.assert_called_once_with("Subscription", "SUB-SITE-001")
