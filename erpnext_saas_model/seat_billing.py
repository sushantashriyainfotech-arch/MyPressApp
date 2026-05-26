from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowtime

SEAT_BILLING_SNAPSHOT_HOUR = 18
ACTIVE_USER_CACHE_TTL = 60 * 5


def is_seat_based_plan(plan: str | dict[str, Any] | None) -> bool:
	"""
	Checks if a given Site Plan follows a 'Seat Based' billing model.
	"""
	if not plan:
		return False

	if isinstance(plan, dict):
		return plan.get("billing_type") == "Seat Based"

	billing_type = frappe.db.get_value("Site Plan", plan, "billing_type")
	return billing_type == "Seat Based"


def get_plan_price_per_seat(plan: str | dict[str, Any] | None) -> float:
	"""
	Fetches the configured price per seat for a specific Site Plan.
	Defaults to 0.0 if not found.
	"""
	if not plan:
		return 0.0

	if isinstance(plan, dict):
		price = plan.get("price_per_seat") or 0
	else:
		price = frappe.db.get_value("Site Plan", plan, "price_per_seat") or 0

	return flt(price, 2)


def get_seat_plans() -> list[dict[str, Any]]:
	"""
	Returns a list of all enabled Site Plans that use seat-based billing.
	Ordered by price (ascending).
	"""
	return frappe.get_all(
		"Site Plan",
		filters={"enabled": 1, "billing_type": "Seat Based"},
		fields=["name", "plan_title", "price_per_seat", "min_seats", "max_seats", "next_plan"],
		order_by="price_per_seat asc, name asc",
	)


def get_seat_change_logs(subscription: str, limit: int = 10) -> list[dict[str, Any]]:
	"""
	Fetches recent audit logs for seat count changes on a specific subscription.
	"""
	return frappe.get_all(
		"Seat Change Log",
		filters={"subscription": subscription},
		fields=[
			"name",
			"old_seats",
			"new_seats",
			"change_type",
			"access_updated_at",
			"billing_effective_from",
			"changed_by",
			"change_date",
		],
		order_by="creation desc",
		limit=limit,
	)


def get_seat_billing_dashboard(subscription: str | None = None) -> dict[str, Any]:
	"""
	Collects all data required for the Seat Billing Dashboard view.
	Returns active subscriptions, available plans, and historical logs.
	"""
	subscriptions = frappe.get_all(
		"Subscription",
		filters={"plan_type": "Site Plan"},
		fields=[
			"name",
			"site",
			"plan",
			"plan_type",
			"enabled",
			"billable_seats",
			"price_per_seat",
			"total_amount",
			"seats_last_updated",
		],
		order_by="modified desc",
	)
	plans = get_seat_plans()

	selected_subscription = subscription
	if not selected_subscription and subscriptions:
		selected_subscription = subscriptions[0]["name"]

	current = None
	logs = []
	active_user_count = 0
	if selected_subscription:
		try:
			# Gather context for the currently viewed subscription
			current = get_subscription_seat_context(selected_subscription)
			current["name"] = selected_subscription
			current["subscription"] = frappe.get_doc("Subscription", selected_subscription).as_dict()
			active_user_count = get_active_user_count(current["subscription"]["site"]) if current["subscription"].get("site") else 0
			logs = get_seat_change_logs(selected_subscription, limit=10)
		except Exception:
			current = None

	return {
		"subscriptions": subscriptions,
		"plans": plans,
		"current": current,
		"active_user_count": active_user_count,
		"logs": logs,
	}


@frappe.whitelist()
def get_seat_pricing_preview(plan: str, seats: int = 1) -> dict[str, Any]:
	"""
	API method to calculate pricing for a plan/seat combination without saving.
	Used by frontend UI for real-time cost estimation.
	"""
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
	"""Returns the symbol for the team's currency."""
	return "₹" if currency == "INR" else "$"


def get_next_snapshot_date(moment: datetime | None = None):
	"""
	Determines the date of the next billing snapshot.
	Snapshots happen daily at 6 PM (18:00).
	"""
	moment = moment or now_datetime()
	if moment.time() < time(SEAT_BILLING_SNAPSHOT_HOUR, 0):
		return moment.date()

	return getdate(moment.date()) + timedelta(days=1)


def get_billing_effective_from(moment: datetime | None = None):
	"""
	Determines when a seat change should start being billed.
	Changes made after 6 PM take effect from the next day's snapshot.
	"""
	moment = moment or now_datetime()
	if moment.time() < time(SEAT_BILLING_SNAPSHOT_HOUR, 0):
		return getdate(moment.date())

	return getdate(moment.date()) + timedelta(days=1)


def _extract_users_from_analytics(analytics_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
	"""Internal helper to parse user lists from Site Analytics data."""
	if not analytics_payload:
		return []

	analytics = analytics_payload.get("analytics")
	if isinstance(analytics, dict):
		users = analytics.get("users", [])
		return users if isinstance(users, list) else []

	users = analytics_payload.get("users", [])
	return users if isinstance(users, list) else []


def _get_site_analytics(site_name: str) -> dict[str, Any]:
	"""Fetches real-time site analytics (including user state) from the Press Agent."""
	site = frappe.get_cached_doc("Site", site_name)
	analytics = site.fetch_analytics()
	if not analytics:
		frappe.throw(_("Could not verify active user count. Please try again."))

	return analytics


def get_active_user_count(site_name: str) -> int:
	"""
	Queries the site to count 'enabled' users.
	Results are cached for ACTIVE_USER_CACHE_TTL to improve UI performance.
	"""
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
	"""
	Compiles a context object representing the current seat-billing state 
	of a subscription (count, price, total).
	"""
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
	"""
	Validates if a proposed new seat count is allowed.
	- Must be >= Plan minimum.
	- Must be <= Plan maximum (if defined).
	- Must be >= Current enabled user count on the site.
	"""
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

	# Ensure they don't buy fewer seats than they have active users
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


def validate_seat_selection_for_plan(site: str | None, plan: str | dict[str, Any], new_seats: int) -> dict[str, Any]:
	"""
	Validates seat selection for a specific plan. 
	Used during initial signup or checkout flows where a subscription doesn't exist yet.
	"""
	plan_doc = frappe.get_cached_doc("Site Plan", plan) if isinstance(plan, str) else plan
	new_seats = cint(new_seats)
	min_seats = cint(getattr(plan_doc, "min_seats", 0) or 1)
	if new_seats < min_seats:
		frappe.throw(_("You need at least {0} seats on this plan.").format(min_seats))

	max_seats = cint(getattr(plan_doc, "max_seats", 0) or 0)
	if max_seats and new_seats > max_seats:
		return {
			"error_code": "SEATS_EXCEED_PLAN_LIMIT",
			"suggested_plan": getattr(plan_doc, "next_plan", None),
			"message": _("Requested seats exceed the current plan limit."),
		}

	active_user_count = 0
	if site:
		active_user_count = get_active_user_count(site)
		if new_seats < active_user_count:
			frappe.throw(
				_("You have {0} active users. Please deactivate users before reducing your seat count.").format(
					active_user_count
				)
			)

	price_per_seat = get_plan_price_per_seat(plan_doc)
	return {
		"plan": plan_doc.name,
		"billable_seats": new_seats,
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
	"""
	Logs a change in seat count for billing audit.
	This is critical for calculating pro-rated charges in the next billing cycle.
	"""
	access_updated_at = access_updated_at or now_datetime()
	billing_effective_from = billing_effective_from or get_billing_effective_from(access_updated_at)
	subscription_doc = frappe.get_cached_doc("Subscription", subscription)
	site_name = subscription_doc.site or (
		subscription_doc.document_name if subscription_doc.document_type == "Site" else None
	)
	seat_change = frappe.get_doc(
		{
			"doctype": "Seat Change Log",
			"subscription": subscription,
			"site": site_name,
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
	"""
	Notifies the managed Site about its new seat/license limit.
	Triggers an external API call to the site via the Press Agent.
	"""
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
	"""
	Creates a daily Usage Record representing the seat count snapshot for billing.
	Only executes after the 6 PM daily cutoff.
	"""
	if isinstance(subscription, str):
		subscription_doc = frappe.get_cached_doc("Subscription", subscription)
	else:
		subscription_doc = frappe.get_cached_doc("Subscription", subscription.get("name"))

	plan = frappe.get_cached_doc(subscription_doc.plan_type, subscription_doc.plan)
	if not is_seat_based_plan(plan):
		return None

	date = getdate(date or frappe.utils.today())
	# Bypassed if before snapshot time unless forced
	if date == getdate() and not force and nowtime() < time(SEAT_BILLING_SNAPSHOT_HOUR, 0):
		return None

	if subscription_doc.is_usage_record_created(date):
		return None

	if date == getdate() and not force:
		backfill_missing_seat_usage_records(subscription_doc, date)

	return _insert_seat_usage_record(subscription_doc, date)


def backfill_missing_seat_usage_records(subscription, upto_date=None):
	"""
	Ensures there are no gaps in usage records for the current billing cycle.
	Creates 'backfill' snapshots using the legacy seat count if necessary.
	"""
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
	"""
	Cron-triggered task to generate daily seat snapshots for all active subscriptions.
	Called by Frappe Scheduler events.
	"""
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
	"""API wrapper to trigger a seat count update on a subscription."""
	subscription_doc = frappe.get_cached_doc("Subscription", subscription)
	return subscription_doc.update_billable_seats(new_seats)


@frappe.whitelist()
def activate_seat_billing(subscription: str, plan: str, new_seats: int) -> dict[str, Any]:
	"""
	API method to convert an existing generic subscription into a seat-based one.
	Sets the plan, initial seat count, and enables the subscription.
	"""
	subscription_doc = frappe.get_cached_doc("Subscription", subscription)
	validation = validate_seat_selection_for_plan(subscription_doc.site, plan, new_seats)
	if validation.get("error_code") == "SEATS_EXCEED_PLAN_LIMIT":
		return validation

	plan_doc = frappe.get_cached_doc("Site Plan", plan)
	old_seats = cint(getattr(subscription_doc, "billable_seats", 0) or 0)
	subscription_doc.flags.skip_seat_change_log = True
	subscription_doc.plan_type = "Site Plan"
	subscription_doc.plan = plan_doc.name
	subscription_doc.billable_seats = cint(validation["billable_seats"])
	subscription_doc.price_per_seat = flt(validation["price_per_seat"], 2)
	subscription_doc.total_amount = flt(validation["total_amount"], 2)
	subscription_doc.seats_last_updated = now_datetime()
	subscription_doc.enabled = 1
	subscription_doc.save(ignore_permissions=True)
	subscription_doc.flags.skip_seat_change_log = False

	if old_seats != subscription_doc.billable_seats:
		log_seat_change(
			subscription=subscription_doc.name,
			old_seats=old_seats,
			new_seats=subscription_doc.billable_seats,
			changed_by=frappe.session.user,
			access_updated_at=subscription_doc.seats_last_updated,
			billing_effective_from=get_billing_effective_from(subscription_doc.seats_last_updated),
		)

	sync_site_access(subscription_doc)
	return {
		"subscription": subscription_doc.name,
		"plan": plan_doc.name,
		"plan_title": getattr(plan_doc, "plan_title", None) or plan_doc.name,
		"billable_seats": subscription_doc.billable_seats,
		"price_per_seat": subscription_doc.price_per_seat,
		"total_amount": subscription_doc.total_amount,
		"message": _(
			"Your seat count has been updated to {0}. Billing will reflect this change from today's daily update at 6 PM."
		).format(subscription_doc.billable_seats),
	}


def _insert_seat_usage_record(subscription, date, backfill: bool = False):
	"""Internal helper to insert a 'Usage Record' document into the database."""
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
