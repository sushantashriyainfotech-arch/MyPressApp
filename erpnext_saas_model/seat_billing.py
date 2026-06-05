from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any


import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowtime
from erpnext_saas_model.user_eligibility import _log_user_eligibility

SEAT_BILLING_SNAPSHOT_HOUR = 18

def is_seat_based_plan(plan: str | dict[str, Any] | None) -> bool:
	"""
	Checks if a given Site Plan follows a 'Seat Based' billing model.
	"""
	if not plan:
		return False

	if isinstance(plan, dict):
		return plan.get("billing_type") == "Seat Based"

	if hasattr(plan, "billing_type"):
		return plan.billing_type == "Seat Based"

	billing_type = frappe.db.get_value("Site Plan", plan, "billing_type")
	return billing_type == "Seat Based"


def get_plan_total_price(plan: str | dict[str, Any] | None) -> float:
	"""
	Returns the base price of a Site Plan.
	For seat-based plans, this is usually 0 (since it's per-seat).
	For resource-based plans, this is the fixed price of the plan.
	"""
	if not plan:
		return 0.0

	if isinstance(plan, str):
		plan = frappe.get_cached_doc("Site Plan", plan)

	price = getattr(plan, "total_price", None) or getattr(plan, "amount", 0)
	return flt(price, 2)


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
			active_user_count = (
				get_site_user_active_count(current["subscription"]["site"])
				if current["subscription"].get("site")
				else 0
			)
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


def _get_subscription_site_name(subscription_doc: dict[str, Any]) -> str | None:
	"""
	Resolve the site name associated with a subscription.
	Prefer the explicit `site` link, but fall back to the subscribed document
	for legacy Site subscriptions where `site` was not backfilled yet.
	"""
	site_name = subscription_doc.get("site")
	if site_name:
		return site_name

	if subscription_doc.get("document_type") == "Site":
		return subscription_doc.get("document_name")

	return None


def get_site_user_active_count(site_name: str) -> int:
	"""Count enabled mirrored users for a site."""
	if not site_name:
		return 0

	return frappe.db.count("Site User", {"site": site_name, "enabled": 1})


def get_site_billable_seats(site: str | dict[str, Any] | None) -> int:
	"""
	Returns the current seat allowance for a site.
	Prefers the Site doc's billable_seats field, then falls back to the
	linked subscription or plan minimum for seat-based plans.
	"""
	if not site:
		return 0

	if isinstance(site, dict):
		site_doc = frappe._dict(site)
	else:
		site_doc = site if hasattr(site, "doctype") else frappe.get_cached_doc("Site", site)

	subscription = getattr(site_doc, "subscription", None)
	plan = None
	if subscription:
		plan = frappe.get_cached_doc(subscription.plan_type, subscription.plan)
	elif getattr(site_doc, "plan", None) or getattr(site_doc, "subscription_plan", None):
		plan_name = getattr(site_doc, "plan", None) or getattr(site_doc, "subscription_plan", None)
		plan = frappe.get_cached_doc("Site Plan", plan_name)

	if not plan or not is_seat_based_plan(plan):
		return 0

	billable_seats = cint(getattr(site_doc, "billable_seats", 0) or 0)
	if billable_seats:
		return billable_seats

	if subscription:
		billable_seats = cint(getattr(subscription, "billable_seats", 0) or 0)
		if billable_seats:
			return billable_seats

	return cint(getattr(plan, "min_seats", 0) or 1)


def get_site_seat_limit_context(site: str | dict[str, Any] | None) -> dict[str, Any]:
	"""
	Builds a compact context payload used when validating site user creation.
	"""
	if not site:
		return {"billable_seats": 0, "active_user_count": 0, "plan": None, "next_plan": None}

	site_doc = site if hasattr(site, "doctype") else frappe.get_cached_doc("Site", site)
	subscription = getattr(site_doc, "subscription", None)
	plan = None

	if subscription:
		plan = frappe.get_cached_doc(subscription.plan_type, subscription.plan)
	elif getattr(site_doc, "plan", None) or getattr(site_doc, "subscription_plan", None):
		plan_name = getattr(site_doc, "plan", None) or getattr(site_doc, "subscription_plan", None)
		plan = frappe.get_cached_doc("Site Plan", plan_name)

	billable_seats = get_site_billable_seats(site_doc)
	active_user_count = frappe.db.count("Site User", {"site": site_doc.name, "enabled": 1})
	next_plan = getattr(plan, "next_plan", None) if plan else None

	return {
		"site": site_doc.name,
		"billable_seats": billable_seats,
		"active_user_count": active_user_count,
		"plan": getattr(plan, "name", None),
		"plan_title": getattr(plan, "plan_title", None) if plan else None,
		"next_plan": next_plan,
	}


def validate_site_user_seat_limit(site: str | dict[str, Any], enabled: bool = True) -> dict[str, Any]:
	"""
	Ensures that enabling or creating a site user does not exceed billable seats.
	"""
	_log_user_eligibility(
		"validate_site_user_seat_limit.start",
		{"site": getattr(site, "name", site), "enabled": enabled},
		status="info",
	)
	context = get_site_seat_limit_context(site)
	_log_user_eligibility(
		"validate_site_user_seat_limit.context",
		context,
		status="info",
	)
	if not enabled:
		_log_user_eligibility(
			"validate_site_user_seat_limit.skipped",
			context,
			{"can_create_user": True, "reason": "DISABLED"},
			status="info",
		)
		return context

	if not context["billable_seats"]:
		_log_user_eligibility(
			"validate_site_user_seat_limit.skipped",
			context,
			{"can_create_user": True, "reason": "NO_BILLABLE_SEATS"},
			status="info",
		)
		return context

	# The current count does not include the pending insert/update, so equal means full.
	_log_user_eligibility(
		"validate_site_user_seat_limit.compare",
		context,
		{
			"billable_seats": context["billable_seats"],
			"active_user_count": context["active_user_count"],
			"next_plan": context.get("next_plan"),
		},
		status="info",
	)
	if context["active_user_count"] >= context["billable_seats"]:
		next_plan = context.get("next_plan")
		if next_plan:
			_log_user_eligibility(
				"validate_site_user_seat_limit.block",
				context,
				{"can_create_user": False, "reason": "SEAT_LIMIT_REACHED", "next_plan": next_plan},
				status="warning",
			)
			frappe.throw(
				_(
					"This site has reached its billable seat limit of {0}. Please upgrade to {1} to add more users."
				).format(context["billable_seats"], next_plan)
			)

		_log_user_eligibility(
			"validate_site_user_seat_limit.block",
			context,
			{"can_create_user": False, "reason": "SEAT_LIMIT_REACHED", "next_plan": None},
			status="warning",
		)
		frappe.throw(
			_(
				"This site has reached its billable seat limit of {0}. Please upgrade your plan to add more users."
			).format(context["billable_seats"])
		)

	_log_user_eligibility(
		"validate_site_user_seat_limit.allow",
		context,
		{"can_create_user": True, "reason": "WITHIN_LIMIT"},
		status="info",
	)
	return context


def upsert_site_user(site: str, user_mail: str, enabled: bool) -> dict[str, Any] | None:
	"""
	Creates or updates a Site User row while honoring seat limits.
	Returns the inserted/updated document, or None when no change is needed.
	"""
	if not site or not user_mail:
		return None

	site_doc = frappe.get_cached_doc("Site", site)
	enabled = bool(cint(enabled))
	site_user_name = frappe.db.get_value("Site User", {"site": site_doc.name, "user": user_mail}, "name")

	if site_user_name:
		current_enabled = cint(frappe.db.get_value("Site User", site_user_name, "enabled") or 0)
		if current_enabled == cint(enabled):
			return frappe.get_doc("Site User", site_user_name)

		if enabled:
			validate_site_user_seat_limit(site_doc, enabled=True)

		frappe.db.set_value("Site User", site_user_name, "enabled", enabled)
		return frappe.get_doc("Site User", site_user_name)

	if enabled:
		validate_site_user_seat_limit(site_doc, enabled=True)

	site_user = frappe.get_doc(
		{
			"doctype": "Site User",
			"site": site_doc.name,
			"user": user_mail,
			"enabled": enabled,
		}
	)
	site_user.insert(ignore_permissions=True)
	return site_user


def validate_site_user_before_save(doc, method=None):
	"""
	Doc event hook for Site User writes that bypass the custom sync helpers.
	"""
	previous = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if previous and cint(getattr(previous, "enabled", 0)) == cint(getattr(doc, "enabled", 0)):
		return

	validate_site_user_seat_limit(getattr(doc, "site", None), enabled=bool(cint(getattr(doc, "enabled", 0))))


def _get_team_seat_limited_site(team_name: str | None):
	"""Returns the seat-based site linked to a team, if one exists."""
	if not team_name:
		return None

	for site in frappe.get_all(
		"Site",
		filters={"team": team_name},
		fields=["name"],
		order_by="modified desc",
	):
		site_doc = frappe.get_cached_doc("Site", site.name)
		subscription = getattr(site_doc, "subscription", None)
		if subscription and is_seat_based_plan(frappe.get_cached_doc(subscription.plan_type, subscription.plan)):
			return site_doc

		plan_name = getattr(site_doc, "plan", None) or getattr(site_doc, "subscription_plan", None)
		if plan_name and is_seat_based_plan(frappe.get_cached_doc("Site Plan", plan_name)):
			return site_doc

	return None


def get_team_seat_limit_context(team: str | dict[str, Any] | None) -> dict[str, Any]:
	"""
	Builds a seat-limit context for Team member operations.
	"""
	if not team:
		return {
			"team": None,
			"site": None,
			"billable_seats": 0,
			"active_user_count": 0,
			"plan": None,
			"plan_title": None,
			"next_plan": None,
		}

	team_doc = team if hasattr(team, "doctype") else frappe.get_cached_doc("Team", team)
	site_doc = _get_team_seat_limited_site(team_doc.name)
	if not site_doc:
		return {
			"team": team_doc.name,
			"site": None,
			"billable_seats": 0,
			"active_user_count": 0,
			"plan": None,
			"plan_title": None,
			"next_plan": None,
		}

	site_context = get_site_seat_limit_context(site_doc)
	site_context.update(
		{
			"team": team_doc.name,
			"active_user_count": frappe.db.count(
				"Team Member", {"parent": team_doc.name, "parenttype": "Team"}
			),
		}
	)
	return site_context


def validate_team_member_seat_limit(team: str | dict[str, Any]) -> dict[str, Any]:
	"""
	Ensures that adding another team member does not exceed billable seats.
	"""
	context = get_team_seat_limit_context(team)
	if not context["billable_seats"]:
		return context

	if context["active_user_count"] >= context["billable_seats"]:
		next_plan = context.get("next_plan")
		if next_plan:
			frappe.throw(
				_(
					"This team has reached its billable seat limit of {0}. Please upgrade to {1} to add more users."
				).format(context["billable_seats"], next_plan)
			)

		frappe.throw(
			_(
				"This team has reached its billable seat limit of {0}. Please upgrade your plan to add more users."
			).format(context["billable_seats"])
		)

	return context


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
			"next_plan": getattr(plan, "next_plan", None),
			"message": _("Requested seats exceed the current plan limit."),
		}

	# Ensure they don't buy fewer seats than they have active users
	site_name = _get_subscription_site_name(subscription_doc)
	active_user_count = get_site_user_active_count(site_name) if site_name else 0
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
			"next_plan": getattr(plan_doc, "next_plan", None),
			"message": _("Requested seats exceed the current plan limit."),
		}

	active_user_count = 0
	if site:
		active_user_count = get_site_user_active_count(site)
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
