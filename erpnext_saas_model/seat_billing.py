from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any


import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowtime
from erpnext_saas_model.user_eligibility import _log_user_eligibility

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


def get_team_currency(team: str | dict[str, Any] | None) -> str:
	"""Resolve the team's billing currency, defaulting to USD."""
	if not team:
		return "USD"

	if isinstance(team, dict):
		return (team.get("currency") or "USD").upper()

	if hasattr(team, "currency"):
		return (getattr(team, "currency", None) or "USD").upper()

	return (frappe.db.get_value("Team", team, "currency") or "USD").upper()


def get_plan_price_for_currency(
	plan: str | dict[str, Any] | None,
	currency: str | None = None,
) -> float:
	"""Return the plan price for the requested currency, with fallback to the other field."""
	if not plan:
		return 0.0

	if isinstance(plan, str):
		plan = frappe.get_cached_doc("Site Plan", plan)

	currency = (currency or "USD").upper()
	preferred_field = "price_inr" if currency == "INR" else "price_usd"
	fallback_field = "price_usd" if preferred_field == "price_inr" else "price_inr"
	price = getattr(plan, preferred_field, None)
	if price in (None, ""):
		price = getattr(plan, fallback_field, None)
	if price in (None, ""):
		price = 0

	return flt(price, 2)


def get_plan_price_per_seat(plan: str | dict[str, Any] | None, currency: str | None = None) -> float:
	"""Backward-compatible wrapper for the currency-aware seat price helper."""
	return get_plan_price_for_currency(plan, currency=currency)


def get_seat_plans() -> list[dict[str, Any]]:
	"""
	Returns a list of all enabled Site Plans that use seat-based billing.
	Ordered by price (ascending).
	"""
	return frappe.get_all(
		"Site Plan",
		filters={"enabled": 1, "billing_type": "Seat Based"},
		fields=["name", "plan_title", "price_inr", "price_usd", "min_seats", "max_seats", "next_plan"],
		order_by="COALESCE(price_inr, price_usd) asc, name asc",
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


def get_seat_change_log_for_reference(subscription: str, reference_at=None) -> dict[str, Any] | None:
	"""Return the latest seat change log that applies at a specific point in time."""
	if not reference_at:
		reference_at = now_datetime()
	if not isinstance(reference_at, datetime):
		reference_at = datetime.combine(getdate(reference_at), time(23, 59, 59))

	logs = frappe.get_all(
		"Seat Change Log",
		filters={
			"subscription": subscription,
			"access_updated_at": ("<=", reference_at),
		},
		fields=["name", "old_seats", "new_seats", "change_type", "access_updated_at"],
		order_by="access_updated_at desc, creation desc",
		limit=1,
	)
	return logs[0] if logs else None


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
			"price_inr",
			"price_usd",
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
	price_inr = flt(getattr(plan_doc, "price_inr", 0) or 0, 2)
	price_usd = flt(getattr(plan_doc, "price_usd", 0) or 0, 2)
	selected_price = price_usd or price_inr
	if not is_seat_based_plan(plan_doc):
		return {
			"plan": plan_doc.name,
			"plan_title": getattr(plan_doc, "plan_title", None) or plan_doc.name,
			"billable_seats": cint(seats),
			"price_inr": price_inr,
			"price_usd": price_usd,
			"selected_price": selected_price,
			"total_amount": flt(selected_price * cint(seats), 2),
		}

	return {
		"plan": plan_doc.name,
		"plan_title": getattr(plan_doc, "plan_title", None) or plan_doc.name,
		"billable_seats": cint(seats),
		"price_inr": price_inr,
		"price_usd": price_usd,
		"selected_price": selected_price,
		"total_amount": flt(selected_price * cint(seats), 2),
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

	cache_key = f"erpnext_saas_model:seat_billing:active_users:{site_name}"
	cached_value = frappe.cache().get_value(cache_key)
	if cached_value is not None:
		return cint(cached_value)

	active_users = frappe.db.count("Site User", {"site": site_name, "enabled": 1})
	frappe.cache().set_value(cache_key, active_users, expires_in_sec=ACTIVE_USER_CACHE_TTL)
	return active_users


def refresh_site_user_active_count_cache(site_name: str) -> int:
	"""Recompute and cache the enabled Site User count for a site."""
	if not site_name:
		return 0

	active_users = frappe.db.count("Site User", {"site": site_name, "enabled": 1})
	cache_key = f"erpnext_saas_model:seat_billing:active_users:{site_name}"
	frappe.cache().set_value(cache_key, active_users, expires_in_sec=ACTIVE_USER_CACHE_TTL)
	return active_users


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
	active_user_count = get_site_user_active_count(site_doc.name)
	next_plan = getattr(plan, "next_plan", None) if plan else None

	return {
		"site": site_doc.name,
		"billable_seats": billable_seats,
		"active_user_count": active_user_count,
		"plan": getattr(plan, "name", None),
		"plan_title": getattr(plan, "plan_title", None) if plan else None,
		"next_plan": next_plan,
	}


def sync_site_users_from_analytics(site: str, analytics_payload: dict[str, Any]) -> None:
	"""
	Syncs users from site analytics to Press while enforcing seat caps.
	"""
	_log_user_eligibility(
		"sync_site_users_from_analytics.start",
		{
			"site": site,
			"analytics_keys": sorted(list(analytics_payload.keys())) if isinstance(analytics_payload, dict) else None,
		},
		status="info",
	)
	users = _extract_users_from_analytics(analytics_payload)
	_log_user_eligibility(
		"sync_site_users_from_analytics.users_parsed",
		{
			"site": site,
			"users_count": len(users),
			"sample_users": [user.get("email") for user in users[:5]],
		},
		status="info",
	)
	for user_data in users:
		_log_user_eligibility(
			"sync_site_users_from_analytics.user_upsert",
			{
				"site": site,
				"user": user_data.get("email"),
				"enabled": user_data.get("enabled"),
			},
			status="info",
		)
		upsert_site_user(site, user_data.get("email"), user_data.get("enabled"), refresh_cache=False)
	active_users = refresh_site_user_active_count_cache(site)
	_log_user_eligibility(
		"sync_site_users_from_analytics.complete",
		{
			"site": site,
			"synced_users_count": len(users),
			"active_user_count": active_users,
		},
		status="info",
	)


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


def sync_site_access(subscription: str | dict[str, Any]):
	"""
	Notifies the managed Site about its new seat/license limit.
	Triggers an external API call to the site via the Press Agent.
	"""
	_log_user_eligibility(
		"sync_site_access.start",
		{
			"subscription": subscription if isinstance(subscription, str) else subscription.get("name"),
		},
		status="info",
	)
	if isinstance(subscription, str):
		subscription_doc = frappe.get_cached_doc("Subscription", subscription)
	else:
		subscription_doc = frappe.get_cached_doc("Subscription", subscription.get("name"))

	if not subscription_doc.site:
		_log_user_eligibility(
			"sync_site_access.skipped",
			{
				"subscription": subscription_doc.name,
				"reason": "NO_SITE_LINKED",
			},
			status="warning",
		)
		return

	try:
		site = frappe.get_cached_doc("Site", subscription_doc.site)
		_log_user_eligibility(
			"sync_site_access.site_loaded",
			{
				"subscription": subscription_doc.name,
				"site": site.name,
				"plan": getattr(site, "plan", None) or getattr(site, "subscription_plan", None),
				"billable_seats": getattr(site, "billable_seats", None),
			},
			status="info",
		)
		if hasattr(site, "sync_users_to_product_site"):
			_log_user_eligibility(
				"sync_site_access.sync_users_called",
				{
					"subscription": subscription_doc.name,
					"site": site.name,
				},
				status="info",
			)
			site.sync_users_to_product_site()
			_log_user_eligibility(
				"sync_site_access.complete",
				{
					"subscription": subscription_doc.name,
					"site": site.name,
				},
				status="info",
			)
	except Exception:
		frappe.logger("erpnext_saas_model.seat_billing").warning(
			f"Failed to sync site access for subscription {subscription_doc.name}", exc_info=True
		)
		_log_user_eligibility(
			"sync_site_access.failed",
			{
				"subscription": subscription_doc.name,
				"site": getattr(subscription_doc, "site", None),
			},
			status="warning",
		)


def upsert_site_user(site: str, user_mail: str, enabled: bool, refresh_cache: bool = True) -> dict[str, Any] | None:
	"""
	Creates or updates a Site User row while honoring seat limits.
	Returns the inserted/updated document, or None when no change is needed.
	"""
	if not site or not user_mail:
		return None

	site_doc = frappe.get_cached_doc("Site", site)
	enabled = bool(cint(enabled))
	_log_user_eligibility(
		"upsert_site_user.start",
		{
			"site": site_doc.name,
			"user": user_mail,
			"enabled": enabled,
			"refresh_cache": refresh_cache,
		},
		status="info",
	)
	site_user_name = frappe.db.get_value("Site User", {"site": site_doc.name, "user": user_mail}, "name")

	if site_user_name:
		_log_user_eligibility(
			"upsert_site_user.existing",
			{
				"site": site_doc.name,
				"user": user_mail,
				"site_user_name": site_user_name,
			},
			status="info",
		)
		current_enabled = cint(frappe.db.get_value("Site User", site_user_name, "enabled") or 0)
		if current_enabled == cint(enabled):
			_log_user_eligibility(
				"upsert_site_user.no_change",
				{
					"site": site_doc.name,
					"user": user_mail,
					"site_user_name": site_user_name,
					"enabled": enabled,
				},
				status="info",
			)
			return frappe.get_doc("Site User", site_user_name)

		if enabled:
			validate_site_user_seat_limit(site_doc, enabled=True)

		frappe.db.set_value("Site User", site_user_name, "enabled", enabled)
		_log_user_eligibility(
			"upsert_site_user.updated",
			{
				"site": site_doc.name,
				"user": user_mail,
				"site_user_name": site_user_name,
				"enabled": enabled,
			},
			status="info",
		)
		if refresh_cache:
			active_users = refresh_site_user_active_count_cache(site_doc.name)
			_log_user_eligibility(
				"upsert_site_user.cache_refreshed",
				{
					"site": site_doc.name,
					"user": user_mail,
					"active_user_count": active_users,
				},
				status="info",
			)
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
	if refresh_cache:
		active_users = refresh_site_user_active_count_cache(site_doc.name)
		_log_user_eligibility(
			"upsert_site_user.cache_refreshed",
			{
				"site": site_doc.name,
				"user": user_mail,
				"active_user_count": active_users,
			},
			status="info",
		)
	_log_user_eligibility(
		"upsert_site_user.created",
		{
			"site": site_doc.name,
			"user": user_mail,
			"site_user_name": site_user.name,
			"enabled": enabled,
		},
		status="info",
	)
	return site_user


def validate_site_user_before_save(doc, method=None):
	"""
	Doc event hook for Site User writes that bypass the custom sync helpers.
	"""
	_log_user_eligibility(
		"validate_site_user_before_save.start",
		{
			"site": getattr(doc, "site", None),
			"user": getattr(doc, "user", None),
			"enabled": getattr(doc, "enabled", None),
		},
		status="info",
	)
	previous = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if previous and cint(getattr(previous, "enabled", 0)) == cint(getattr(doc, "enabled", 0)):
		_log_user_eligibility(
			"validate_site_user_before_save.skipped",
			{
				"site": getattr(doc, "site", None),
				"user": getattr(doc, "user", None),
				"enabled": getattr(doc, "enabled", None),
				"reason": "NO_ENABLED_STATE_CHANGE",
			},
			status="info",
		)
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
	team_currency = get_team_currency(subscription_doc.get("team"))
	price_inr = flt(subscription_doc.get("price_inr") or getattr(plan, "price_inr", 0) or 0, 2)
	price_usd = flt(subscription_doc.get("price_usd") or getattr(plan, "price_usd", 0) or 0, 2)
	selected_price = get_plan_price_for_currency(plan, team_currency)
	billable_seats = cint(subscription_doc.get("billable_seats") or 0)
	total_amount = flt(selected_price * billable_seats, 2)

	return {
		"plan": plan,
		"billable_seats": billable_seats,
		"team_currency": team_currency,
		"price_inr": price_inr,
		"price_usd": price_usd,
		"selected_price": selected_price,
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
	team_currency = get_team_currency(subscription_doc.get("team"))
	if not is_seat_based_plan(plan):
		price_inr = flt(getattr(plan, "price_inr", 0) or 0, 2)
		price_usd = flt(getattr(plan, "price_usd", 0) or 0, 2)
		selected_price = get_plan_price_for_currency(plan, team_currency)
		return {
			"subscription": subscription_name,
			"billable_seats": cint(new_seats),
			"plan": plan.name,
			"team_currency": team_currency,
			"price_inr": price_inr,
			"price_usd": price_usd,
			"selected_price": selected_price,
			"total_amount": flt(selected_price * cint(new_seats), 2),
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

	price_inr = flt(subscription_doc.get("price_inr") or getattr(plan, "price_inr", 0) or 0, 2)
	price_usd = flt(subscription_doc.get("price_usd") or getattr(plan, "price_usd", 0) or 0, 2)
	selected_price = get_plan_price_for_currency(plan, team_currency)
	return {
		"subscription": subscription_name,
		"billable_seats": new_seats,
		"plan": plan.name,
		"team_currency": team_currency,
		"price_inr": price_inr,
		"price_usd": price_usd,
		"selected_price": selected_price,
		"total_amount": flt(selected_price * new_seats, 2),
		"active_user_count": active_user_count,
	}


def validate_seat_selection_for_plan(site: str | None, plan: str | dict[str, Any], new_seats: int) -> dict[str, Any]:
	"""
	Validates seat selection for a specific plan. 
	Used during initial signup or checkout flows where a subscription doesn't exist yet.
	"""
	plan_doc = frappe.get_cached_doc("Site Plan", plan) if isinstance(plan, str) else plan
	team_currency = get_team_currency(frappe.get_cached_doc("Site", site).team if site else None)
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

	price_inr = flt(getattr(plan_doc, "price_inr", 0) or 0, 2)
	price_usd = flt(getattr(plan_doc, "price_usd", 0) or 0, 2)
	selected_price = get_plan_price_for_currency(plan_doc, team_currency)
	return {
		"plan": plan_doc.name,
		"billable_seats": new_seats,
		"team_currency": team_currency,
		"price_inr": price_inr,
		"price_usd": price_usd,
		"selected_price": selected_price,
		"total_amount": flt(selected_price * new_seats, 2),
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


def get_seat_billing_start_date(subscription_doc) -> datetime | None:
	"""
	Returns the first timestamp when the current paid plan became active.
	For trial-to-paid flows, this is the first Site Plan Change timestamp for the current plan.
	"""
	site_name = getattr(subscription_doc, "site", None) or (
		getattr(subscription_doc, "document_name", None)
		if getattr(subscription_doc, "document_type", None) == "Site"
		else None
	)
	plan_name = getattr(subscription_doc, "plan", None)
	if not site_name or not plan_name:
		return getattr(subscription_doc, "creation", None)

	plan_change_ts = frappe.db.get_value(
		"Site Plan Change",
		{"site": site_name, "to_plan": plan_name},
		"timestamp",
		order_by="timestamp asc",
	)
	if plan_change_ts:
		return plan_change_ts

	return getattr(subscription_doc, "creation", None)


def backfill_missing_seat_usage_records(subscription, upto_date=None):
	"""
	Ensures there are no gaps in usage records for the current billing cycle.
	Creates 'backfill' snapshots using the legacy seat count if necessary.
	The backfill window never starts before the paid billing start date.
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
	billing_start = get_seat_billing_start_date(subscription_doc)
	if billing_start:
		billing_start = getdate(billing_start)
		if billing_start > cycle_start:
			cycle_start = billing_start

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


def _format_seat_change_log_description(change_log, fallback_billable_seats: int | None = None) -> str:
	"""Format the human-readable seat change reason shown in invoice rows."""
	old_seats = cint(getattr(change_log, "old_seats", 0) or 0)
	new_seats = cint(getattr(change_log, "new_seats", 0) or 0)

	if old_seats or new_seats:
		return f"Seats changed: {old_seats} -> {new_seats}"

	if fallback_billable_seats is not None:
		seat_count = cint(fallback_billable_seats or 0)
		return f"Seats changed: {seat_count}"

	return "Seats changed"


def get_seat_usage_record_remark(
	subscription: str | dict[str, Any] | None = None,
	reference_at=None,
	snapshot_taken_at=None,
	seat_change_log: str | dict[str, Any] | None = None,
	fallback_billable_seats: int | None = None,
) -> str:
	"""Build the human-readable reason shown alongside seat-based usage records."""
	if reference_at is None:
		reference_at = snapshot_taken_at

	subscription_doc = None
	if subscription:
		subscription_doc = (
			frappe.get_cached_doc("Subscription", subscription)
			if isinstance(subscription, str)
			else frappe.get_cached_doc("Subscription", subscription.get("name"))
		)

	change_log = None
	if seat_change_log:
		change_log = (
			seat_change_log
			if isinstance(seat_change_log, dict)
			else frappe.get_cached_doc("Seat Change Log", seat_change_log).as_dict()
		)
	elif subscription_doc:
		change_log = get_seat_change_log_for_reference(subscription_doc.name, reference_at=reference_at)

	if change_log:
		return _format_seat_change_log_description(change_log, fallback_billable_seats=fallback_billable_seats)

	if fallback_billable_seats is not None:
		return _format_seat_change_log_description(None, fallback_billable_seats=fallback_billable_seats)

	return "Seats changed"


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
	team_currency = get_team_currency(subscription_doc.team)
	selected_price = get_plan_price_for_currency(plan_doc, team_currency)
	subscription_doc.flags.skip_seat_change_log = True
	subscription_doc.plan_type = "Site Plan"
	subscription_doc.plan = plan_doc.name
	subscription_doc.billable_seats = cint(validation["billable_seats"])
	subscription_doc.price_inr = flt(validation.get("price_inr") or getattr(plan_doc, "price_inr", 0) or 0, 2)
	subscription_doc.price_usd = flt(validation.get("price_usd") or getattr(plan_doc, "price_usd", 0) or 0, 2)
	subscription_doc.price_per_seat = selected_price
	subscription_doc.total_amount = flt(selected_price * subscription_doc.billable_seats, 2)
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
		"team_currency": team_currency,
		"price_inr": subscription_doc.price_inr,
		"price_usd": subscription_doc.price_usd,
		"selected_price": subscription_doc.price_per_seat,
		"total_amount": subscription_doc.total_amount,
		"message": _(
			"Your seat count has been updated to {0}. Billing will reflect this change from today's daily update at 6 PM."
		).format(subscription_doc.billable_seats),
	}


def _insert_seat_usage_record(subscription, date, backfill: bool = False):
	"""Internal helper to insert a 'Usage Record' document into the database."""
	plan = frappe.get_cached_doc(subscription.plan_type, subscription.plan)
	team_currency = get_team_currency(subscription.team)
	selected_price = get_plan_price_for_currency(plan, team_currency)
	billable_seats = cint(subscription.billable_seats or 0)
	seat_amount = flt(selected_price * billable_seats, 2)
	snapshot_taken_at = now_datetime()
	seat_change_log = get_seat_change_log_for_reference(subscription.name, reference_at=date if backfill else snapshot_taken_at)
	remark = get_seat_usage_record_remark(
		subscription=subscription.name,
		reference_at=snapshot_taken_at if not backfill else date,
		seat_change_log=seat_change_log,
		fallback_billable_seats=billable_seats,
	)

	usage_record = frappe.get_doc(
		{
			"doctype": "Usage Record",
			"team": subscription.team,
			"document_type": subscription.document_type,
			"document_name": subscription.document_name,
			"plan_type": subscription.plan_type,
			"plan": subscription.plan,
			"amount": seat_amount,
			"currency": team_currency,
			"date": date,
			"time": snapshot_taken_at.time().strftime("%H:%M:%S"),
			"subscription": subscription.name,
			"site": subscription.site,
			"billable_seats": billable_seats,
			"seat_amount": seat_amount,
			"snapshot_taken_at": snapshot_taken_at,
			"seat_change_log": getattr(seat_change_log, "name", None) if seat_change_log else None,
			"remark": remark,
		}
	)
	usage_record.insert(ignore_permissions=True)
	usage_record.submit()
	return usage_record
