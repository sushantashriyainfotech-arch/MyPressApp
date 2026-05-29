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

		if not getattr(self, "seat_amount", None):
			self.seat_amount = self.amount
		if not getattr(self, "amount", None):
			self.amount = self.seat_amount
