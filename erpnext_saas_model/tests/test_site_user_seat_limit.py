from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe.tests.utils import FrappeTestCase

from erpnext_saas_model import seat_billing


class TestSiteUserSeatLimit(FrappeTestCase):
	def test_validate_site_user_seat_limit_raises_when_full(self):
		with patch.object(
			seat_billing,
			"get_site_seat_limit_context",
			return_value={"billable_seats": 2, "active_user_count": 2, "next_plan": "PRO"},
		), patch.object(seat_billing.frappe, "throw") as throw:
			seat_billing.validate_site_user_seat_limit("site-001", enabled=True)

		throw.assert_called_once()
		self.assertIn("upgrade to PRO", throw.call_args.args[0])

	def test_validate_site_user_seat_limit_allows_unlimited(self):
		with patch.object(
			seat_billing,
			"get_site_seat_limit_context",
			return_value={"billable_seats": 0, "active_user_count": 99, "next_plan": "PRO"},
		), patch.object(seat_billing.frappe, "throw") as throw:
			context = seat_billing.validate_site_user_seat_limit("site-001", enabled=True)

		throw.assert_not_called()
		self.assertEqual(context["billable_seats"], 0)

	def test_validate_team_member_seat_limit_allows_unlimited(self):
		with patch.object(
			seat_billing,
			"get_team_seat_limit_context",
			return_value={"billable_seats": 0, "active_user_count": 99, "next_plan": "PRO"},
		), patch.object(seat_billing.frappe, "throw") as throw:
			context = seat_billing.validate_team_member_seat_limit("TEAM-001")

		throw.assert_not_called()
		self.assertEqual(context["billable_seats"], 0)

	def test_upsert_site_user_enables_existing_user_with_room(self):
		site = SimpleNamespace(name="site-001")
		existing_user = SimpleNamespace(name="SU-001", enabled=0)

		with patch.object(seat_billing.frappe, "get_cached_doc", return_value=site), patch.object(
			seat_billing.frappe.db, "get_value", side_effect=["SU-001", 0]
		), patch.object(seat_billing, "validate_site_user_seat_limit") as validate, patch.object(
			seat_billing.frappe, "get_doc", return_value=existing_user
		) as get_doc, patch.object(seat_billing.frappe.db, "set_value") as set_value, patch.object(
			seat_billing, "refresh_site_user_active_count_cache"
		) as refresh_cache:
			result = seat_billing.upsert_site_user("site-001", "user@example.com", True)

		validate.assert_called_once_with(site, enabled=True)
		set_value.assert_called_once_with("Site User", "SU-001", "enabled", True)
		get_doc.assert_called_once_with("Site User", "SU-001")
		refresh_cache.assert_called_once_with("site-001")
		self.assertEqual(result, existing_user)

	def test_get_site_user_active_count_uses_cache_and_refreshes_on_miss(self):
		with patch.object(
			seat_billing.frappe,
			"cache",
			return_value=SimpleNamespace(
				get_value=Mock(return_value=None),
				set_value=Mock(),
			),
		), patch.object(seat_billing.frappe.db, "count", return_value=3) as count:
			result = seat_billing.get_site_user_active_count("site-001")

		self.assertEqual(result, 3)
		count.assert_called_once_with("Site User", {"site": "site-001", "enabled": 1})

	def test_validate_site_user_before_save_ignores_noop_update(self):
		doc = SimpleNamespace(
			site="site-001",
			enabled=1,
			get_doc_before_save=Mock(return_value=SimpleNamespace(enabled=1)),
		)

		with patch.object(seat_billing, "validate_site_user_seat_limit") as validate:
			seat_billing.validate_site_user_before_save(doc)

		validate.assert_not_called()
