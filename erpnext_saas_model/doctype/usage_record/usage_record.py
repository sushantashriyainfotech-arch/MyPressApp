from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

from press.press.doctype.usage_record.usage_record import UsageRecord as PressUsageRecord

from erpnext_saas_model.seat_billing import is_seat_based_plan


class UsageRecord(PressUsageRecord):
	def validate(self):
		super().validate()
		if not self.plan:
			return

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			return

		if not getattr(self, "snapshot_taken_at", None):
			self.snapshot_taken_at = now_datetime()

		if not cint(getattr(self, "billable_seats", 0) or 0):
			self.billable_seats = 1

	def validate_duplicate_usage_record(self):
		# Keep Press behavior, but do not key duplicates off amount.
		if self.document_type == "Server":
			is_primary = frappe.db.get_value("Server", self.document_name, "is_primary")
			if not is_primary:
				return

		usage_record = frappe.get_all(
			"Usage Record",
			{
				"name": ("!=", self.name),
				"team": self.team,
				"document_type": self.document_type,
				"document_name": self.document_name,
				"interval": self.interval,
				"date": self.date,
				"plan": self.plan,
				"docstatus": 1,
				"subscription": self.subscription,
			},
			pluck="name",
		)

		if usage_record:
			frappe.throw(
				f"Usage Record {usage_record[0]} already exists for this document",
				frappe.DuplicateEntryError,
			)
