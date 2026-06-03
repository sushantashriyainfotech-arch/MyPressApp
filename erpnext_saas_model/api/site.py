from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from press.api.site import get_site_plans as get_press_site_plans
from press.api.site import change_plan as change_press_plan

from erpnext_saas_model.seat_billing import get_active_user_count
from erpnext_saas_model.seat_billing import get_seat_billing_dashboard
from erpnext_saas_model.seat_billing import get_site_seat_limit_context
from erpnext_saas_model.seat_billing import get_subscription_seat_context
from erpnext_saas_model.seat_billing import is_seat_based_plan
from erpnext_saas_model.seat_billing import validate_site_user_seat_limit


def _log_user_eligibility(event_type: str, payload: dict, decision: dict | None = None, status: str = "info"):
	entry = {
		"event_type": event_type,
		"payload": payload,
		"decision": decision,
		"timestamp": now_datetime(),
	}
	message = json.dumps(entry, default=str, sort_keys=True)
	logger = frappe.logger("erpnext_saas_model.user_eligibility")
	if status == "warning":
		logger.warning(message)
	elif status == "error":
		logger.error(message)
	else:
		logger.info(message)


def _authenticate_billing_site() -> frappe._dict:
	headers = frappe.request.headers
	site_name = headers.get("x-site")
	site_token = headers.get("x-site-token")

	if not site_name:
		frappe.throw("Invalid x-site provided", frappe.AuthenticationError)

	if not site_token:
		frappe.throw("Invalid communication secret. Please verify your key secret and retry.")

	if not frappe.db.exists("Site", site_name):
		frappe.throw(
			"The site does not seem to exist. Please <a href='https://docs.frappe.io/cloud/sites/creating-a-new-site'>create a new site</a> or reach out to us at <a href='https://support.frappe.io/'>support.frappe.io</a> if you don't think this should be expected."
		)

	site = frappe.get_doc("Site", site_name)
	site_secret = getattr(site, "saas_communication_secret", None) or getattr(site, "fc_communication_secret", None)
	if site_secret != site_token:
		frappe.throw("The secret seems invalid. Please verify your key secret and retry.")

	return site


@frappe.whitelist()
def get_site_plans():
	plans = get_press_site_plans()

	for plan in plans:
		plan_doc = frappe.get_cached_doc("Site Plan", plan["name"])
		if not is_seat_based_plan(plan_doc):
			continue

		plan["billing_type"] = getattr(plan_doc, "billing_type", None)
		plan["price_per_seat"] = getattr(plan_doc, "price_per_seat", None)
		plan["min_seats"] = getattr(plan_doc, "min_seats", None)
		plan["max_seats"] = getattr(plan_doc, "max_seats", None)
		plan["next_plan"] = getattr(plan_doc, "next_plan", None)

	return plans


@frappe.whitelist()
def change_plan(name, plan, billable_seats=None, price_usd=None):
	site = frappe.get_doc("Site", name)
	frappe.logger("erpnext_saas_model.seat_debug").info(
		json.dumps(
			{
				"event": "api.change_plan.called",
				"site_name_arg": name,
				"resolved_site_name": getattr(site, "name", None),
				"resolved_site_team": getattr(site, "team", None),
				"plan": plan,
				"billable_seats": billable_seats,
				"price_usd": price_usd,
			},
			default=str,
		)
	)
	if billable_seats is not None:
		site.set_plan(plan, billable_seats=billable_seats, price_usd=price_usd)
		return

	return change_press_plan(name, plan)


@frappe.whitelist()
def get_seat_billing_context(subscription=None):
	return get_seat_billing_dashboard(subscription=subscription)


@frappe.whitelist()
def get_current_subscription_context(site=None, subscription=None):
	if subscription:
		subscription_doc = frappe.get_doc("Subscription", subscription)
	elif site:
		site_doc = frappe.get_doc("Site", site)
		subscription_doc = getattr(site_doc, "subscription", None)
	else:
		subscription_doc = None

	if not subscription_doc:
		return {"subscription": None, "current": None}

	current = get_subscription_seat_context(subscription_doc.name)
	current["name"] = subscription_doc.name
	current["subscription"] = subscription_doc.as_dict()
	current["site"] = getattr(subscription_doc, "site", None) or (
		subscription_doc.document_name if subscription_doc.document_type == "Site" else None
	)
	current["active_user_count"] = get_active_user_count(current["site"]) if current["site"] else 0
	return {"subscription": subscription_doc.name, "current": current}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def check_user_creation_eligibility():
	"""Return True if the authenticated site may add another user."""
	site = _authenticate_billing_site()
	try:
		validate_site_user_seat_limit(site, enabled=True)
		_log_user_eligibility(
			"user_creation_eligibility",
			{"site": site.name},
			{"can_create_user": True},
		)
		return True
	except Exception as exc:
		_log_user_eligibility(
			"user_creation_eligibility",
			{"site": site.name},
			{"can_create_user": False, "message": str(exc)},
			status="warning",
		)
		frappe.throw(str(exc))
