from __future__ import annotations

# pyrefly: ignore [missing-import]
import frappe


def execute():
	doctype_name = "Seat Change Log"
	expected_module = "Erpnext Saas Model"

	doctype = frappe.get_doc("DocType", doctype_name)
	if getattr(doctype, "module", None) != expected_module:
		doctype.module = expected_module
		doctype.save(ignore_permissions=True)

	frappe.clear_cache(doctype=doctype_name)
