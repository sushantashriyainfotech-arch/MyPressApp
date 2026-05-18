from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowtime

SEAT_BILLING_SNAPSHOT_HOUR = 18
ACTIVE_USER_CACHE_TTL = 60 * 5


def is_seat_based_plan(plan: str | dict[str, Any] | None) -> bool:
	if not plan:
		return False

	if isinstance(plan, dict):
		return plan.get("billing_type") == "Seat Based"

	billing_type = frappe.db.get_value("Site Plan", plan, "billing_type")
	return billing_type == "Seat Based"


def get_plan_price_per_seat(plan: str | dict[str, Any] | None) -> float:
	if not plan:
		return 0.0

	if isinstance(plan, dict):
		price = plan.get("price_per_seat") or 0
	else:
		price = frappe.db.get_value("Site Plan", plan, "price_per_seat") or 0

	return flt(price, 2)


@frappe.whitelist()
def get_seat_pricing_preview(plan: str, seats: int = 1) -> dict[str, Any]:
	plan_doc = frappe.get_cached_doc("Site Plan", plan)
	if not is_seat_based_plan(plan_doc):
		return {
			"plan": plan_doc.name,
			"plan_title": getattr(plan_doc, "plan_title", None) or plan_doc.name,
			"billable_seats": cint(seats),
			"price_per_seat": get_plan_price_per_seat(plan_doc),
			"total_amount": flt(get_plan_price_per_seat(plan_doc) * cint(seats), 2),
		}

	return {
		"plan": plan_doc.name,
		"plan_title": getattr(plan_doc, "plan_title", None) or plan_doc.name,
		"billable_seats": cint(seats),
		"price_per_seat": get_plan_price_per_seat(plan_doc),
		"total_amount": flt(get_plan_price_per_seat(plan_doc) * cint(seats), 2),
		"min_seats": cint(getattr(plan_doc, "min_seats", 0) or 1),
		"max_seats": cint(getattr(plan_doc, "max_seats", 0) or 0),
		"next_plan": getattr(plan_doc, "next_plan", None),
	}


def get_currency_symbol(currency: str | None) -> str:
	return "₹" if currency == "INR" else "$"


def get_next_snapshot_date(moment: datetime | None = None):
	moment = moment or now_datetime()
	if moment.time() < time(SEAT_BILLING_SNAPSHOT_HOUR, 0):
		return moment.date()

	return getdate(moment.date()) + timedelta(days=1)


def get_billing_effective_from(moment: datetime | None = None):
	moment = moment or now_datetime()
	if moment.time() < time(SEAT_BILLING_SNAPSHOT_HOUR, 0):
		return getdate(moment.date())

	return getdate(moment.date()) + timedelta(days=1)


def _extract_users_from_analytics(analytics_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
	if not analytics_payload:
		return []

	analytics = analytics_payload.get("analytics")
	if isinstance(analytics, dict):
		users = analytics.get("users", [])
		return users if isinstance(users, list) else []

	users = analytics_payload.get("users", [])
	return users if isinstance(users, list) else []


def _get_site_analytics(site_name: str) -> dict[str, Any]:
	site = frappe.get_cached_doc("Site", site_name)
	analytics = site.fetch_analytics()
	if not analytics:
		frappe.throw(_("Could not verify active user count. Please try again."))

	return analytics


def get_active_user_count(site_name: str) -> int:
	cache_key = f"erpnext_saas_model:seat_billing:active_users:{site_name}"
	cached_value = frappe.cache().get_value(cache_key)
	if cached_value is not None:
		return cint(cached_value)

	try:
		analytics = _get_site_analytics(site_name)
		users = _extract_users_from_analytics(analytics)
		active_users = sum(1 for user in users if cint(user.get("enabled")))
	except Exception:
		frappe.throw(_("Could not verify active user count. Please try again."))

	frappe.cache().set_value(cache_key, active_users, expires_in_sec=ACTIVE_USER_CACHE_TTL)
	return active_users


def get_subscription_seat_context(subscription: str | dict[str, Any]) -> dict[str, Any]:
	if isinstance(subscription, dict):
		subscription_doc = subscription
	else:
		subscription_doc = frappe.get_cached_doc("Subscription", subscription).as_dict()

	plan = frappe.get_cached_doc(subscription_doc["plan_type"], subscription_doc["plan"])
	price_per_seat = flt(
		subscription_doc.get("price_per_seat") or get_plan_price_per_seat(plan), 2
	)
	billable_seats = cint(subscription_doc.get("billable_seats") or 0)
	total_amount = flt(price_per_seat * billable_seats, 2)

	return {
		"plan": plan,
		"billable_seats": billable_seats,
		"price_per_seat": price_per_seat,
		"total_amount": total_amount,
	}


def validate_seat_change(subscription: str | dict[str, Any], new_seats: int) -> dict[str, Any]:
	if isinstance(subscription, dict):
		subscription_doc = subscription
		subscription_name = subscription_doc["name"]
	else:
		subscription_name = subscription
		subscription_doc = frappe.get_cached_doc("Subscription", subscription_name).as_dict()

	plan = frappe.get_cached_doc(subscription_doc["plan_type"], subscription_doc["plan"])
	if not is_seat_based_plan(plan):
		return {
			"subscription": subscription_name,
			"billable_seats": cint(new_seats),
			"plan": plan.name,
			"price_per_seat": get_plan_price_per_seat(plan),
			"total_amount": flt(get_plan_price_per_seat(plan) * cint(new_seats), 2),
		}

	new_seats = cint(new_seats)
	min_seats = cint(getattr(plan, "min_seats", 0) or 1)
	if new_seats < min_seats:
		frappe.throw(_("You need at least {0} seats on this plan.").format(min_seats))

	max_seats = cint(getattr(plan, "max_seats", 0) or 0)
	if max_seats and new_seats > max_seats:
		return {
			"error_code": "SEATS_EXCEED_PLAN_LIMIT",
			"suggested_plan": getattr(plan, "next_plan", None),
			"message": _("Requested seats exceed the current plan limit."),
		}

	active_user_count = get_active_user_count(subscription_doc["site"])
	if new_seats < active_user_count:
		frappe.throw(
			_("You have {0} active users. Please deactivate users before reducing your seat count.").format(
				active_user_count
			)
		)

	price_per_seat = flt(subscription_doc.get("price_per_seat") or get_plan_price_per_seat(plan), 2)
	return {
		"subscription": subscription_name,
		"billable_seats": new_seats,
		"plan": plan.name,
		"price_per_seat": price_per_seat,
		"total_amount": flt(price_per_seat * new_seats, 2),
		"active_user_count": active_user_count,
	}


def log_seat_change(
	subscription: str,
	old_seats: int,
	new_seats: int,
	changed_by: str | None = None,
	access_updated_at: datetime | None = None,
	billing_effective_from=None,
	proration_amount: float | None = None,
):
	access_updated_at = access_updated_at or now_datetime()
	billing_effective_from = billing_effective_from or get_billing_effective_from(access_updated_at)
	subscription_doc = frappe.get_cached_doc("Subscription", subscription)
	seat_change = frappe.get_doc(
		{
			"doctype": "Seat Change Log",
			"subscription": subscription,
			"site": subscription_doc.site,
			"old_seats": cint(old_seats),
			"new_seats": cint(new_seats),
			"change_type": "Increase" if cint(new_seats) >= cint(old_seats) else "Decrease",
			"access_updated_at": access_updated_at,
			"billing_effective_from": billing_effective_from,
			"changed_by": changed_by or frappe.session.user,
			"change_date": access_updated_at,
			"proration_amount": proration_amount,
		}
	)
	seat_change.insert(ignore_permissions=True)
	return seat_change


def sync_site_access(subscription: str | dict[str, Any]):
	if isinstance(subscription, str):
		subscription_doc = frappe.get_cached_doc("Subscription", subscription)
	else:
		subscription_doc = frappe.get_cached_doc("Subscription", subscription.get("name"))

	if not subscription_doc.site:
		return

	try:
		site = frappe.get_cached_doc("Site", subscription_doc.site)
		if hasattr(site, "sync_users_to_product_site"):
			site.sync_users_to_product_site()
	except Exception:
		frappe.logger("erpnext_saas_model.seat_billing").warning(
			f"Failed to sync site access for subscription {subscription_doc.name}", exc_info=True
		)


def create_seat_usage_record(subscription: str | dict[str, Any], date=None, force: bool = False):
	if isinstance(subscription, str):
		subscription_doc = frappe.get_cached_doc("Subscription", subscription)
	else:
		subscription_doc = frappe.get_cached_doc("Subscription", subscription.get("name"))

	plan = frappe.get_cached_doc(subscription_doc.plan_type, subscription_doc.plan)
	if not is_seat_based_plan(plan):
		return None

	date = getdate(date or frappe.utils.today())
	if date == getdate() and not force and nowtime() < time(SEAT_BILLING_SNAPSHOT_HOUR, 0):
		return None

	if subscription_doc.is_usage_record_created(date):
		return None

	if date == getdate() and not force:
		backfill_missing_seat_usage_records(subscription_doc, date)

	return _insert_seat_usage_record(subscription_doc, date)


def backfill_missing_seat_usage_records(subscription, upto_date=None):
	subscription_doc = (
		frappe.get_cached_doc("Subscription", subscription)
		if isinstance(subscription, str)
		else frappe.get_cached_doc("Subscription", subscription.get("name"))
	)
	if not is_seat_based_plan(subscription_doc.plan):
		return []

	upto_date = getdate(upto_date or frappe.utils.today())
	cycle_start = getdate(frappe.utils.get_first_day(upto_date))
	existing_dates = set(
		getdate(date)
		for date in frappe.get_all(
			"Usage Record",
			filters={"subscription": subscription_doc.name, "date": ("between", (cycle_start, upto_date))},
			pluck="date",
		)
	)
	missing_dates = []
	current = cycle_start
	while current < upto_date:
		if current not in existing_dates:
			missing_dates.append(current)
		current = current + timedelta(days=1)

	if missing_dates:
		frappe.logger("erpnext_saas_model.seat_billing").warning(
			f"Backfilling {len(missing_dates)} seat usage record(s) for subscription {subscription_doc.name}"
		)

	for missing_date in missing_dates:
		_insert_seat_usage_record(subscription_doc, missing_date, backfill=True)

	return missing_dates


def create_seat_usage_records(date=None):
	date = getdate(date or frappe.utils.today())
	subscriptions = frappe.get_all(
		"Subscription",
		filters={"enabled": 1, "plan_type": "Site Plan"},
		pluck="name",
		order_by=None,
	)
	for name in subscriptions:
		subscription = frappe.get_cached_doc("Subscription", name)
		if not is_seat_based_plan(subscription.plan):
			continue
		try:
			subscription.create_usage_record(date=date)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.logger("erpnext_saas_model.seat_billing").error(
				f"Failed to create seat usage record for subscription {name}", exc_info=True
			)


@frappe.whitelist()
def change_subscription_seats(subscription: str, new_seats: int) -> dict[str, Any]:
	subscription_doc = frappe.get_cached_doc("Subscription", subscription)
	return subscription_doc.update_billable_seats(new_seats)


def _insert_seat_usage_record(subscription, date, backfill: bool = False):
	plan = frappe.get_cached_doc(subscription.plan_type, subscription.plan)
	price_per_seat = flt(subscription.price_per_seat or get_plan_price_per_seat(plan), 2)
	billable_seats = cint(subscription.billable_seats or 0)
	seat_amount = flt(price_per_seat * billable_seats, 2)
	snapshot_taken_at = now_datetime()

	usage_record = frappe.get_doc(
		{
			"doctype": "Usage Record",
			"team": subscription.team,
			"document_type": subscription.document_type,
			"document_name": subscription.document_name,
			"plan_type": subscription.plan_type,
			"plan": subscription.plan,
			"amount": seat_amount,
			"currency": frappe.get_cached_value("Team", subscription.team, "currency") or "INR",
			"date": date,
			"time": snapshot_taken_at.time().strftime("%H:%M:%S"),
			"subscription": subscription.name,
			"site": subscription.site,
			"billable_seats": billable_seats,
			"seat_amount": seat_amount,
			"snapshot_taken_at": snapshot_taken_at,
			"remark": "Seat billing snapshot" if not backfill else "Seat billing backfill snapshot",
		}
	)
	usage_record.insert(ignore_permissions=True)
	usage_record.submit()
	return usage_record
