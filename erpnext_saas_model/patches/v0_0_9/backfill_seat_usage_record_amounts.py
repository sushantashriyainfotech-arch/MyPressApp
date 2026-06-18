from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from erpnext_saas_model.seat_billing import (
	get_seat_usage_record_amount,
	get_seat_usage_record_billable_seats,
)
from erpnext_saas_model.seat_billing import is_seat_based_plan


def execute():
	seat_plan_names = frappe.get_all(
		"Site Plan",
		filters={"billing_type": "Seat Based"},
		pluck="name",
	)
	resource_plan_names = frappe.get_all(
		"Site Plan",
		filters={"billing_type": "Resource Based"},
		pluck="name",
	)

	if seat_plan_names:
		backfill_seat_usage_record_amounts(seat_plan_names)
	if resource_plan_names:
		backfill_resource_usage_record_amounts(resource_plan_names)


def backfill_seat_usage_record_amounts(seat_plan_names):
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

		plan = frappe.get_cached_doc("Site Plan", usage_record.plan)
		if not is_seat_based_plan(plan):
			continue

		billable_seats = get_seat_usage_record_billable_seats(
			{
				"billable_seats": getattr(usage_record, "billable_seats", 0),
				"team": getattr(usage_record, "team", None),
				"site": getattr(usage_record, "site", None),
				"document_type": getattr(usage_record, "document_type", None),
				"document_name": getattr(usage_record, "document_name", None),
				"plan": usage_record.plan,
				"plan_type": "Site Plan",
			},
		)
		if not billable_seats:
			continue

		amount = get_seat_usage_record_amount(
			plan=plan,
			team=getattr(usage_record, "team", None),
			billable_seats=billable_seats,
			reference_at=getattr(usage_record, "snapshot_taken_at", None) or usage_record.date,
		)
		if flt(amount, 2) <= 0:
			continue

		frappe.db.set_value("Usage Record", usage_record.name, "billable_seats", billable_seats, update_modified=False)
		frappe.db.set_value("Usage Record", usage_record.name, "amount", amount, update_modified=False)


def backfill_resource_usage_record_amounts(resource_plan_names):
	if not resource_plan_names:
		return

	usage_records = frappe.get_all(
		"Usage Record",
		filters={
			"plan_type": "Site Plan",
			"plan": ("in", resource_plan_names),
			"docstatus": 1,
		},
		fields=[
			"name",
			"plan",
			"team",
			"amount",
			"interval",
			"document_type",
			"document_name",
			"additional_storage",
		],
		order_by="creation asc",
	)

	for usage_record in usage_records:
		if flt(getattr(usage_record, "amount", 0) or 0, 2) > 0:
			continue

		plan = frappe.get_cached_doc("Site Plan", usage_record.plan)
		team = frappe.get_cached_doc("Team", usage_record.team) if getattr(usage_record, "team", None) else None
		if team and team.parent_team:
			team = frappe.get_cached_doc("Team", team.parent_team)
		if team and team.billing_team and team.payment_mode == "Paid By Partner":
			team = frappe.get_cached_doc("Team", team.billing_team)

		amount = get_resource_usage_record_amount(
			plan=plan,
			team_currency=getattr(team, "currency", None) if team else None,
			interval=getattr(usage_record, "interval", None),
			additional_storage=getattr(usage_record, "additional_storage", None),
		)
		if flt(amount, 2) <= 0:
			continue

		frappe.db.set_value("Usage Record", usage_record.name, "amount", amount, update_modified=False)


def get_resource_usage_record_amount(
	plan,
	team_currency: str | None,
	interval: str | None,
	additional_storage: int | None = None,
) -> float:
	team_currency = (team_currency or "USD").upper()
	price = getattr(plan, "price_inr", 0) if team_currency == "INR" else getattr(plan, "price_usd", 0)
	price_per_day = flt(price / (getattr(plan, "period", 30) or 30), 2)

	if additional_storage:
		return flt(price_per_day * cint(additional_storage), 2)
	if interval == "Hourly":
		return flt(price_per_day / 24, 2)
	if interval == "Daily":
		return price_per_day
	if interval == "Monthly":
		return flt(price_per_day * 30, 2)
	return flt(price_per_day, 2)
