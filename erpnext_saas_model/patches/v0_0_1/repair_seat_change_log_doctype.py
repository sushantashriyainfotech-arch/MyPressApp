from __future__ import annotations

# pyrefly: ignore [missing-import]
import frappe
from frappe.modules.import_file import import_file_by_path


def execute():
	doctype_name = "Seat Change Log"
	expected_module = "Erpnext Saas Model"

	doc_path = frappe.get_app_path(
		"erpnext_saas_model",
		"doctype",
		"seat_change_log",
		"seat_change_log.json",
	)
	import_file_by_path(doc_path, force=True, ignore_version=True)

	if not frappe.db.exists("DocType", doctype_name):
		frappe.throw(f"DocType {doctype_name} could not be imported.")

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
