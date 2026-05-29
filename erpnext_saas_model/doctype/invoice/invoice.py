from __future__ import annotations

import frappe
from frappe.utils import cint, flt, fmt_money

from press.press.doctype.invoice.invoice import Invoice as PressInvoice

from erpnext_saas_model.seat_billing import get_seat_billing_month_fraction, is_seat_based_plan


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

		billable_seats = cint(getattr(usage_record, "billable_seats", 0) or 0)
		seat_amount = flt(getattr(usage_record, "seat_amount", 0) or getattr(usage_record, "amount", 0), 2)
		quantity_increment = get_seat_billing_month_fraction(usage_record.date)

		invoice_item = self.get_invoice_item_for_usage_record(usage_record)
		if not invoice_item:
			invoice_item = self.append(
				"items",
				{
					"document_type": usage_record.document_type,
					"document_name": usage_record.document_name,
					"plan": usage_record.plan,
					"quantity": 0,
					"rate": seat_amount,
					"site": usage_record.site,
				},
			)

		invoice_item.quantity = flt((invoice_item.quantity or 0) + quantity_increment, 8)
		if billable_seats and getattr(invoice_item.meta, "get_field", None) and invoice_item.meta.get_field(
			"custom_no_of_seats"
		):
			invoice_item.custom_no_of_seats = billable_seats

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

		quantity_increment = get_seat_billing_month_fraction(usage_record.date)

		for row in self.items:
			conditions = (
				row.document_type == usage_record.document_type
				and row.document_name == usage_record.document_name
				and row.plan == usage_record.plan
				and row.rate == usage_record.amount
			)
			if row.document_type == "Marketplace App":
				conditions = conditions and row.site == usage_record.site

			if not conditions:
				continue

			if flt(row.quantity or 0, 8) <= 0:
				return

			row.quantity = flt((row.quantity or 0) - quantity_increment, 8)
			self.save()
			usage_record.db_set("invoice", None)
			return

	def get_invoice_item_for_usage_record(self, usage_record):
		if self._is_seat_usage_record(usage_record):
			for row in self.items:
				conditions = (
					row.document_type == usage_record.document_type
					and row.document_name == usage_record.document_name
					and row.plan == usage_record.plan
					and row.rate == usage_record.amount
				)
				if row.document_type == "Marketplace App":
					conditions = conditions and row.site == usage_record.site
				if conditions:
					return row
			return None

		if hasattr(PressInvoice, "get_invoice_item_for_usage_record"):
			return PressInvoice.get_invoice_item_for_usage_record(self, usage_record)
		return None

	def validate_items(self):
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
			days_in_month = frappe.utils.get_last_day(frappe.utils.getdate(self.period_start or self.period_end or frappe.utils.today())).day or 30
			used_days = int(round(flt(item.quantity or 0, 8) * days_in_month))
			seats = cint(getattr(item, "custom_no_of_seats", 0) or 0)
			if seats:
				item.description = (
					f"{getattr(plan, 'plan_title', None) or plan.name} — {seats} seats for "
					f"{used_days} of {days_in_month} days = {fmt_money(total, 2, self.currency)}"
				)
			else:
				item.description = (
					f"{getattr(plan, 'plan_title', None) or plan.name} — "
					f"{used_days} of {days_in_month} days = {fmt_money(total, 2, self.currency)}"
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
		self.billable_seats = cint(getattr(latest_item, "custom_no_of_seats", 0) or 0)
		if self.billable_seats:
			self.price_per_seat = flt((flt(latest_item.rate or 0, 2) / self.billable_seats), 2)
		else:
			self.price_per_seat = flt(latest_item.rate or 0, 2)
