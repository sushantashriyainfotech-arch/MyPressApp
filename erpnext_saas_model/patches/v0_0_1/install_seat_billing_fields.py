from __future__ import annotations

# pyrefly: ignore [missing-import]
import frappe
# pyrefly: ignore [missing-import]
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.utils import flt


def _ensure_custom_field(doctype: str, fieldname: str, df: dict) -> None:
	custom_field_name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname})
	if custom_field_name:
		custom_field = frappe.get_doc("Custom Field", custom_field_name)
		if getattr(custom_field, "fieldtype", None) != df.get("fieldtype"):
			frappe.delete_doc("Custom Field", custom_field_name, force=1, ignore_permissions=True)
			create_custom_field(doctype, df, ignore_validate=True)
			return
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
	ensure_existing_seat_prices_are_migrated()


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
		"min_seats",
		{
			"label": "Minimum Seats",
			"fieldname": "min_seats",
			"fieldtype": "Int",
			"default": "1",
			"depends_on": "eval:doc.billing_type == 'Seat Based'",
			"insert_after": "billing_type",
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
			"hidden": 0,
			"insert_after": "plan",
		},
	)


def ensure_subscription_fields():
	_ensure_custom_field(
		"Subscription",
		"currency",
		{
			"label": "Currency",
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"fetch_from": "team.currency",
			"fetch_if_empty": 1,
			"depends_on": "eval:doc.plan_type == 'Site Plan'",
			"insert_after": "billable_seats",
		},
	)
	_ensure_custom_field(
		"Subscription",
		"billable_seats",
		{
			"label": "Billable Seats",
			"fieldname": "billable_seats",
			"fieldtype": "Int",
			"default": "1",
			"fetch_from": "plan.min_seats",
			"fetch_if_empty": 1,
			"depends_on": "eval:doc.plan_type == 'Site Plan'",
			"insert_after": "plan",
		},
	)
	_ensure_custom_field(
		"Subscription",
		"price_inr",
		{
			"label": "Price (INR)",
			"fieldname": "price_inr",
			"fieldtype": "Currency",
			"options": "INR",
			"fetch_from": "plan.price_inr",
			"fetch_if_empty": 1,
			"depends_on": "eval:doc.plan_type == 'Site Plan'",
			"insert_after": "billable_seats",
		},
	)
	_ensure_custom_field(
		"Subscription",
		"price_usd",
		{
			"label": "Price (USD)",
			"fieldname": "price_usd",
			"fieldtype": "Currency",
			"options": "USD",
			"fetch_from": "plan.price_usd",
			"fetch_if_empty": 1,
			"depends_on": "eval:doc.plan_type == 'Site Plan'",
			"insert_after": "price_inr",
		},
	)
	_ensure_custom_field(
		"Subscription",
		"total_amount",
		{
			"label": "Total Amount",
			"fieldname": "total_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"depends_on": "eval:doc.plan_type == 'Site Plan'",
			"insert_after": "price_usd",
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
	migrate_usage_record_seat_amount_to_amount()
	remove_usage_record_seat_amount_field()
	_ensure_custom_field(
		"Usage Record",
		"snapshot_taken_at",
		{
			"label": "Snapshot Taken At",
			"fieldname": "snapshot_taken_at",
			"fieldtype": "Datetime",
			"insert_after": "billable_seats",
		},
	)


def remove_usage_record_seat_amount_field():
	custom_field_name = frappe.db.get_value("Custom Field", {"dt": "Usage Record", "fieldname": "seat_amount"})
	if not custom_field_name:
		return

	frappe.delete_doc("Custom Field", custom_field_name, ignore_permissions=True, force=True)


def migrate_usage_record_seat_amount_to_amount():
	if not frappe.db.has_column("Usage Record", "seat_amount"):
		return

	usage_records = frappe.get_all(
		"Usage Record",
		fields=["name", "date", "seat_amount", "amount"],
		filters={"plan_type": "Site Plan"},
	)
	for usage_record in usage_records:
		if usage_record.seat_amount is None:
			continue
		days_in_month = frappe.utils.get_last_day(usage_record.date).day or 30
		amount = flt(usage_record.seat_amount / days_in_month, 2)
		if flt(usage_record.amount or 0, 2) == amount:
			continue
		frappe.db.set_value("Usage Record", usage_record.name, "amount", amount, update_modified=False)


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
		"price_inr",
		{
			"label": "Price (INR)",
			"fieldname": "price_inr",
			"fieldtype": "Currency",
			"options": "INR",
			"insert_after": "billable_seats",
		},
	)
	_ensure_custom_field(
		"Invoice",
		"price_usd",
		{
			"label": "Price (USD)",
			"fieldname": "price_usd",
			"fieldtype": "Currency",
			"options": "USD",
			"insert_after": "price_inr",
		},
	)


def ensure_invoice_item_fields():
	_ensure_custom_field(
		"Invoice Item",
		"usage_record",
		{
			"label": "Usage Record",
			"fieldname": "usage_record",
			"fieldtype": "Data",
			"options": "",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "document_name",
		},
	)
	_ensure_custom_field(
		"Invoice Item",
		"billable_seats",
		{
			"label": "Billable Seats",
			"fieldname": "billable_seats",
			"fieldtype": "Int",
			"insert_after": "usage_record",
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


def ensure_existing_seat_prices_are_migrated():
	frappe.db.sql(
		"""
		UPDATE `tabSubscription`
		SET
			`currency` = COALESCE(NULLIF(`currency`, ''), (SELECT `currency` FROM `tabTeam` WHERE `tabTeam`.`name` = `tabSubscription`.`team`))
		WHERE IFNULL(`plan_type`, '') = 'Site Plan'
		"""
	)
	frappe.db.commit()
