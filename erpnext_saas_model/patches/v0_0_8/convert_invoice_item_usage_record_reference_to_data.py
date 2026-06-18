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
	# Invoice Item.usage_record is a descriptive pointer, not a true ownership link.
	# Keeping it as a Link causes cancel/delete operations to fail once a usage record is cancelled.
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
