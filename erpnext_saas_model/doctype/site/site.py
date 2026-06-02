from __future__ import annotations

import frappe
from frappe.utils import cint

from press.api.client import dashboard_whitelist
from press.press.doctype.site.site import Site as PressSite

from erpnext_saas_model.seat_billing import (
	is_seat_based_plan,
	sync_site_users_from_analytics,
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
			self._throw_plan_limit_error(validation)

	def _set_billable_seats(self, billable_seats: int) -> int:
		"""Persist the current site seat count without triggering a full plan change."""
		self.billable_seats = cint(billable_seats)
		if self.name:
			frappe.db.set_value(
				"Site",
				self.name,
				"billable_seats",
				self.billable_seats,
				update_modified=False,
			)
		return self.billable_seats

	# @property
	# def subscription(self):
	# 	"""
	# 	Resolve the linked subscription in a stable order.
	# 	Prefer the explicit `Subscription.site` link when present, then fall back
	# 	to the historical Site linkage used by older records.
	# 	"""
	# 	lookups = (
	# 		{"site": self.name, "document_type": "Site"},
	# 		{"document_type": "Site", "document_name": self.name, "team": self.team},
	# 		{"document_type": "Site", "document_name": self.name},
	# 	)
	# 	for filters in lookups:
	# 		subscription_name = frappe.db.get_value(
	# 			"Subscription",
	# 			filters,
	# 			"name",
	# 			order_by="modified desc",
	# 		)
	# 		if subscription_name:
	# 			return frappe.get_doc("Subscription", subscription_name)
	# 	return None

	def _throw_plan_limit_error(self, validation: dict) -> None:
		"""Raise the user-facing plan upgrade hint when seat count exceeds the plan."""
		suggested_plan = validation.get("suggested_plan")
		if suggested_plan:
			frappe.throw(
				f"Requested seats exceed the current plan limit. Please choose {suggested_plan} or fewer seats."
			)
		frappe.throw(validation.get("message") or "Requested seats exceed the current plan limit.")

	def _update_seat_count_for_current_plan(self, requested_seats: int):
		"""Handle seat-only changes without involving the Press plan-change workflow."""
		subscription_name = getattr(self, "subscription", None)
		if not subscription_name:
			return {"billable_seats": requested_seats}

		subscription = frappe.get_doc("Subscription", subscription_name)
		if getattr(subscription, "team", None) != getattr(self, "team", None):
			frappe.throw("The linked subscription does not belong to this site team.")
		if getattr(subscription, "site", None) and getattr(subscription, "site", None) != self.name:
			frappe.throw("The linked subscription does not belong to this site.")
		return subscription.update_billable_seats(requested_seats)

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

			requested_seats = cint(billable_seats)
			validation = validate_seat_selection_for_plan(self.name, plan_doc, requested_seats)
			if validation.get("error_code") == "SEATS_EXCEED_PLAN_LIMIT":
				self._throw_plan_limit_error(validation)

			current_plan = getattr(self, "subscription_plan", None) or getattr(self, "plan", None)
			current_seats = cint(getattr(self, "billable_seats", 0) or 0)
			self._set_billable_seats(requested_seats)

			if current_plan == plan:
				if current_seats == requested_seats:
					return validation

				return self._update_seat_count_for_current_plan(requested_seats)

			result = self.change_plan(plan)
			return result

		if billable_seats is not None and self.name:
			self._set_billable_seats(billable_seats)

		return super().set_plan(plan)

	def sync_users_to_product_site(self, analytics=None):
		"""
		Sync enabled users from the product site while honoring billable-seat limits.
		"""
		if self.is_standby:
			return

		if not analytics:
			analytics = self.fetch_analytics()

		if analytics:
			sync_site_users_from_analytics(self.name, analytics)
