from __future__ import annotations

import frappe
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
	# Keep seat change logs attached to Team/Subscription/Site only.
	# Invoice and Usage Record keep the log name as plain metadata so deletes
	# do not inherit hard link validation from Frappe.
	_ensure_custom_field(
		"Usage Record",
		"seat_change_log",
		{
			"label": "Seat Change Log",
			"fieldname": "seat_change_log",
			"fieldtype": "Data",
			"options": "",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "snapshot_taken_at",
		},
	)
	_ensure_custom_field(
		"Invoice Item",
		"seat_change_log",
		{
			"label": "Seat Change Log",
			"fieldname": "seat_change_log",
			"fieldtype": "Data",
			"options": "",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "usage_record",
		},
	)
