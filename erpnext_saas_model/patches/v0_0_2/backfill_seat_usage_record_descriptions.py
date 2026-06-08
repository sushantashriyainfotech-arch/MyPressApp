from __future__ import annotations

import frappe

from erpnext_saas_model.seat_billing import get_seat_usage_record_remark


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
		fields=["name", "remark", "billable_seats", "subscription", "snapshot_taken_at"],
		order_by="creation asc",
	)

	for usage_record in usage_records:
		remark = get_seat_usage_record_remark(
			subscription=usage_record.subscription,
			snapshot_taken_at=usage_record.snapshot_taken_at,
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
		fields=["name", "parent", "document_type", "document_name", "plan", "description"],
		order_by="creation asc",
	)

	for invoice_item in invoice_items:
		if invoice_item.description:
			continue

		usage_record = frappe.get_all(
			"Usage Record",
			filters={
				"invoice": invoice_item.parent,
				"document_type": invoice_item.document_type,
				"document_name": invoice_item.document_name,
				"plan": invoice_item.plan,
				"docstatus": 1,
			},
			fields=["name", "remark", "billable_seats", "subscription", "snapshot_taken_at"],
			order_by="creation desc",
			limit=1,
		)
		if usage_record:
			usage_record = usage_record[0]
			description = get_seat_usage_record_remark(
				subscription=usage_record.subscription,
				snapshot_taken_at=usage_record.snapshot_taken_at,
				fallback_billable_seats=usage_record.billable_seats,
			)
		else:
			description = "Seats changed"

		if not description:
			continue

		frappe.db.set_value(
			"Invoice Item",
			invoice_item.name,
			"description",
			description,
			update_modified=False,
		)
