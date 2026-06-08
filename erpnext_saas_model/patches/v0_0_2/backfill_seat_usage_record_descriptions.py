from __future__ import annotations

import frappe
from frappe.utils import flt, getdate

from erpnext_saas_model.seat_billing import get_seat_usage_record_remark

LEGACY_SEAT_DESCRIPTION_PREFIXES = ("Seats changed", "Billable seats change record")


def execute():
	seat_plan_names = frappe.get_all(
		"Site Plan",
		filters={"billing_type": "Seat Based"},
		pluck="name",
	)
	if not seat_plan_names:
		return

	backfill_usage_record_remarks(seat_plan_names)
	backfill_invoice_item_descriptions(seat_plan_names)


def backfill_usage_record_remarks(seat_plan_names):
	usage_records = frappe.get_all(
		"Usage Record",
		filters={
			"plan_type": "Site Plan",
			"plan": ("in", seat_plan_names),
			"docstatus": 1,
		},
		fields=["name", "remark", "billable_seats", "subscription", "date", "snapshot_taken_at"],
		order_by="creation asc",
	)

	for usage_record in usage_records:
		remark = get_seat_usage_record_remark(
			subscription=usage_record.subscription,
			reference_at=usage_record.date,
			fallback_billable_seats=usage_record.billable_seats,
		)
		if usage_record.remark == remark:
			continue

		frappe.db.set_value(
			"Usage Record",
			usage_record.name,
			"remark",
			remark,
			update_modified=False,
		)


def backfill_invoice_item_descriptions(seat_plan_names):
	invoice_items = frappe.get_all(
		"Invoice Item",
		filters={"plan": ("in", seat_plan_names)},
		fields=[
			"name",
			"parent",
			"document_type",
			"document_name",
			"plan",
			"rate",
			"description",
			"usage_record",
		],
		order_by="creation asc",
	)

	used_usage_records: set[str] = set()
	for invoice_item in invoice_items:
		if not _should_replace_description(invoice_item.description):
			continue

		usage_record = _get_usage_record_for_invoice_item(invoice_item, used_usage_records)
		if not usage_record:
			continue

		remark = get_seat_usage_record_remark(
			subscription=usage_record.subscription,
			reference_at=usage_record.date,
			fallback_billable_seats=usage_record.billable_seats,
		)
		frappe.db.set_value(
			"Invoice Item",
			invoice_item.name,
			"usage_record",
			usage_record.name,
			update_modified=False,
		)
		frappe.db.set_value(
			"Invoice Item",
			invoice_item.name,
			"description",
			remark,
			update_modified=False,
		)
		used_usage_records.add(usage_record.name)


def _should_replace_description(description: str | None) -> bool:
	if not description:
		return True
	return description.startswith(LEGACY_SEAT_DESCRIPTION_PREFIXES)


def _get_usage_record_for_invoice_item(invoice_item, used_usage_records: set[str]):
	if getattr(invoice_item, "usage_record", None):
		return frappe.get_doc("Usage Record", invoice_item.usage_record)

	usage_records = frappe.get_all(
		"Usage Record",
		filters={
			"invoice": invoice_item.parent,
			"document_type": invoice_item.document_type,
			"document_name": invoice_item.document_name,
			"plan": invoice_item.plan,
			"docstatus": 1,
		},
		fields=[
			"name",
			"subscription",
			"date",
			"billable_seats",
			"seat_amount",
			"amount",
		],
		order_by="creation asc",
	)

	rate = flt(invoice_item.rate or 0, 2)
	for usage_record in usage_records:
		if usage_record.name in used_usage_records:
			continue
		if flt(_get_usage_record_daily_rate(usage_record), 2) != rate:
			continue
		return usage_record

	return None


def _get_usage_record_daily_rate(usage_record) -> float:
	monthly_total = flt(getattr(usage_record, "seat_amount", None) or getattr(usage_record, "amount", 0), 2)
	usage_date = getdate(usage_record.date)
	days_in_month = frappe.utils.get_last_day(usage_date).day or 30
	return flt(monthly_total / days_in_month, 2)
