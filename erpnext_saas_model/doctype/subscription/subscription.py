from __future__ import annotations

import frappe
from frappe.utils import cint, flt, now_datetime

from press.press.doctype.subscription.subscription import Subscription as PressSubscription

from erpnext_saas_model.seat_billing import (
	backfill_missing_seat_usage_records,
	create_seat_usage_record,
	get_billing_effective_from,
	get_plan_price_per_seat,
	get_plan_total_price,
	get_subscription_seat_context,
	is_seat_based_plan,
	get_site_user_active_count,
	log_seat_change,
	sync_site_access,
	validate_seat_change,
)


class Subscription(PressSubscription):
	"""
	Extended Subscription controller for seat-based billing modeling.
	Overrides base PressSubscription to handle seat count validation, 
	usage recording, and billing calculations.
	"""

	def _get_seed_billable_seats(self, plan) -> int:
		"""
		Helper to determine the initial seat count for a subscription.
		Checks the linked Site first, otherwise defaults to the Plan's minimum seats.
		"""
		site_billable_seats = 0
		if getattr(self, "document_type", None) == "Site" and getattr(self, "document_name", None):
			site_billable_seats = cint(
				frappe.db.get_value("Site", self.document_name, "billable_seats") or 0
			)

		if site_billable_seats:
			return site_billable_seats

		return cint(getattr(plan, "min_seats", 0) or 1)

	def _get_effective_billable_seats(self, plan) -> int:
		"""
		Returns the seat count that should be enforced for this subscription.
		Prioritizes the existing subscription value, but never allows it to fall
		below the site's current billed seats or the plan minimum.
		"""
		current_seats = cint(getattr(self, "billable_seats", 0) or 0)
		seed_seats = self._get_seed_billable_seats(plan)
		return max(current_seats, seed_seats)

	def _clear_seat_billing_fields(self, plan=None) -> None:
		"""Reset seat-billing fields when the subscription is no longer seat-based."""
		self.billable_seats = 1
		self.price_per_seat = 0
		self.total_amount = get_plan_total_price(plan) if plan else 0
		self.seats_last_updated = now_datetime()

	def before_validate(self):
		"""
		Preprocessing before standard validation.
		- Ensures seat-based plans have a billable_seats count.
		- Fetches and sets the latest price_per_seat from the Plan.
		- Calculates the total_amount (billable_seats * price_per_seat).
		"""
		super().before_validate()
		if not self.plan:
			return

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			self._clear_seat_billing_fields(plan)
			return

		# Keep subscription seats at or above the site's billed seat count
		self.billable_seats = self._get_effective_billable_seats(plan)

		# Sync price per seat from plan if not explicitly set
		if not getattr(self, "price_per_seat", None):
			self.price_per_seat = get_plan_price_per_seat(plan)

		# Calculate total subscription amount
		self.total_amount = flt(cint(self.billable_seats) * flt(self.price_per_seat or 0, 2), 2)
		self.seats_last_updated = getattr(self, "seats_last_updated", None) or now_datetime()

	def validate(self):
		"""
		Main validation logic for seat boundaries.
		- Enforces minimum and maximum seats defined in the Site Plan.
		- Finalizes the total_amount calculation.
		"""
		super().validate()
		if not self.plan:
			return

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			return

		min_seats = cint(getattr(plan, "min_seats", 0) or 1)
		max_seats = cint(getattr(plan, "max_seats", 0) or 0)
		
		# Ensure seat count stays within plan boundaries and doesn't fall behind the site state
		self.billable_seats = self._get_effective_billable_seats(plan)
		if self.billable_seats < min_seats:
			frappe.throw(f"You need at least {min_seats} seats on this plan.")

		if max_seats and self.billable_seats > max_seats:
			frappe.throw(f"This plan allows a maximum of {max_seats} seats.")

		if not getattr(self, "price_per_seat", None):
			self.price_per_seat = get_plan_price_per_seat(plan)

		self.total_amount = flt(cint(self.billable_seats) * flt(self.price_per_seat or 0, 2), 2)

	def before_save(self):
		"""
		Captures the previous seat count before saving.
		Used in on_update to detect if a change occurred that needs logging.
		"""
		if self.is_new():
			self._previous_billable_seats = None
			return
		self._previous_billable_seats = cint(
			frappe.db.get_value("Subscription", self.name, "billable_seats") or 0
		)

	def on_update(self):
		"""
		Post-save triggers for seat changes.
		- Logs any change in seat count for billing audit.
		- Synchronizes seat access (permissions/limits) to the underlying site.
		"""
		super().on_update()
		if not self.plan:
			return

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			return

		previous = getattr(self, "_previous_billable_seats", None)
		current = cint(getattr(self, "billable_seats", 0) or 0)
		
		# Only act if seats actually changed and logging isn't skipped
		if previous is None or previous == current:
			return

		if getattr(self.flags, "skip_seat_change_log", False):
			return

		# Log the transition for retroactive/pro-rated billing calculations
		log_seat_change(
			subscription=self.name,
			old_seats=previous,
			new_seats=current,
			changed_by=frappe.session.user,
			access_updated_at=now_datetime(),
			billing_effective_from=get_billing_effective_from(),
		)
		sync_site_access(self)

	@frappe.whitelist()
	def create_usage_record(self, date=None):
		"""
		Daily billing snapshot record (Usage Record).
		- Overrides base to handle seat-based metrics.
		- Site usage is captured via a snapshot at approximately 6 PM.
		"""
		if not self.plan:
			return super().create_usage_record(date=date)

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			return super().create_usage_record(date=date)

		date = frappe.utils.getdate(date or frappe.utils.today())
		
		# Standard Press usage collection happens once a day (after 6 PM)
		if date == frappe.utils.getdate() and frappe.utils.now_datetime().time().hour < 18:
			return None

		if date == frappe.utils.getdate():
			# Ensure we have all necessary seat logs before creating the final daily record
			backfill_missing_seat_usage_records(self, date)

		return create_seat_usage_record(self, date=date, force=True)
	
	@frappe.whitelist()
	def update_billable_seats(self, new_seats: int):
		"""
		Whitelisted API method to update seat count from the frontend/dashboard.
		- Validates the new count against plan limits.
		- Updates the subscription and recalculates pricing.
		- Returns a summary of the change to the user.
		"""
		result = validate_seat_change(self.name, new_seats)
		if result.get("error_code") == "SEATS_EXCEED_PLAN_LIMIT":
			return result

		self.flags.skip_seat_change_log = True # Prevent duplicate logging (one here, one in on_update)
		old_seats = cint(getattr(self, "billable_seats", 0) or 0)
		self.billable_seats = cint(result["billable_seats"])
		self.price_per_seat = flt(result["price_per_seat"], 2)
		self.total_amount = flt(result["total_amount"], 2)
		self.seats_last_updated = now_datetime()
		self.save(ignore_permissions=True)
		self.flags.skip_seat_change_log = False

		# Explicitly log the change and sync access
		log_seat_change(
			subscription=self.name,
			old_seats=old_seats,
			new_seats=self.billable_seats,
			changed_by=frappe.session.user,
			access_updated_at=self.seats_last_updated,
			billing_effective_from=get_billing_effective_from(self.seats_last_updated),
		)
		sync_site_access(self)
		
		return {
			"subscription": self.name,
			"billable_seats": self.billable_seats,
			"price_per_seat": self.price_per_seat,
			"total_amount": self.total_amount,
			"message": (
				f"Your seat count has been updated to {self.billable_seats}. "
				f"Billing will reflect this change from the next 6 PM snapshot."
			),
		}

	def get_active_user_count(self) -> int:
		"""Returns the count of enabled users on the linked Site."""
		site_name = self.site or (self.document_name if self.document_type == "Site" else None)
		if not site_name:
			return 0
		return get_site_user_active_count(site_name)

	def get_seat_context(self) -> dict[str, object]:
		"""Fetches metadata required for seat selection UI (plan limits, current count, etc.)."""
		return get_subscription_seat_context(self.name)
