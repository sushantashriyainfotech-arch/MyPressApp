from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from erpnext_saas_model import seat_billing as seat_billing_module
from erpnext_saas_model.doctype.invoice import invoice as invoice_module
from erpnext_saas_model.doctype.invoice.invoice import Invoice as Invoice
from erpnext_saas_model.doctype.usage_record import usage_record as usage_record_module
from erpnext_saas_model.doctype.usage_record.usage_record import UsageRecord
from erpnext_saas_model.patches.v0_0_2 import backfill_seat_usage_record_descriptions as backfill_patch_module
from erpnext_saas_model.patches.v0_0_3 import (
	backfill_seat_usage_record_window_descriptions as window_backfill_patch_module,
)
from erpnext_saas_model.patches.v0_0_4 import (
	backfill_seat_change_log_team_and_proration as seat_change_log_backfill_patch_module,
)
from erpnext_saas_model.patches.v0_0_5 import (
	backfill_seat_usage_invoice_item_grouping as usage_invoice_backfill_patch_module,
)


class TestSeatBillingHelpers(FrappeTestCase):
	def test_snapshot_helpers_use_midnight_cutoff(self):
		snapshot_moment = datetime(2026, 5, 29, 0, 0, 0)
		after_snapshot = datetime(2026, 5, 29, 0, 0, 1)

		self.assertEqual(seat_billing_module.get_next_snapshot_date(snapshot_moment), snapshot_moment.date())
		self.assertEqual(seat_billing_module.get_next_snapshot_date(after_snapshot), datetime(2026, 5, 30).date())
		self.assertEqual(seat_billing_module.get_billing_effective_from(snapshot_moment), snapshot_moment.date())
		self.assertEqual(
			seat_billing_module.get_billing_effective_from(after_snapshot),
			datetime(2026, 5, 30).date(),
		)

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
		change_log = SimpleNamespace(name="SEAT-LOG-001", old_seats=2, new_seats=5, change_type="Increase")
		with patch.object(
			seat_billing_module,
			"get_seat_change_log_for_reference",
			return_value=change_log,
		):
			self.assertEqual(
				seat_billing_module.get_seat_usage_record_remark(
					subscription="SUB-001",
					snapshot_taken_at=datetime(2026, 5, 29, 0, 0, 0),
					fallback_billable_seats=5,
			),
			"Seats changed: 2 -> 5",
		)

	def test_seat_usage_record_remark_aggregates_same_window_changes(self):
		billing_date = datetime(2026, 5, 29, 18, 0, 0).date()
		logs = [
			SimpleNamespace(
				name="SEAT-LOG-001",
				old_seats=5,
				new_seats=7,
				change_type="Increase",
				billing_effective_from=billing_date,
			),
			SimpleNamespace(
				name="SEAT-LOG-002",
				old_seats=7,
				new_seats=8,
				change_type="Increase",
				billing_effective_from=billing_date,
			),
		]

		def fake_get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, limit=None):
			if doctype == "Seat Change Log" and filters and filters.get("subscription") == "SUB-001":
				if filters.get("billing_effective_from") == billing_date:
					return logs
			if doctype == "Subscription":
				return [SimpleNamespace(name="SUB-001")]
			return []

		with patch.object(seat_billing_module.frappe, "get_all", side_effect=fake_get_all), patch.object(
			seat_billing_module.frappe, "get_cached_doc", return_value=SimpleNamespace(name="SUB-001")
		):
			self.assertEqual(
				seat_billing_module.get_seat_usage_record_remark(
					subscription="SUB-001",
					reference_at=datetime(2026, 5, 29, 18, 0, 0),
					fallback_billable_seats=8,
				),
				"Seats changed: 5 -> 8",
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
			subscription="SUB-001",
			seat_change_log="SEAT-LOG-001",
			invoice=None,
			date="2026-05-15",
			document_type="Site",
			document_name="site-001",
			site="site-001",
			amount=49.99,
			billable_seats=5,
			snapshot_taken_at=datetime(2026, 5, 15, 18, 0, 0),
			db_set=lambda *args, **kwargs: None,
		)
		plan = SimpleNamespace(name="PLAN-001", billing_type="Seat Based")

		with patch.object(invoice_module.frappe, "get_cached_doc", return_value=plan), patch.object(
			invoice_module, "is_seat_based_plan", return_value=True
		), patch.object(invoice_module, "get_seat_usage_record_remark", return_value="Seats changed: 2 -> 5"):
			invoice.add_usage_record(usage_record)

		self.assertEqual(invoice.items[0].description, "Seats changed: 2 -> 5")
		self.assertEqual(invoice.items[0].usage_record, usage_record.name)
		self.assertEqual(invoice.items[0].seat_change_log, usage_record.seat_change_log)
		self.assertEqual(invoice.items[0].billable_seats, 5)

	def test_seat_usage_record_remark_prefers_exact_seat_change_log(self):
		exact_log = SimpleNamespace(name="SEAT-LOG-007", old_seats=7, new_seats=8)

		with patch.object(seat_billing_module.frappe, "get_cached_doc", return_value=exact_log):
			self.assertEqual(
				seat_billing_module.get_seat_usage_record_remark(
					subscription="SUB-001",
					seat_change_log="SEAT-LOG-007",
					fallback_billable_seats=8,
				),
				"Seats changed: 7 -> 8",
			)

	def test_seat_usage_records_group_only_when_consecutive(self):
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

		def make_usage_record(name, description, billable_seats, date):
			return SimpleNamespace(
				name=name,
				plan="PLAN-001",
				plan_type="Site Plan",
				subscription="SUB-001",
				seat_change_log=name,
				remark=description,
				invoice=None,
				date=date,
				document_type="Site",
				document_name="site-001",
				site="site-001",
				amount=49.99,
				billable_seats=billable_seats,
				snapshot_taken_at=datetime(2026, 5, 15, 18, 0, 0),
				db_set=lambda *args, **kwargs: None,
			)

		usage_records = [
			make_usage_record("UR-001", "Seats changed: 2 -> 5", 5, "2026-05-15"),
			make_usage_record("UR-002", "Seats changed: 2 -> 5", 5, "2026-05-16"),
			make_usage_record("UR-003", "Seats changed: 5 -> 7", 7, "2026-05-17"),
			make_usage_record("UR-004", "Seats changed: 2 -> 5", 5, "2026-05-18"),
		]

		plan = SimpleNamespace(name="PLAN-001", billing_type="Seat Based")
		with patch.object(invoice_module.frappe, "get_cached_doc", return_value=plan), patch.object(
			invoice_module, "is_seat_based_plan", return_value=True
		):
			for usage_record in usage_records:
				invoice.add_usage_record(usage_record)

		self.assertEqual(len(invoice.items), 3)
		self.assertEqual(invoice.items[0].quantity, 2)
		self.assertEqual(invoice.items[0].billable_seats, 5)
		self.assertEqual(invoice.items[1].quantity, 1)
		self.assertEqual(invoice.items[2].quantity, 1)
		self.assertEqual(invoice.items[2].billable_seats, 5)

	def test_update_item_descriptions_uses_press_for_resource_and_remark_for_seat_based(self):
		invoice = Invoice.__new__(Invoice)
		seat_item = SimpleNamespace(
			plan="SEAT-PLAN",
			usage_record="UR-001",
			description=None,
			document_type="Site",
			document_name="site-001",
			quantity=1,
		)
		resource_item = SimpleNamespace(
			plan="RESOURCE-PLAN",
			description=None,
			document_type="Site",
			document_name="site-002",
			quantity=1,
		)
		invoice.items = [seat_item, resource_item]

		def fake_get_cached_doc(doctype, name):
			if doctype == "Usage Record" and name == "UR-001":
				return SimpleNamespace(
					name="UR-001",
					remark="Seats changed: 1 -> 5",
					seat_change_log=None,
				)
			if doctype == "Site Plan" and name == "SEAT-PLAN":
				return SimpleNamespace(name=name, billing_type="Seat Based")
			if doctype == "Site Plan" and name == "RESOURCE-PLAN":
				return SimpleNamespace(name=name, billing_type="Resource Based")
			raise AssertionError(f"Unexpected cached doc: {doctype} {name}")

		def fake_press_update_item_descriptions(self):
			resource_item.description = "Press description"

		with patch.object(invoice_module.frappe, "get_cached_doc", side_effect=fake_get_cached_doc), patch.object(
			invoice_module.PressInvoice, "update_item_descriptions", fake_press_update_item_descriptions
		):
			invoice.update_item_descriptions()

		self.assertEqual(seat_item.description, "Seats changed: 1 -> 5")
		self.assertEqual(resource_item.description, "Press description")

	def test_invoice_prefers_usage_record_remark_over_seat_change_log(self):
		invoice = Invoice.__new__(Invoice)
		invoice.type = "Subscription"
		invoice.period_start = "2026-05-01"
		invoice.period_end = "2026-05-31"
		invoice.billable_seats = 0

		usage_record = SimpleNamespace(
			remark="Seats changed: 5 -> 8",
			seat_change_log="SEAT-LOG-002",
			snapshot_taken_at=datetime(2026, 5, 29, 18, 0, 0),
			date="2026-05-29",
			subscription="SUB-001",
			billable_seats=8,
		)

		with patch.object(invoice_module, "get_seat_usage_record_remark", side_effect=AssertionError("unexpected call")):
			self.assertEqual(invoice._get_seat_usage_description(usage_record), "Seats changed: 5 -> 8")

	def test_log_seat_change_sets_team_and_proration_amount(self):
		captured = {}

		def fake_get_cached_doc(doctype, name):
			if doctype == "Subscription":
				return SimpleNamespace(
					name=name,
					team="TEAM-001",
					site="SITE-001",
					document_type="Site",
					document_name="SITE-001",
					plan_type="Site Plan",
					plan="PLAN-001",
					price_inr=31,
					price_usd=0,
					total_amount=31,
					billable_seats=1,
				)
			if doctype == "Site Plan":
				return SimpleNamespace(name=name, billing_type="Seat Based", price_inr=31, price_usd=0)
			raise AssertionError(f"Unexpected cached doc: {doctype} {name}")

		def fake_get_doc(data):
			captured.update(data)
			return SimpleNamespace(insert=lambda ignore_permissions=False: None)

		with patch.object(seat_billing_module.frappe, "get_cached_doc", side_effect=fake_get_cached_doc), patch.object(
			seat_billing_module.frappe, "get_doc", side_effect=fake_get_doc
		), patch.object(seat_billing_module.frappe.db, "get_value", return_value="INR"), patch.object(
			seat_billing_module.frappe.session, "user", "Administrator"
		):
			seat_billing_module.log_seat_change("SUB-001", old_seats=5, new_seats=7, access_updated_at=datetime(2026, 5, 1, 12, 0, 0))

		self.assertEqual(captured["team"], "TEAM-001")
		self.assertEqual(captured["currency"], "INR")
		self.assertEqual(captured["proration_amount"], 62.0)

	def test_seat_change_log_backfill_sets_team_and_proration_amount(self):
		captured = []

		def fake_get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, limit=None):
			if doctype == "Seat Change Log":
				return [
					SimpleNamespace(
						name="SEAT-LOG-001",
						subscription="SUB-001",
						team=None,
						old_seats=5,
						new_seats=7,
						access_updated_at=datetime(2026, 5, 1, 12, 0, 0),
						billing_effective_from=datetime(2026, 5, 1, 0, 0, 0).date(),
						proration_amount=0.0,
					)
				]
			return []

		def fake_get_value(doctype, name, fieldname):
			if doctype == "Team" and fieldname == "currency":
				return "INR"
			if doctype == "Subscription" and fieldname == "team":
				return "TEAM-001"
			raise AssertionError(f"Unexpected get_value: {doctype} {name} {fieldname}")

		def fake_get_cached_doc(doctype, name):
			if doctype == "Subscription":
				return SimpleNamespace(
					name=name,
					team="TEAM-001",
					site="SITE-001",
					document_type="Site",
					document_name="SITE-001",
					plan_type="Site Plan",
					plan="PLAN-001",
					price_inr=31,
					price_usd=0,
					total_amount=31,
					billable_seats=1,
				)
			if doctype == "Site Plan":
				return SimpleNamespace(name=name, billing_type="Seat Based", price_inr=31, price_usd=0)
			raise AssertionError(f"Unexpected cached doc: {doctype} {name}")

		def fake_set_value(doctype, name, fieldname, value, update_modified=False):
			captured.append((doctype, name, fieldname, value, update_modified))

		with patch.object(seat_change_log_backfill_patch_module.frappe, "get_all", side_effect=fake_get_all), patch.object(
			seat_change_log_backfill_patch_module.frappe, "get_value", side_effect=fake_get_value
		), patch.object(seat_change_log_backfill_patch_module.frappe, "reload_doc", return_value=None), patch.object(
			seat_change_log_backfill_patch_module.frappe, "get_cached_doc", side_effect=fake_get_cached_doc
		), patch.object(
			seat_change_log_backfill_patch_module.frappe.db, "set_value", side_effect=fake_set_value
		), patch.object(seat_change_log_backfill_patch_module.frappe.db, "get_value", return_value="INR"):
			seat_change_log_backfill_patch_module.execute()

		self.assertEqual(
			captured,
			[
				("Seat Change Log", "SEAT-LOG-001", "team", "TEAM-001", False),
				("Seat Change Log", "SEAT-LOG-001", "currency", "INR", False),
				("Seat Change Log", "SEAT-LOG-001", "proration_amount", 62.0, False),
			],
		)

		def test_seat_change_log_backfill_skips_currency_when_column_is_missing(self):
			captured_fields = []

			def fake_get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, limit=None):
				if doctype == "Seat Change Log":
					captured_fields.extend(fields or [])
					return [
						SimpleNamespace(
							name="SEAT-LOG-001",
							subscription="SUB-001",
							team=None,
							old_seats=5,
							new_seats=7,
							access_updated_at=datetime(2026, 5, 1, 12, 0, 0),
							billing_effective_from=datetime(2026, 5, 1, 0, 0, 0).date(),
							proration_amount=0.0,
						)
					]
				return []

			def fake_get_value(doctype, name, fieldname):
				if doctype == "Subscription" and fieldname == "team":
					return "TEAM-001"
				raise AssertionError(f"Unexpected get_value: {doctype} {name} {fieldname}")

			def fake_get_cached_doc(doctype, name):
				if doctype == "Subscription":
					return SimpleNamespace(
						name=name,
						team="TEAM-001",
						site="SITE-001",
						document_type="Site",
						document_name="SITE-001",
						plan_type="Site Plan",
						plan="PLAN-001",
						price_inr=31,
						price_usd=0,
						total_amount=31,
						billable_seats=1,
					)
				if doctype == "Site Plan":
					return SimpleNamespace(name=name, billing_type="Seat Based", price_inr=31, price_usd=0)
				raise AssertionError(f"Unexpected cached doc: {doctype} {name}")

			def fake_set_value(*args, **kwargs):
				raise AssertionError("currency writes should be skipped when the column is missing")

			with patch.object(seat_change_log_backfill_patch_module.frappe, "get_all", side_effect=fake_get_all), patch.object(
				seat_change_log_backfill_patch_module.frappe, "get_value", side_effect=fake_get_value
			), patch.object(seat_change_log_backfill_patch_module.frappe, "reload_doc", return_value=None), patch.object(
				seat_change_log_backfill_patch_module.frappe, "get_cached_doc", side_effect=fake_get_cached_doc
			), patch.object(
				seat_change_log_backfill_patch_module.frappe.db, "set_value", side_effect=fake_set_value
			), patch.object(seat_change_log_backfill_patch_module.frappe.db, "get_value", return_value="INR"), patch.object(
				seat_change_log_backfill_patch_module.frappe.db, "has_column", return_value=False
			):
				seat_change_log_backfill_patch_module.execute()

			self.assertNotIn("currency", captured_fields)

		def test_usage_record_backfill_keeps_distinct_seat_change_logs(self):
			captured = []

			def fake_get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, limit=None):
				if doctype == "Site Plan":
					return ["PLAN-001"]
				if doctype == "Usage Record":
					return [
						SimpleNamespace(
							name="UR-001",
							remark="old",
							billable_seats=5,
							subscription="SUB-001",
							team="TEAM-001",
							date=datetime(2026, 5, 15, 0, 0, 0).date(),
							snapshot_taken_at=datetime(2026, 5, 15, 18, 0, 0),
							seat_change_log="SEAT-LOG-001",
						),
						SimpleNamespace(
							name="UR-002",
							remark="old",
							billable_seats=7,
							subscription="SUB-001",
							team="TEAM-001",
							date=datetime(2026, 5, 16, 0, 0, 0).date(),
							snapshot_taken_at=datetime(2026, 5, 16, 18, 0, 0),
							seat_change_log="SEAT-LOG-002",
						),
					]
				return []

			def fake_get_doc(doctype, name):
				if doctype == "Seat Change Log":
					if name == "SEAT-LOG-001":
						return SimpleNamespace(name=name, old_seats=5, new_seats=7)
					if name == "SEAT-LOG-002":
						return SimpleNamespace(name=name, old_seats=7, new_seats=8)
				raise AssertionError(f"Unexpected get_doc: {doctype} {name}")

			def fake_set_value(doctype, name, fieldname, value, update_modified=False):
				captured.append((doctype, name, fieldname, value, update_modified))

			with patch.object(usage_invoice_backfill_patch_module.frappe, "get_all", side_effect=fake_get_all), patch.object(
				usage_invoice_backfill_patch_module.frappe, "get_doc", side_effect=fake_get_doc
			), patch.object(
				usage_invoice_backfill_patch_module.frappe.db, "set_value", side_effect=fake_set_value
			), patch.object(
				usage_invoice_backfill_patch_module.frappe, "get_cached_doc", side_effect=fake_get_doc
			):
				usage_invoice_backfill_patch_module.backfill_usage_record_billable_seats_and_remarks()

			self.assertEqual(
				captured,
				[
					("Usage Record", "UR-001", "remark", "Seats changed: 5 -> 7", False),
					("Usage Record", "UR-002", "remark", "Seats changed: 7 -> 8", False),
				],
			)

	def test_backfill_patch_sets_missing_usage_record_remarks(self):
		captured = []

		def fake_get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, limit=None):
			if doctype == "Site Plan":
				return ["PLAN-001"]
			if doctype == "Usage Record":
				return [
					SimpleNamespace(
						name="UR-001",
						remark=None,
						billable_seats=5,
						subscription="SUB-001",
						date="2026-05-29",
						snapshot_taken_at=datetime(2026, 5, 29, 18, 0, 0),
						seat_change_log=None,
					),
					SimpleNamespace(
						name="UR-002",
						remark="Seats changed: 3 -> 4",
						billable_seats=4,
						subscription="SUB-002",
						date="2026-05-29",
						snapshot_taken_at=datetime(2026, 5, 29, 18, 0, 0),
						seat_change_log="SEAT-LOG-002",
					),
				]
			if doctype == "Seat Change Log":
				if filters and filters.get("subscription") == "SUB-001":
					return [SimpleNamespace(name="SEAT-LOG-001", old_seats=2, new_seats=5, change_type="Increase")]
				if filters and filters.get("subscription") == "SUB-002":
					return [SimpleNamespace(name="SEAT-LOG-002", old_seats=3, new_seats=4, change_type="Increase")]
				return []
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
					"Seats changed: 2 -> 5",
					False,
				),
				(
					"Usage Record",
					"UR-001",
					"seat_change_log",
					"SEAT-LOG-001",
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
						rate=8.33,
						description="Seats changed: 7 -> 8",
						usage_record=None,
						seat_change_log=None,
					),
					SimpleNamespace(
						name="ITEM-002",
						parent="INV-002",
						document_type="Site",
						document_name="site-002",
						plan="PLAN-001",
						rate=8.33,
						description="Seats changed: 7 -> 8",
						usage_record=None,
						seat_change_log="SEAT-LOG-002",
					),
				]
			if doctype == "Usage Record":
				if filters and filters.get("invoice") == "INV-001":
					return [
						SimpleNamespace(
							name="UR-001",
							subscription="SUB-001",
							remark=None,
							billable_seats=5,
							amount=250,
							date="2026-06-30",
							snapshot_taken_at=datetime(2026, 5, 29, 18, 0, 0),
							seat_change_log="SEAT-LOG-001",
						)
					]
				if filters and filters.get("invoice") == "INV-002":
					return [
						SimpleNamespace(
							name="UR-002",
							subscription="SUB-002",
							remark="Seats changed: 3 -> 4",
							billable_seats=4,
							amount=250,
							date="2026-06-30",
							snapshot_taken_at=datetime(2026, 5, 29, 18, 0, 0),
							seat_change_log="SEAT-LOG-002",
						)
					]
				return []
			if doctype == "Seat Change Log":
				if filters and filters.get("subscription") == "SUB-001":
					return [SimpleNamespace(name="SEAT-LOG-001", old_seats=2, new_seats=5, change_type="Increase")]
				if filters and filters.get("subscription") == "SUB-002":
					return [SimpleNamespace(name="SEAT-LOG-002", old_seats=3, new_seats=4, change_type="Increase")]
				return []
			raise AssertionError(f"Unexpected doctype: {doctype}")

		def fake_set_value(doctype, name, fieldname, value, update_modified=False):
			captured.append((doctype, name, fieldname, value, update_modified))

		with patch.object(backfill_patch_module.frappe, "get_all", side_effect=fake_get_all), patch.object(
			backfill_patch_module.frappe.db, "set_value", side_effect=fake_set_value
		):
			backfill_patch_module.backfill_invoice_item_descriptions(["PLAN-001"])

	def test_window_backfill_patch_uses_aggregated_window_remark(self):
		captured = []
		billing_date = datetime(2026, 5, 29, 18, 0, 0).date()

		def fake_get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, limit=None):
			if doctype == "Site Plan":
				return ["PLAN-001"]
			if doctype == "Usage Record":
				if filters and filters.get("plan") == ("in", ["PLAN-001"]):
					return [
						SimpleNamespace(
							name="UR-001",
							remark=None,
							billable_seats=8,
							subscription="SUB-001",
							date="2026-05-29",
							snapshot_taken_at=datetime(2026, 5, 29, 18, 0, 0),
							seat_change_log=None,
						)
					]
				if filters and filters.get("invoice") == "INV-001":
					return [
						SimpleNamespace(
							name="UR-001",
							subscription="SUB-001",
							date="2026-05-29",
							billable_seats=8,
							remark=None,
							snapshot_taken_at=datetime(2026, 5, 29, 18, 0, 0),
							seat_change_log=None,
						)
					]
				return []
			if doctype == "Invoice Item":
				return [
					SimpleNamespace(
						name="ITEM-001",
						parent="INV-001",
						document_type="Site",
						document_name="site-001",
						plan="PLAN-001",
						rate=8.33,
						description="Seats changed: 7 -> 8",
						usage_record="UR-001",
					)
				]
			if doctype == "Seat Change Log":
				if filters and filters.get("subscription") == "SUB-001" and filters.get("billing_effective_from") == billing_date:
					return [
						SimpleNamespace(
							name="SEAT-LOG-001",
							old_seats=5,
							new_seats=7,
							change_type="Increase",
							billing_effective_from=billing_date,
						),
						SimpleNamespace(
							name="SEAT-LOG-002",
							old_seats=7,
							new_seats=8,
							change_type="Increase",
							billing_effective_from=billing_date,
						),
					]
				return []
			raise AssertionError(f"Unexpected doctype: {doctype}")

		def fake_set_value(doctype, name, fieldname, value, update_modified=False):
			captured.append((doctype, name, fieldname, value, update_modified))

		with patch.object(window_backfill_patch_module.frappe, "get_all", side_effect=fake_get_all), patch.object(
			window_backfill_patch_module.frappe.db, "set_value", side_effect=fake_set_value
		), patch.object(
			window_backfill_patch_module.frappe,
			"get_doc",
			return_value=SimpleNamespace(
				name="UR-001",
				subscription="SUB-001",
				date="2026-05-29",
				billable_seats=8,
				remark=None,
				snapshot_taken_at=datetime(2026, 5, 29, 18, 0, 0),
			),
		):
			window_backfill_patch_module.execute()

		self.assertEqual(
			captured,
			[
				("Usage Record", "UR-001", "remark", "Seats changed: 5 -> 8", False),
				("Invoice Item", "ITEM-001", "description", "Seats changed: 5 -> 8", False),
			],
		)

		self.assertEqual(
			captured,
			[
				(
					"Invoice Item",
					"ITEM-001",
					"usage_record",
					"UR-001",
					False,
				),
				(
					"Invoice Item",
					"ITEM-001",
					"seat_change_log",
					"SEAT-LOG-001",
					False,
				),
				(
					"Invoice Item",
					"ITEM-001",
					"description",
					"Seats changed: 2 -> 5",
					False,
				),
				(
					"Invoice Item",
					"ITEM-002",
					"usage_record",
					"UR-002",
					False,
				),
				(
					"Invoice Item",
					"ITEM-002",
					"seat_change_log",
					"SEAT-LOG-002",
					False,
				),
				(
					"Invoice Item",
					"ITEM-002",
					"description",
					"Seats changed: 3 -> 4",
					False,
				),
			],
		)
