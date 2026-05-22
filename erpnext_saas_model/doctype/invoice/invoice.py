from __future__ import annotations

import frappe
from frappe.utils import cint, flt, fmt_money

from press.press.doctype.invoice.invoice import Invoice as PressInvoice

from erpnext_saas_model.seat_billing import is_seat_based_plan


class Invoice(PressInvoice):
	def _is_seat_usage_record(self, usage_record) -> bool:
		if not usage_record.plan:
			return False

		plan = frappe.get_cached_doc(usage_record.plan_type, usage_record.plan)
		return is_seat_based_plan(plan)

	def add_usage_record(self, usage_record):
		if not self._is_seat_usage_record(usage_record):
			if hasattr(PressInvoice, "add_usage_record"):
				return PressInvoice.add_usage_record(self, usage_record)
			return
		if self.type != "Subscription":
			return

		if usage_record.invoice:
			return

		usage_record_date = frappe.utils.getdate(usage_record.date)
		start = frappe.utils.getdate(self.period_start)
		end = frappe.utils.getdate(self.period_end)
		if not (start <= usage_record_date <= end):
			return

		plan = frappe.get_cached_doc(usage_record.plan_type, usage_record.plan)
		billable_seats = cint(getattr(usage_record, "billable_seats", 0) or 0)
		seat_amount = flt(getattr(usage_record, "seat_amount", 0) or 0, 2)
		price_per_seat = flt(seat_amount / billable_seats, 2) if billable_seats else seat_amount
		description = (
			f"{getattr(plan, 'plan_title', None) or plan.name} — {billable_seats} seats × "
			f"{fmt_money(price_per_seat, 2, self.currency)} = {fmt_money(seat_amount, 2, self.currency)}"
		)

		self.append(
			"items",
			{
				"document_type": usage_record.document_type,
				"document_name": usage_record.document_name,
				"plan": usage_record.plan,
				"quantity": billable_seats,
				"rate": price_per_seat,
				"amount": seat_amount,
				"site": usage_record.site,
				"description": description,
				"usage_record": usage_record.name,
			},
		)
		self.save()
		usage_record.db_set("invoice", self.name)

	def remove_usage_record(self, usage_record):
		if not self._is_seat_usage_record(usage_record):
			if hasattr(PressInvoice, "remove_usage_record"):
				return PressInvoice.remove_usage_record(self, usage_record)
			return
		if self.type != "Subscription":
			return

		if self.docstatus != 0:
			return
		if usage_record.invoice != self.name:
			return

		for row in self.items:
			if getattr(row, "usage_record", None) == usage_record.name:
				self.remove(row)
				self.save()
				usage_record.db_set("invoice", None)
				return

	def get_invoice_item_for_usage_record(self, usage_record):
		if self._is_seat_usage_record(usage_record):
			for row in self.items:
				if getattr(row, "usage_record", None) == usage_record.name:
					return row
			return None

		if hasattr(PressInvoice, "get_invoice_item_for_usage_record"):
			return PressInvoice.get_invoice_item_for_usage_record(self, usage_record)
		return None

	def validate_items(self):
		for row in self.items:
			if getattr(row, "usage_record", None):
				row.amount = flt((cint(row.quantity) * flt(row.rate or 0, 2)), 2)
		if hasattr(PressInvoice, "validate_items"):
			return PressInvoice.validate_items(self)

	def update_item_descriptions(self):
		for item in self.items:
			if not item.plan:
				continue
			plan = frappe.get_cached_doc("Site Plan", item.plan)
			if not is_seat_based_plan(plan):
				continue
			total = flt(item.amount, 2)
			item.description = (
				f"{getattr(plan, 'plan_title', None) or plan.name} — {cint(item.quantity)} seats × "
				f"{fmt_money(flt(item.rate or 0, 2), 2, self.currency)} = {fmt_money(total, 2, self.currency)}"
			)

		if hasattr(PressInvoice, "update_item_descriptions"):
			PressInvoice.update_item_descriptions(self)

	def before_validate(self):
		if hasattr(PressInvoice, "before_validate"):
			PressInvoice.before_validate(self)
		seat_items = [
			item
			for item in self.items
			if item.plan and is_seat_based_plan(frappe.get_cached_doc("Site Plan", item.plan))
		]
		if not seat_items:
			return

		latest_item = seat_items[-1]
		self.billable_seats = cint(latest_item.quantity or 0)
		self.price_per_seat = flt(latest_item.rate or 0, 2)
