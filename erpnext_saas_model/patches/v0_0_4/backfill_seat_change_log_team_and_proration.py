from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from erpnext_saas_model.seat_billing import _calculate_seat_change_proration_amount


def execute():
	seat_change_logs = frappe.get_all(
		"Seat Change Log",
		fields=[
			"name",
			"subscription",
			"team",
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
