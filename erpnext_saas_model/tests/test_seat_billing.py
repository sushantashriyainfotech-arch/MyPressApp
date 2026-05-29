from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from erpnext_saas_model import seat_billing
from erpnext_saas_model.doctype.usage_record import usage_record as usage_record_module
from erpnext_saas_model.doctype.usage_record.usage_record import UsageRecord


class TestSeatBillingHelpers(FrappeTestCase):
	def test_month_fraction_uses_calendar_days(self):
		with patch.object(seat_billing.frappe.utils, "today", return_value="2026-05-26"):
			self.assertAlmostEqual(seat_billing.get_seat_billing_month_fraction(), 1 / 31, places=8)

	def test_usage_record_validate_preserves_existing_amount(self):
		usage_record = UsageRecord.__new__(UsageRecord)
		usage_record.plan = "PLAN-001"
		usage_record.plan_type = "Site Plan"
		usage_record.amount = 12.5
		usage_record.seat_amount = None
		usage_record.billable_seats = 0
		usage_record.snapshot_taken_at = None

		plan = SimpleNamespace(billing_type="Seat Based")
		with patch.object(usage_record_module.PressUsageRecord, "validate", return_value=None), patch.object(
			usage_record_module.frappe, "get_cached_doc", return_value=plan
		), patch.object(usage_record_module, "is_seat_based_plan", return_value=True), patch.object(
			usage_record_module, "now_datetime", return_value=datetime(2026, 5, 26, 19, 0, 0)
		):
			usage_record.validate()

		self.assertEqual(usage_record.amount, 12.5)
		self.assertEqual(usage_record.seat_amount, 12.5)
		self.assertEqual(usage_record.billable_seats, 1)
		self.assertIsNotNone(usage_record.snapshot_taken_at)
