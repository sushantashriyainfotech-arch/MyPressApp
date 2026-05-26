from __future__ import annotations

# pyrefly: ignore [missing-import]
import frappe


def execute():
	doctype_name = "Seat Change Log"
	expected_module = "Erpnext Saas Model"

	frappe.reload_doc(expected_module, "doctype", "seat_change_log", force=True)

	current_module = frappe.db.get_value("DocType", doctype_name, "module")
	if current_module != expected_module:
		frappe.db.set_value(
			"DocType",
			doctype_name,
			"module",
			expected_module,
			update_modified=False,
		)
	frappe.clear_cache(doctype=doctype_name)
