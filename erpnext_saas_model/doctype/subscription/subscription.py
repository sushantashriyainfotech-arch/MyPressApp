from __future__ import annotations


import frappe
from frappe.utils import cint, flt, now_datetime
from erpnext_saas_model.doctype.subscription.log_subscription_seat_debug import _log_subscription_seat_debug

from press.press.doctype.subscription.subscription import Subscription as PressSubscription

from erpnext_saas_model.seat_billing import (
	backfill_missing_seat_usage_records,
	create_seat_usage_record,
	get_billing_effective_from,
	get_plan_price_for_currency,
	get_plan_total_price,
	get_subscription_seat_context,
	is_seat_based_plan,
	get_site_user_active_count,
	get_team_currency,
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
		Allows downgrades only when the site's active users fit within the
		requested seat count, while never allowing the count to fall below the
		plan minimum.
		"""
		current_seats = cint(getattr(self, "billable_seats", 0) or 0)
		seed_seats = self._get_seed_billable_seats(plan)
		min_seats = cint(getattr(plan, "min_seats", 0) or 1)
		requested_seats = current_seats or seed_seats

		if requested_seats < min_seats:
			frappe.throw(f"You need at least {min_seats} seats on this plan.")

		site_name = getattr(self, "site", None) or (
			self.document_name if getattr(self, "document_type", None) == "Site" else None
		)
		active_user_count = get_site_user_active_count(site_name) if site_name else 0
		if site_name and active_user_count > requested_seats:
			frappe.throw(
				"Please deactivate users before reducing your seat count. "
				f"You currently have {active_user_count} active users, but the requested seat count is {requested_seats}."
			)

		return requested_seats

	def _get_currency_prices(self, plan) -> tuple[str, float, float, float]:
		"""Return the team currency, both plan prices, and the selected seat price."""
		team_currency = get_team_currency(getattr(self, "team", None))
		price_inr = flt(getattr(plan, "price_inr", 0) or 0, 2)
		price_usd = flt(getattr(plan, "price_usd", 0) or 0, 2)
		selected_price = get_plan_price_for_currency(plan, team_currency)
		return team_currency, price_inr, price_usd, selected_price

	def _clear_seat_billing_fields(self, plan=None) -> None:
		"""Reset seat-billing fields when the subscription is no longer seat-based."""
		self.billable_seats = 1
		self.price_inr = 0
		self.price_usd = 0
		self.price_per_seat = 0
		self.total_amount = get_plan_total_price(plan) if plan else 0
		self.seats_last_updated = now_datetime()

	def _sync_linked_site_billable_seats(self, plan) -> None:
		"""Persist the current seat count onto the linked Site before parent sync runs."""
		site_name = getattr(self, "site", None) or (
			self.document_name if getattr(self, "document_type", None) == "Site" else None
		)
		if not site_name:
			_log_subscription_seat_debug(
				"sync_site_billable_seats.skipped",
				{"subscription": self.name, "reason": "NO_SITE_LINKED"},
			)
			return

		if not is_seat_based_plan(plan):
			_log_subscription_seat_debug(
				"sync_site_billable_seats.skipped",
				{
					"subscription": self.name,
					"site": site_name,
					"reason": "RESOURCE_BASED",
				},
			)
			return

		current_seats = cint(getattr(self, "billable_seats", 0) or 0)
		previous_site_seats = cint(frappe.db.get_value("Site", site_name, "billable_seats") or 0)
		frappe.db.set_value("Site", site_name, "billable_seats", current_seats, update_modified=False)
		_log_subscription_seat_debug(
			"sync_site_billable_seats.updated",
			{
				"subscription": self.name,
				"site": site_name,
				"previous_site_billable_seats": previous_site_seats,
				"current_subscription_billable_seats": current_seats,
			},
		)

	def before_validate(self):
		"""
		Preprocessing before standard validation.
		- Ensures seat-based plans have a billable_seats count.
		- Fetches and sets the latest INR/USD plan prices.
		- Calculates the total_amount from the team's selected currency.
		"""
		super().before_validate()
		_log_subscription_seat_debug(
			"before_validate.start",
			{
				"subscription": self.name,
				"plan_type": getattr(self, "plan_type", None),
				"plan": getattr(self, "plan", None),
				"billable_seats": getattr(self, "billable_seats", None),
				"document_type": getattr(self, "document_type", None),
				"document_name": getattr(self, "document_name", None),
			},
		)
		if not self.plan:
			_log_subscription_seat_debug(
				"before_validate.skip",
				{"subscription": self.name, "reason": "NO_PLAN"},
			)
			return

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			_log_subscription_seat_debug(
				"before_validate.skip",
				{
					"subscription": self.name,
					"plan": self.plan,
					"reason": "RESOURCE_BASED",
				},
			)
			self._clear_seat_billing_fields(plan)
			return

		# Keep subscription seats at or above the site's billed seat count
		self.billable_seats = self._get_effective_billable_seats(plan)
		team_currency, price_inr, price_usd, selected_price = self._get_currency_prices(plan)

		self.price_inr = price_inr
		self.price_usd = price_usd
		self.price_per_seat = selected_price
		self.total_amount = flt(cint(self.billable_seats) * flt(selected_price or 0, 2), 2)
		self.seats_last_updated = getattr(self, "seats_last_updated", None) or now_datetime()
		_log_subscription_seat_debug(
			"before_validate.complete",
			{
				"subscription": self.name,
				"plan": self.plan,
				"billable_seats": self.billable_seats,
				"team_currency": team_currency,
				"price_inr": self.price_inr,
				"price_usd": self.price_usd,
				"selected_price": selected_price,
				"total_amount": self.total_amount,
				"seats_last_updated": self.seats_last_updated,
			},
		)

	def validate(self):
		"""
		Main validation logic for seat boundaries.
		- Enforces minimum and maximum seats defined in the Site Plan.
		- Finalizes the total_amount calculation.
		"""
		super().validate()
		_log_subscription_seat_debug(
			"validate.start",
			{
				"subscription": self.name,
				"plan_type": getattr(self, "plan_type", None),
				"plan": getattr(self, "plan", None),
				"billable_seats": getattr(self, "billable_seats", None),
			},
		)
		if not self.plan:
			_log_subscription_seat_debug(
				"validate.skip",
				{"subscription": self.name, "reason": "NO_PLAN"},
			)
			return

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			_log_subscription_seat_debug(
				"validate.skip",
				{
					"subscription": self.name,
					"plan": self.plan,
					"reason": "RESOURCE_BASED",
				},
			)
			return

		min_seats = cint(getattr(plan, "min_seats", 0) or 1)
		max_seats = cint(getattr(plan, "max_seats", 0) or 0)
		
		# Ensure seat count stays within plan boundaries and doesn't fall behind the site state
		self.billable_seats = self._get_effective_billable_seats(plan)
		team_currency, price_inr, price_usd, selected_price = self._get_currency_prices(plan)
		_log_subscription_seat_debug(
			"validate.compare",
			{
				"subscription": self.name,
				"plan": self.plan,
				"plan_min_seats": min_seats,
				"plan_max_seats": max_seats,
				"billable_seats": self.billable_seats,
				"team_currency": team_currency,
				"price_inr": price_inr,
				"price_usd": price_usd,
				"selected_price": selected_price,
				"site_billable_seats": frappe.db.get_value(
					"Site", self.document_name, "billable_seats"
				)
				if getattr(self, "document_type", None) == "Site" and getattr(self, "document_name", None)
				else None,
			},
		)
		if self.billable_seats < min_seats:
			_log_subscription_seat_debug(
				"validate.block",
				{
					"subscription": self.name,
					"plan": self.plan,
					"billable_seats": self.billable_seats,
					"plan_min_seats": min_seats,
					"site_billable_seats": frappe.db.get_value(
						"Site", self.document_name, "billable_seats"
					)
					if getattr(self, "document_type", None) == "Site" and getattr(self, "document_name", None)
					else None,
				},
				{"can_save": False, "reason": "BELOW_MIN_SEATS"},
				status="warning",
			)
			frappe.throw(f"You need at least {min_seats} seats on this plan.")

		if max_seats and self.billable_seats > max_seats:
			_log_subscription_seat_debug(
				"validate.block",
				{
					"subscription": self.name,
					"plan": self.plan,
					"billable_seats": self.billable_seats,
					"plan_max_seats": max_seats,
				},
				{"can_save": False, "reason": "ABOVE_MAX_SEATS"},
				status="warning",
			)
			frappe.throw(f"This plan allows a maximum of {max_seats} seats.")

		self.price_inr = price_inr
		self.price_usd = price_usd
		self.price_per_seat = selected_price
		self.total_amount = flt(cint(self.billable_seats) * flt(selected_price or 0, 2), 2)
		_log_subscription_seat_debug(
			"validate.complete",
			{
				"subscription": self.name,
				"plan": self.plan,
				"billable_seats": self.billable_seats,
				"team_currency": team_currency,
				"price_inr": self.price_inr,
				"price_usd": self.price_usd,
				"selected_price": selected_price,
				"total_amount": self.total_amount,
			},
		)

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
		if not self.plan:
			super().on_update()
			return

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if is_seat_based_plan(plan):
			self._sync_linked_site_billable_seats(plan)

		super().on_update()
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
		self.price_inr = flt(result.get("price_inr") or 0, 2)
		self.price_usd = flt(result.get("price_usd") or 0, 2)
		self.price_per_seat = flt(result.get("selected_price") or result.get("price_per_seat") or 0, 2)
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
			"price_inr": self.price_inr,
			"price_usd": self.price_usd,
			"selected_price": self.price_per_seat,
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
