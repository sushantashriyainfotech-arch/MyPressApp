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
	backfill_currency_from_team()
	frappe.clear_cache(doctype="Seat Change Log")


def backfill_currency_from_team():
	seat_change_logs = frappe.get_all(
		"Seat Change Log",
		fields=["name", "team", "subscription", "currency"],
		order_by="creation asc",
	)

	for seat_change_log in seat_change_logs:
		team = getattr(seat_change_log, "team", None)
		if not team and getattr(seat_change_log, "subscription", None):
			team = frappe.db.get_value("Subscription", seat_change_log.subscription, "team")

		if not team:
			continue

		currency = (frappe.db.get_value("Team", team, "currency") or "USD").upper()
		if currency == (getattr(seat_change_log, "currency", None) or "").upper():
			continue

		frappe.db.set_value(
			"Seat Change Log",
			seat_change_log.name,
			"currency",
			currency,
			update_modified=False,
		)
