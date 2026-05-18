from __future__ import annotations

import frappe

from press.api.site import get_site_plans as get_press_site_plans
from press.api.site import change_plan as change_press_plan

from erpnext_saas_model.seat_billing import is_seat_based_plan


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
def change_plan(name, plan, billable_seats=None):
	site = frappe.get_doc("Site", name)
	if billable_seats is not None:
		site.set_plan(plan, billable_seats=billable_seats)
		return

	return change_press_plan(name, plan)
