from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.utils import cint, flt

from erpnext_saas_model.seat_billing import (
	get_seat_change_log_for_reference,
	get_seat_usage_record_remark,
	is_seat_based_plan,
)


def execute():
	ensure_invoice_item_fields()
	backfill_usage_record_billable_seats_and_remarks()
	backfill_invoice_item_billable_seats()
	normalize_draft_seat_invoice_items()


def _has_column(doctype: str, fieldname: str) -> bool:
	has_column = getattr(frappe.db, "has_column", None)
	if callable(has_column):
		try:
			return bool(has_column(doctype, fieldname))
		except Exception:
			return False

	return bool(frappe.db.get_value("DocField", {"parent": doctype, "fieldname": fieldname}, "name"))


def ensure_invoice_item_fields():
	custom_field_name = frappe.db.get_value("Custom Field", {"dt": "Invoice Item", "fieldname": "billable_seats"})
	if custom_field_name:
		custom_field = frappe.get_doc("Custom Field", custom_field_name)
		changed = False
		for key, value in {
			"label": "Billable Seats",
			"fieldname": "billable_seats",
			"fieldtype": "Int",
			"insert_after": "usage_record",
		}.items():
			if getattr(custom_field, key, None) != value:
				setattr(custom_field, key, value)
				changed = True
		if changed:
			custom_field.save(ignore_permissions=True)
		return

	create_custom_field(
		"Invoice Item",
		{
			"label": "Billable Seats",
			"fieldname": "billable_seats",
			"fieldtype": "Int",
			"insert_after": "usage_record",
		},
		ignore_validate=True,
	)


def backfill_invoice_item_billable_seats():
	seat_plan_names = frappe.get_all(
		"Site Plan",
		filters={"billing_type": "Seat Based"},
		pluck="name",
	)
	if not seat_plan_names:
		return

	invoice_items = frappe.get_all(
		"Invoice Item",
		filters={"plan": ("in", seat_plan_names)},
		fields=[
			"name",
			"parent",
			"document_type",
			"document_name",
			"plan",
			"usage_record",
			"billable_seats",
		],
		order_by="creation asc",
	)

	for invoice_item in invoice_items:
		billable_seats = _get_billable_seats_for_invoice_item(invoice_item)
		if billable_seats is None:
			continue

		if cint(getattr(invoice_item, "billable_seats", 0) or 0) == billable_seats:
			continue

		frappe.db.set_value(
			"Invoice Item",
			invoice_item.name,
			"billable_seats",
			billable_seats,
			update_modified=False,
		)


def backfill_usage_record_billable_seats_and_remarks():
	include_team = _has_column("Usage Record", "team")
	fields = [
		"name",
		"remark",
		"billable_seats",
		"subscription",
		"date",
		"snapshot_taken_at",
		"seat_change_log",
	]
	if include_team:
		fields.insert(4, "team")

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
		fields=fields,
		order_by="creation asc",
	)

	for usage_record in usage_records:
		seat_change_log = usage_record.seat_change_log or get_seat_change_log_for_reference(
			usage_record.subscription,
			getattr(usage_record, "snapshot_taken_at", None) or usage_record.date,
			team=getattr(usage_record, "team", None),
		)
		remark = get_seat_usage_record_remark(
			subscription=usage_record.subscription,
			team=getattr(usage_record, "team", None),
			reference_at=getattr(usage_record, "snapshot_taken_at", None) or usage_record.date,
			seat_change_log=seat_change_log,
			fallback_billable_seats=usage_record.billable_seats,
		)

		updates = {}
		if getattr(usage_record, "seat_change_log", None) != getattr(seat_change_log, "name", None):
			updates["seat_change_log"] = getattr(seat_change_log, "name", None)
		if getattr(usage_record, "remark", None) != remark:
			updates["remark"] = remark
		snapshot_billable_seats = _get_usage_record_billable_seats(usage_record, seat_change_log)
		if snapshot_billable_seats is not None and cint(getattr(usage_record, "billable_seats", 0) or 0) != snapshot_billable_seats:
			updates["billable_seats"] = snapshot_billable_seats

		for fieldname, value in updates.items():
			if value is None:
				continue
			frappe.db.set_value("Usage Record", usage_record.name, fieldname, value, update_modified=False)


def normalize_draft_seat_invoice_items():
	invoice_names = frappe.get_all(
		"Invoice",
		filters={
			"type": "Subscription",
			"docstatus": 0,
		},
		pluck="name",
	)

	for invoice_name in invoice_names:
		invoice = frappe.get_doc("Invoice", invoice_name)
		if _normalize_invoice_items(invoice):
			invoice.save(ignore_permissions=True)


def _normalize_invoice_items(invoice) -> bool:
	normalized_items = []
	changed = False
	last_seat_item = None

	for item in invoice.items:
		if not _is_seat_invoice_item(item):
			normalized_items.append(item)
			last_seat_item = None
			continue

		billable_seats = _get_billable_seats_for_invoice_item(item)
		description = _get_invoice_item_description(item)
		rate = flt(getattr(item, "rate", 0) or 0, 2)
		item.billable_seats = billable_seats
		if description and not getattr(item, "description", None):
			item.description = description

		if last_seat_item and _seat_invoice_item_matches(last_seat_item, item, billable_seats, description, rate):
			last_seat_item.quantity = flt((last_seat_item.quantity or 0) + (item.quantity or 0), 2)
			last_seat_item.amount = flt((last_seat_item.quantity or 0) * flt(last_seat_item.rate or rate, 2), 2)
			if not getattr(last_seat_item, "billable_seats", None):
				last_seat_item.billable_seats = billable_seats
			if not getattr(last_seat_item, "usage_record", None):
				last_seat_item.usage_record = getattr(item, "usage_record", None)
			if not getattr(last_seat_item, "seat_change_log", None):
				last_seat_item.seat_change_log = getattr(item, "seat_change_log", None)
			changed = True
			continue

		normalized_items.append(item)
		last_seat_item = item

	if changed:
		invoice.set("items", normalized_items)
	return changed


def _is_seat_invoice_item(item) -> bool:
	if not getattr(item, "plan", None):
		return False

	plan = frappe.get_cached_doc("Site Plan", item.plan)
	return is_seat_based_plan(plan)


def _seat_invoice_item_matches(item, usage_item, billable_seats: int, description: str, rate: float) -> bool:
	if getattr(item, "document_type", None) != getattr(usage_item, "document_type", None):
		return False
	if getattr(item, "document_name", None) != getattr(usage_item, "document_name", None):
		return False
	if getattr(item, "plan", None) != getattr(usage_item, "plan", None):
		return False
	if getattr(item, "document_type", None) == "Marketplace App" and getattr(item, "site", None) != getattr(usage_item, "site", None):
		return False
	if cint(getattr(item, "billable_seats", 0) or 0) != cint(billable_seats or 0):
		return False
	if (getattr(item, "description", None) or "") != (description or ""):
		return False
	if flt(getattr(item, "rate", 0) or 0, 2) != flt(rate or 0, 2):
		return False
	return True


def _get_billable_seats_for_invoice_item(invoice_item) -> int | None:
	billable_seats = cint(getattr(invoice_item, "billable_seats", 0) or 0)
	if billable_seats:
		return billable_seats

	usage_record = _get_usage_record_for_invoice_item(invoice_item)
	if usage_record:
		billable_seats = cint(getattr(usage_record, "billable_seats", 0) or 0)
		if billable_seats:
			return billable_seats

	return None


def _get_invoice_item_description(invoice_item) -> str:
	description = getattr(invoice_item, "description", None)
	if description:
		return description

	usage_record = _get_usage_record_for_invoice_item(invoice_item)
	if not usage_record:
		return ""

	return (
		getattr(usage_record, "remark", None)
		or get_seat_usage_record_remark(
			subscription=getattr(usage_record, "subscription", None),
			team=getattr(usage_record, "team", None),
			reference_at=getattr(usage_record, "snapshot_taken_at", None) or getattr(usage_record, "date", None),
			fallback_billable_seats=getattr(usage_record, "billable_seats", None),
		)
		or ""
	)


def _get_usage_record_for_invoice_item(invoice_item):
	usage_record_name = getattr(invoice_item, "usage_record", None)
	if usage_record_name and frappe.db.exists("Usage Record", usage_record_name):
		return frappe.get_doc("Usage Record", usage_record_name)

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
			"team",
			"date",
			"snapshot_taken_at",
			"billable_seats",
			"remark",
		],
		order_by="creation asc",
	)

	return usage_records[0] if usage_records else None


def _get_usage_record_billable_seats(usage_record, seat_change_log=None) -> int | None:
	if seat_change_log:
		if isinstance(seat_change_log, dict):
			new_seats = cint(seat_change_log.get("new_seats", 0) or 0)
		else:
			new_seats = cint(getattr(seat_change_log, "new_seats", 0) or 0)
		if new_seats:
			return new_seats

	if cint(getattr(usage_record, "billable_seats", 0) or 0):
		return cint(getattr(usage_record, "billable_seats", 0) or 0)

	if getattr(usage_record, "seat_change_log", None):
		seat_change_log = frappe.get_doc("Seat Change Log", usage_record.seat_change_log)
		return cint(getattr(seat_change_log, "new_seats", 0) or 0) or None

	return None
