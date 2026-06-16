from __future__ import annotations

import frappe
from frappe.modules.import_file import import_file_by_path


def execute():
	doc_path = frappe.get_app_path(
		"erpnext_saas_model",
		"doctype",
		"seat_change_log",
		"seat_change_log.json",
	)
	import_file_by_path(doc_path, force=True, ignore_version=True)
	frappe.clear_cache(doctype="Seat Change Log")
