from __future__ import annotations

import frappe
from frappe.utils import cint

from press.api.client import dashboard_whitelist
from press.press.doctype.site.site import Site as PressSite

from erpnext_saas_model.seat_billing import (
	is_seat_based_plan,
	validate_seat_selection_for_plan,
)


class Site(PressSite):
	"""
	Extended Site controller for seat-based billing modeling.
	Overrides base Press Site to handle seat count validation during 
	site creation and plan updates.
	"""

	def validate(self):
		"""
		Enforces seat-based billing rules during site validation.
		- Checks if the selected plan is seat-based.
		- Validates the requested billable_seats against plan minimums.
		- Throws an error if seats exceed the current plan's hard limit.
		"""
		super().validate()

		plan_name = getattr(self, "subscription_plan", None) or getattr(self, "plan", None)
		if not plan_name:
			return

		plan = frappe.get_cached_doc("Site Plan", plan_name)
		if not is_seat_based_plan(plan):
			return

		# Default to plan's minimum seats if not specified
		requested_seats = cint(getattr(self, "billable_seats", 0) or 0)
		if not requested_seats:
			requested_seats = cint(getattr(plan, "min_seats", 0) or 1)

		self.billable_seats = requested_seats
		
		# Cross-verify with plan configuration
		validation = validate_seat_selection_for_plan(None, plan, requested_seats)
		if validation.get("error_code") == "SEATS_EXCEED_PLAN_LIMIT":
			suggested_plan = validation.get("suggested_plan")
			if suggested_plan:
				frappe.throw(
					f"Requested seats exceed the current plan limit. Please choose {suggested_plan} or fewer seats."
				)
			frappe.throw(validation.get("message") or "Requested seats exceed the current plan limit.")

	@dashboard_whitelist()
	def set_plan(
		self,
		plan: None | str = None,
		billable_seats: int | None = None,
		price_usd: float | None = None,
	):
		"""
		Helper to update both the plan and the billable seat count atomically.
		Updates the database directly for immediate reflection in the UI.
		"""
		plan_doc = frappe.get_cached_doc("Site Plan", plan) if plan else None
		if plan_doc and is_seat_based_plan(plan_doc):
			if billable_seats is None:
				billable_seats = cint(getattr(self, "billable_seats", 0) or getattr(plan_doc, "min_seats", 1))

			if billable_seats is not None and self.name:
				self.billable_seats = cint(billable_seats)
			result = self.change_plan(plan)
			if billable_seats is not None and self.name:
				frappe.db.set_value(
					"Site",
					self.name,
					"billable_seats",
					self.billable_seats,
					update_modified=False,
				)
			return result

		if billable_seats is not None and self.name:
			self.billable_seats = cint(billable_seats)
			frappe.db.set_value(
				"Site",
				self.name,
				"billable_seats",
				self.billable_seats,
				update_modified=False,
			)

		return super().set_plan(plan)
