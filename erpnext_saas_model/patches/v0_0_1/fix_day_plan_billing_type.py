from __future__ import annotations

import frappe


def execute():
	frappe.db.sql(
		"""
		UPDATE `tabSite Plan`
		SET `billing_type` = 'Resource Based'
		WHERE `name` = %s OR `plan_title` = %s
		""",
		("1 Day plan", "1 Day plan"),
	)
	frappe.db.commit()
