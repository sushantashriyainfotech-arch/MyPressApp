from __future__ import annotations

import frappe
from frappe.utils import cint, flt, now_datetime

from press.press.doctype.subscription.subscription import Subscription as PressSubscription

from erpnext_saas_model.seat_billing import (
	backfill_missing_seat_usage_records,
	create_seat_usage_record,
	get_active_user_count,
	get_billing_effective_from,
	get_plan_price_per_seat,
	get_subscription_seat_context,
	is_seat_based_plan,
	log_seat_change,
	sync_site_access,
	validate_seat_change,
)


class Subscription(PressSubscription):
	def _get_seed_billable_seats(self, plan) -> int:
		site_billable_seats = 0
		if getattr(self, "document_type", None) == "Site" and getattr(self, "document_name", None):
			site_billable_seats = cint(
				frappe.db.get_value("Site", self.document_name, "billable_seats") or 0
			)

		if site_billable_seats:
			return site_billable_seats

		return cint(getattr(plan, "min_seats", 0) or 1)

	def before_validate(self):
		super().before_validate()
		if not self.plan:
			return

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			return

		if not cint(getattr(self, "billable_seats", 0) or 0):
			self.billable_seats = self._get_seed_billable_seats(plan)

		if not getattr(self, "price_per_seat", None):
			self.price_per_seat = get_plan_price_per_seat(plan)

		self.total_amount = flt(cint(self.billable_seats) * flt(self.price_per_seat or 0, 2), 2)
		self.seats_last_updated = getattr(self, "seats_last_updated", None) or now_datetime()

	def validate(self):
		super().validate()
		if not self.plan:
			return

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			return

		min_seats = cint(getattr(plan, "min_seats", 0) or 1)
		max_seats = cint(getattr(plan, "max_seats", 0) or 0)
		self.billable_seats = cint(getattr(self, "billable_seats", 0) or self._get_seed_billable_seats(plan))
		if self.billable_seats < min_seats:
			frappe.throw(f"You need at least {min_seats} seats on this plan.")

		if max_seats and self.billable_seats > max_seats:
			frappe.throw(f"This plan allows a maximum of {max_seats} seats.")

		if not getattr(self, "price_per_seat", None):
			self.price_per_seat = get_plan_price_per_seat(plan)

		self.total_amount = flt(cint(self.billable_seats) * flt(self.price_per_seat or 0, 2), 2)

	def before_save(self):
		if self.is_new():
			self._previous_billable_seats = None
			return
		self._previous_billable_seats = cint(
			frappe.db.get_value("Subscription", self.name, "billable_seats") or 0
		)

	def on_update(self):
		super().on_update()
		if not self.plan:
			return

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			return

		previous = getattr(self, "_previous_billable_seats", None)
		current = cint(getattr(self, "billable_seats", 0) or 0)
		if previous is None or previous == current:
			return

		if getattr(self.flags, "skip_seat_change_log", False):
			return

		log_seat_change(
			subscription=self.name,
			old_seats=previous,
			new_seats=current,
			changed_by=frappe.session.user,
			access_updated_at=now_datetime(),
			billing_effective_from=get_billing_effective_from(),
		)
		sync_site_access(self)

	def create_usage_record(self, date=None):  # noqa: C901
		if not self.plan:
			return super().create_usage_record(date=date)

		plan = frappe.get_cached_doc(self.plan_type, self.plan)
		if not is_seat_based_plan(plan):
			return super().create_usage_record(date=date)

		if not date:
			return None

		date = frappe.utils.getdate(date)
		if date == frappe.utils.getdate() and frappe.utils.now_datetime().time().hour < 18:
			return None

		if date == frappe.utils.getdate():
			backfill_missing_seat_usage_records(self, date)

		return create_seat_usage_record(self, date=date, force=True)

	def update_billable_seats(self, new_seats: int):
		result = validate_seat_change(self.name, new_seats)
		if result.get("error_code") == "SEATS_EXCEED_PLAN_LIMIT":
			return result

		self.flags.skip_seat_change_log = True
		old_seats = cint(getattr(self, "billable_seats", 0) or 0)
		self.billable_seats = cint(result["billable_seats"])
		self.price_per_seat = flt(result["price_per_seat"], 2)
		self.total_amount = flt(result["total_amount"], 2)
		self.seats_last_updated = now_datetime()
		self.save(ignore_permissions=True)
		self.flags.skip_seat_change_log = False

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
		if not self.site:
			return 0
		return get_active_user_count(self.site)

	def get_seat_context(self) -> dict[str, object]:
		return get_subscription_seat_context(self.name)
