from __future__ import annotations

import json

import frappe
from frappe.utils import cint, now_datetime

from press.api.site import get_site_plans as get_press_site_plans
from press.api.site import change_plan as change_press_plan

from erpnext_saas_model.seat_billing import get_active_user_count
from erpnext_saas_model.seat_billing import get_site_seat_limit_context
from erpnext_saas_model.seat_billing import is_seat_based_plan


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
	if billable_seats is not None:
		site.set_plan(plan, billable_seats=billable_seats, price_usd=price_usd)
		return

	return change_press_plan(name, plan)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def check_user_creation_eligibility(**data):
	"""Return whether the tenant may add another enabled user."""
	site = _authenticate_billing_site()
	active_user_count = cint(data.get("active_user_count") or 0)
	if not active_user_count:
		active_user_count = cint(get_active_user_count(site.name))

	context = get_site_seat_limit_context(site)
	plan_name = context.get("plan")
	plan = frappe.get_cached_doc("Site Plan", plan_name) if plan_name else None
	billable_seats = cint(context.get("billable_seats") or 0)
	suggested_plan = context.get("suggested_plan")

	response = {
		"site": site.name,
		"subscription": getattr(site, "subscription", None),
		"plan": getattr(plan, "name", None) if plan else None,
		"plan_title": getattr(plan, "plan_title", None) if plan else None,
		"billing_type": getattr(plan, "billing_type", None) if plan else None,
		"billable_seats": billable_seats,
		"active_user_count": active_user_count,
		"suggested_plan": suggested_plan,
		"can_create_user": False,
		"reason": "NO_ACTIVE_PLAN",
	}

	if not plan:
		_log_user_eligibility(
			"user.eligibility",
			{"site": site.name, "active_user_count": active_user_count},
			response,
			status="warning",
		)
		return response

	if getattr(plan, "billing_type", None) != "Seat Based":
		response.update(
			{
				"can_create_user": True,
				"reason": "RESOURCE_BASED_PLAN",
				"billable_seats": 0,
			}
		)
		_log_user_eligibility(
			"user.eligibility",
			{"site": site.name, "active_user_count": active_user_count},
			response,
		)
		return response

	if not billable_seats:
		billable_seats = cint(getattr(plan, "min_seats", 0) or 1)

	can_create_user = active_user_count < billable_seats
	response.update(
		{
			"billable_seats": billable_seats,
			"can_create_user": can_create_user,
			"reason": "WITHIN_LIMIT" if can_create_user else "SEAT_LIMIT_REACHED",
		}
	)

	if not can_create_user:
		response["message"] = (
			f"This site has reached its billable seat limit of {billable_seats}. "
			f"Please upgrade to {suggested_plan or 'the next plan'} to add more users."
		)

	_log_user_eligibility(
		"user.eligibility",
		{"site": site.name, "active_user_count": active_user_count},
		response,
		status="warning" if not response["can_create_user"] else "info",
	)
	return response
