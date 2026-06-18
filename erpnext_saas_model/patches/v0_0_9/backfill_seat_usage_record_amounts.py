from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from erpnext_saas_model.seat_billing import get_seat_usage_record_amount
from erpnext_saas_model.seat_billing import is_seat_based_plan


def execute():
	seat_plan_names = frappe.get_all(
		"Site Plan",
		filters={"billing_type": "Seat Based"},
		pluck="name",
	)
	if not seat_plan_names:
		return

	usage_records = frappe.get_all(
		"Usage Record",
		filters={
			"plan_type": "Site Plan",
			"plan": ("in", seat_plan_names),
			"docstatus": 1,
		},
		fields=["name", "plan", "team", "amount", "billable_seats", "date", "snapshot_taken_at"],
		order_by="creation asc",
	)

	for usage_record in usage_records:
		if flt(getattr(usage_record, "amount", 0) or 0, 2) > 0:
			continue
		if not cint(getattr(usage_record, "billable_seats", 0) or 0):
			continue

		plan = frappe.get_cached_doc("Site Plan", usage_record.plan)
		if not is_seat_based_plan(plan):
			continue

		amount = get_seat_usage_record_amount(
			plan=plan,
			team=getattr(usage_record, "team", None),
			billable_seats=usage_record.billable_seats,
			reference_at=getattr(usage_record, "snapshot_taken_at", None) or usage_record.date,
		)
		if flt(amount, 2) <= 0:
			continue

		frappe.db.set_value("Usage Record", usage_record.name, "amount", amount, update_modified=False)
