from __future__ import annotations

# pyrefly: ignore [missing-import]
import frappe
# pyrefly: ignore [missing-import]
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def _ensure_custom_field(doctype: str, fieldname: str, df: dict) -> None:
	custom_field_name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname})
	if custom_field_name:
		custom_field = frappe.get_doc("Custom Field", custom_field_name)
		changed = False
		for key, value in df.items():
			if getattr(custom_field, key, None) != value:
				setattr(custom_field, key, value)
				changed = True
		if changed:
			custom_field.save(ignore_permissions=True)
		return

	create_custom_field(doctype, df, ignore_validate=True)


def execute():
	ensure_site_plan_fields()
	ensure_site_fields()
	ensure_subscription_fields()
	ensure_usage_record_fields()
	ensure_invoice_fields()
	ensure_invoice_item_fields()
	ensure_existing_site_plans_remain_resource_based()


def ensure_site_plan_fields():
	_ensure_custom_field(
		"Site Plan",
		"billing_type",
		{
			"label": "Billing Type",
			"fieldname": "billing_type",
			"fieldtype": "Select",
			"options": "Seat Based\nResource Based",
			"default": "Resource Based",
			"insert_after": "plan_title",
		},
	)
	_ensure_custom_field(
		"Site Plan",
		"price_per_seat",
		{
			"label": "Price Per Seat",
			"fieldname": "price_per_seat",
			"fieldtype": "Currency",
			"options": "INR",
			"mandatory_depends_on": "eval:doc.billing_type == 'Seat Based'",
			"insert_after": "billing_type",
		},
	)
	_ensure_custom_field(
		"Site Plan",
		"min_seats",
		{
			"label": "Minimum Seats",
			"fieldname": "min_seats",
			"fieldtype": "Int",
			"default": "1",
			"depends_on": "eval:doc.billing_type == 'Seat Based'",
			"insert_after": "price_per_seat",
		},
	)
	_ensure_custom_field(
		"Site Plan",
		"max_seats",
		{
			"label": "Maximum Seats",
			"fieldname": "max_seats",
			"fieldtype": "Int",
			"depends_on": "eval:doc.billing_type == 'Seat Based'",
			"insert_after": "min_seats",
		},
	)
	_ensure_custom_field(
		"Site Plan",
		"next_plan",
		{
			"label": "Next Plan",
			"fieldname": "next_plan",
			"fieldtype": "Link",
			"options": "Site Plan",
			"depends_on": "eval:doc.billing_type == 'Seat Based'",
			"insert_after": "max_seats",
		},
	)


def ensure_site_fields():
	_ensure_custom_field(
		"Site",
		"billable_seats",
		{
			"label": "Billable Seats",
			"fieldname": "billable_seats",
			"fieldtype": "Int",
			"default": "1",
			"hidden": 1,
			"insert_after": "plan",
		},
	)


def ensure_subscription_fields():
	_ensure_custom_field(
		"Subscription",
		"billable_seats",
		{
			"label": "Billable Seats",
			"fieldname": "billable_seats",
			"fieldtype": "Int",
			"default": "1",
			"insert_after": "plan",
		},
	)
	_ensure_custom_field(
		"Subscription",
		"price_per_seat",
		{
			"label": "Price Per Seat",
			"fieldname": "price_per_seat",
			"fieldtype": "Currency",
			"options": "INR",
			"insert_after": "billable_seats",
		},
	)
	_ensure_custom_field(
		"Subscription",
		"total_amount",
		{
			"label": "Total Amount",
			"fieldname": "total_amount",
			"fieldtype": "Currency",
			"options": "INR",
			"insert_after": "price_per_seat",
		},
	)
	_ensure_custom_field(
		"Subscription",
		"seats_last_updated",
		{
			"label": "Seats Last Updated",
			"fieldname": "seats_last_updated",
			"fieldtype": "Datetime",
			"insert_after": "total_amount",
		},
	)


def ensure_usage_record_fields():
	_ensure_custom_field(
		"Usage Record",
		"billable_seats",
		{
			"label": "Billable Seats",
			"fieldname": "billable_seats",
			"fieldtype": "Int",
			"insert_after": "subscription",
		},
	)
	_ensure_custom_field(
		"Usage Record",
		"seat_amount",
		{
			"label": "Seat Amount",
			"fieldname": "seat_amount",
			"fieldtype": "Currency",
			"options": "INR",
			"insert_after": "billable_seats",
		},
	)
	_ensure_custom_field(
		"Usage Record",
		"snapshot_taken_at",
		{
			"label": "Snapshot Taken At",
			"fieldname": "snapshot_taken_at",
			"fieldtype": "Datetime",
			"insert_after": "seat_amount",
		},
	)


def ensure_invoice_fields():
	_ensure_custom_field(
		"Invoice",
		"billable_seats",
		{
			"label": "Billable Seats",
			"fieldname": "billable_seats",
			"fieldtype": "Int",
			"insert_after": "total",
		},
	)
	_ensure_custom_field(
		"Invoice",
		"price_per_seat",
		{
			"label": "Price Per Seat",
			"fieldname": "price_per_seat",
			"fieldtype": "Currency",
			"options": "INR",
			"insert_after": "billable_seats",
		},
	)


def ensure_invoice_item_fields():
	_ensure_custom_field(
		"Invoice Item",
		"usage_record",
		{
			"label": "Usage Record",
			"fieldname": "usage_record",
			"fieldtype": "Link",
			"options": "Usage Record",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "document_name",
		},
	)


def ensure_existing_site_plans_remain_resource_based():
	frappe.db.sql(
		"""
		UPDATE `tabSite Plan`
		SET `billing_type` = 'Resource Based'
		WHERE IFNULL(`billing_type`, '') = ''
		"""
	)
	frappe.db.commit()
