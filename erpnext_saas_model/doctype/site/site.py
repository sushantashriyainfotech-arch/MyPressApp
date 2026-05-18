from __future__ import annotations

import frappe
from frappe.utils import cint

from press.press.doctype.site.site import Site as PressSite

from erpnext_saas_model.seat_billing import (
	is_seat_based_plan,
	validate_seat_selection_for_plan,
)


class Site(PressSite):
	def validate(self):
		super().validate()

		plan_name = getattr(self, "subscription_plan", None) or getattr(self, "plan", None)
		if not plan_name:
			return

		plan = frappe.get_cached_doc("Site Plan", plan_name)
		if not is_seat_based_plan(plan):
			return

		requested_seats = cint(getattr(self, "billable_seats", 0) or 0)
		if not requested_seats:
			requested_seats = cint(getattr(plan, "min_seats", 0) or 1)

		self.billable_seats = requested_seats
		validation = validate_seat_selection_for_plan(None, plan, requested_seats)
		if validation.get("error_code") == "SEATS_EXCEED_PLAN_LIMIT":
			suggested_plan = validation.get("suggested_plan")
			if suggested_plan:
				frappe.throw(
					f"Requested seats exceed the current plan limit. Please choose {suggested_plan} or fewer seats."
				)
			frappe.throw(validation.get("message") or "Requested seats exceed the current plan limit.")

	def set_plan(self, plan: None | str = None, billable_seats: int | None = None):
		if billable_seats is not None and self.name:
			self.billable_seats = cint(billable_seats)
			frappe.db.set_value("Site", self.name, "billable_seats", self.billable_seats)

		return super().set_plan(plan)
