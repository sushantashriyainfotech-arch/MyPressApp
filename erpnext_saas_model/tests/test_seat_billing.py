from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from erpnext_saas_model.doctype.invoice import invoice as invoice_module
from erpnext_saas_model.doctype.invoice.invoice import Invoice as Invoice
from erpnext_saas_model.doctype.usage_record import usage_record as usage_record_module
from erpnext_saas_model.doctype.usage_record.usage_record import UsageRecord
from erpnext_saas_model.patches.v0_0_2 import backfill_seat_usage_record_descriptions as backfill_patch_module


class TestSeatBillingHelpers(FrappeTestCase):
	def test_usage_record_validate_preserves_existing_amount(self):
		usage_record = UsageRecord.__new__(UsageRecord)
		usage_record.plan = "PLAN-001"
		usage_record.plan_type = "Site Plan"
		usage_record.name = "UR-001"
		usage_record.team = "TEAM-001"
		usage_record.document_type = "Site"
		usage_record.document_name = "SITE-001"
		usage_record.interval = "Daily"
		usage_record.date = "2026-05-29"
		usage_record.subscription = "SUB-001"
		usage_record.amount = 12.5
		usage_record.seat_amount = None
		usage_record.billable_seats = 0
		usage_record.snapshot_taken_at = None

		plan = SimpleNamespace(billing_type="Seat Based")
		with patch.object(usage_record_module.PressUsageRecord, "validate", return_value=None), patch.object(
			usage_record_module.frappe, "get_cached_doc", return_value=plan
		), patch.object(usage_record_module, "is_seat_based_plan", return_value=True), patch.object(
			usage_record_module, "now_datetime", return_value=datetime(2026, 5, 29, 0, 0, 0)
		):
			usage_record.validate()

		self.assertEqual(usage_record.amount, 12.5)
		self.assertEqual(usage_record.seat_amount, 12.5)
		self.assertEqual(usage_record.billable_seats, 1)
		self.assertIsNotNone(usage_record.snapshot_taken_at)

	def test_duplicate_usage_record_check_ignores_amount(self):
		usage_record = UsageRecord.__new__(UsageRecord)
		usage_record.name = "UR-002"
		usage_record.team = "TEAM-001"
		usage_record.document_type = "Site"
		usage_record.document_name = "SITE-001"
		usage_record.interval = "Daily"
		usage_record.date = "2026-05-29"
		usage_record.plan = "PLAN-001"
		usage_record.subscription = "SUB-001"
		usage_record.amount = 99.99

		captured_filters = {}

		def fake_get_all(doctype, filters, pluck=None):
			captured_filters.update(filters)
			return []

		with patch.object(usage_record_module.frappe, "get_all", side_effect=fake_get_all), patch.object(
			usage_record_module.frappe.db, "get_value", return_value=1
		):
			usage_record.validate_duplicate_usage_record()

		self.assertNotIn("amount", captured_filters)

	def test_seat_usage_record_remark_is_human_readable(self):
		self.assertEqual(
			usage_record_module.get_seat_usage_record_remark(backfill=False, billable_seats=5),
			"Seat billing snapshot for 5 billable seats",
		)
		self.assertEqual(
			usage_record_module.get_seat_usage_record_remark(backfill=True, billable_seats=1),
			"Seat billing backfill snapshot for 1 billable seat",
		)

	def test_seat_usage_record_description_is_copied_to_invoice_item(self):
		invoice = Invoice.__new__(Invoice)
		invoice.type = "Subscription"
		invoice.period_start = "2026-05-01"
		invoice.period_end = "2026-05-31"
		invoice.billable_seats = 0
		invoice.items = []

		def fake_append(table_field, values):
			row = SimpleNamespace(**values)
			invoice.items.append(row)
			return row

		invoice.append = fake_append
		invoice.save = lambda *args, **kwargs: None
		invoice.get_invoice_item_for_usage_record = lambda usage_record: None

		usage_record = SimpleNamespace(
			plan="PLAN-001",
			plan_type="Site Plan",
			invoice=None,
			date="2026-05-15",
			document_type="Site",
			document_name="site-001",
			site="site-001",
			amount=49.99,
			seat_amount=49.99,
			billable_seats=5,
			remark="Seat billing snapshot for 5 billable seats",
		)
		plan = SimpleNamespace(name="PLAN-001", billing_type="Seat Based")

		with patch.object(invoice_module.frappe, "get_cached_doc", return_value=plan), patch.object(
			invoice_module, "is_seat_based_plan", return_value=True
		):
			invoice.add_usage_record(usage_record)

		self.assertEqual(invoice.items[0].description, usage_record.remark)

	def test_backfill_patch_sets_missing_usage_record_remarks(self):
		captured = []

		def fake_get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, limit=None):
			if doctype == "Site Plan":
				return ["PLAN-001"]
			if doctype == "Usage Record":
				return [
					SimpleNamespace(name="UR-001", remark=None, billable_seats=5),
					SimpleNamespace(
						name="UR-002",
						remark="Seat billing snapshot for 4 billable seats",
						billable_seats=4,
					),
				]
			raise AssertionError(f"Unexpected doctype: {doctype}")

		def fake_set_value(doctype, name, fieldname, value, update_modified=False):
			captured.append((doctype, name, fieldname, value, update_modified))

		with patch.object(backfill_patch_module.frappe, "get_all", side_effect=fake_get_all), patch.object(
			backfill_patch_module.frappe.db, "set_value", side_effect=fake_set_value
		):
			backfill_patch_module.backfill_usage_record_remarks(["PLAN-001"])

		self.assertEqual(
			captured,
			[
				(
					"Usage Record",
					"UR-001",
					"remark",
					"Seat billing snapshot for 5 billable seats",
					False,
				),
			],
		)

	def test_backfill_patch_sets_missing_invoice_item_descriptions(self):
		captured = []

		def fake_get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, limit=None):
			if doctype == "Invoice Item":
				return [
					SimpleNamespace(
						name="ITEM-001",
						parent="INV-001",
						document_type="Site",
						document_name="site-001",
						plan="PLAN-001",
						description="",
					),
					SimpleNamespace(
						name="ITEM-002",
						parent="INV-002",
						document_type="Site",
						document_name="site-002",
						plan="PLAN-001",
						description="",
					),
				]
			if doctype == "Usage Record":
				if filters and filters.get("invoice") == "INV-001":
					return [SimpleNamespace(name="UR-001", remark="Seat billing snapshot for 5 billable seats", billable_seats=5)]
				return []
			raise AssertionError(f"Unexpected doctype: {doctype}")

		def fake_set_value(doctype, name, fieldname, value, update_modified=False):
			captured.append((doctype, name, fieldname, value, update_modified))

		with patch.object(backfill_patch_module.frappe, "get_all", side_effect=fake_get_all), patch.object(
			backfill_patch_module.frappe.db, "set_value", side_effect=fake_set_value
		):
			backfill_patch_module.backfill_invoice_item_descriptions(["PLAN-001"])

		self.assertEqual(
			captured,
			[
				(
					"Invoice Item",
					"ITEM-001",
					"description",
					"Seat billing snapshot for 5 billable seats",
					False,
				),
				(
					"Invoice Item",
					"ITEM-002",
					"description",
					"Seat billing snapshot",
					False,
				),
			],
		)
