from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.utils import cint, flt

from erpnext_saas_model.seat_billing import _calculate_seat_change_proration_amount


def execute():
	ensure_team_field()
	ensure_standard_filters()
	seat_change_logs = frappe.get_all(
		"Seat Change Log",
		fields=[
			"name",
			"subscription",
			"old_seats",
			"new_seats",
			"access_updated_at",
			"billing_effective_from",
			"proration_amount",
		],
		order_by="creation asc",
	)

	for seat_change_log in seat_change_logs:
		team = getattr(seat_change_log, "team", None)
		if not team and getattr(seat_change_log, "subscription", None):
			team = frappe.db.get_value("Subscription", seat_change_log.subscription, "team")
			if team:
				frappe.db.set_value(
					"Seat Change Log",
					seat_change_log.name,
					"team",
					team,
					update_modified=False,
				)

		if getattr(seat_change_log, "proration_amount", None) not in (None, ""):
			continue

		subscription = getattr(seat_change_log, "subscription", None)
		if not subscription:
			continue

		subscription_doc = frappe.get_cached_doc("Subscription", subscription)
		proration_amount = _calculate_seat_change_proration_amount(
			subscription_doc,
			old_seats=cint(getattr(seat_change_log, "old_seats", 0) or 0),
			new_seats=cint(getattr(seat_change_log, "new_seats", 0) or 0),
			access_updated_at=getattr(seat_change_log, "access_updated_at", None),
			billing_effective_from=getattr(seat_change_log, "billing_effective_from", None),
		)
		frappe.db.set_value(
			"Seat Change Log",
			seat_change_log.name,
			"proration_amount",
			flt(proration_amount, 2),
			update_modified=False,
		)


def ensure_team_field():
	custom_field_name = frappe.db.get_value("Custom Field", {"dt": "Seat Change Log", "fieldname": "team"})
	if custom_field_name:
		custom_field = frappe.get_doc("Custom Field", custom_field_name)
		changed = False
		for key, value in {
			"label": "Team",
			"fieldtype": "Link",
			"options": "Team",
			"reqd": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
		}.items():
			if getattr(custom_field, key, None) != value:
				setattr(custom_field, key, value)
				changed = True
		if changed:
			custom_field.save(ignore_permissions=True)
		return

	create_custom_field(
		"Seat Change Log",
		{
			"label": "Team",
			"fieldname": "team",
			"fieldtype": "Link",
			"options": "Team",
			"reqd": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"insert_after": "subscription",
		},
		ignore_validate=True,
	)


def ensure_standard_filters():
	for fieldname in (
		"subscription",
		"team",
		"site",
		"change_type",
		"access_updated_at",
		"billing_effective_from",
		"changed_by",
	):
		ensure_docfield_flag("Seat Change Log", fieldname, "in_standard_filter", 1)

	frappe.clear_cache(doctype="Seat Change Log")


def ensure_docfield_flag(doctype: str, fieldname: str, flag: str, value: int) -> None:
	docfield_name = frappe.db.get_value("DocField", {"parent": doctype, "fieldname": fieldname}, "name")
	if not docfield_name:
		return

	if frappe.db.get_value("DocField", docfield_name, flag) == value:
		return

	frappe.db.set_value("DocField", docfield_name, flag, value, update_modified=False)
