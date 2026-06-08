from __future__ import annotations

import frappe
from frappe.utils import cint, flt, fmt_money

from press.press.doctype.invoice.invoice import Invoice as PressInvoice

from erpnext_saas_model.seat_billing import get_seat_usage_record_remark, is_seat_based_plan


class Invoice(PressInvoice):
	def _is_seat_usage_record(self, usage_record) -> bool:
		if not usage_record.plan:
			return False

		plan = frappe.get_cached_doc(usage_record.plan_type, usage_record.plan)
		return is_seat_based_plan(plan)

	def _get_seat_usage_description(self, usage_record) -> str:
		return get_seat_usage_record_remark(
			subscription=getattr(usage_record, "subscription", None),
			snapshot_taken_at=getattr(usage_record, "snapshot_taken_at", None),
			fallback_billable_seats=getattr(usage_record, "billable_seats", None),
		)

	def _get_seat_usage_pricing(self, usage_record) -> tuple[int, float]:
		"""
		Returns the invoice seat count and per-day rate.
		"""
		billable_seats = cint(getattr(self, "billable_seats", 0) or getattr(usage_record, "billable_seats", 0) or 1)
		monthly_seat_total = flt(getattr(usage_record, "seat_amount", 0) or getattr(usage_record, "amount", 0), 2)
		price_per_seat = flt(monthly_seat_total / billable_seats, 2) if billable_seats else monthly_seat_total
		usage_record_date = frappe.utils.getdate(usage_record.date)
		days_in_month = frappe.utils.get_last_day(usage_record_date).day or 30
		daily_rate = flt((price_per_seat * billable_seats) / days_in_month, 2)
		return billable_seats, daily_rate

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

		billable_seats, daily_rate = self._get_seat_usage_pricing(usage_record)

		invoice_item = self.get_invoice_item_for_usage_record(usage_record)
		if not invoice_item:
			invoice_item = self.append(
				"items",
				{
					"document_type": usage_record.document_type,
					"document_name": usage_record.document_name,
					"plan": usage_record.plan,
					"description": self._get_seat_usage_description(usage_record),
					"quantity": 0,
					"rate": daily_rate,
					"site": usage_record.site,
				},
			)
		else:
			invoice_item.rate = daily_rate
			if not getattr(invoice_item, "description", None):
				invoice_item.description = self._get_seat_usage_description(usage_record)
		invoice_item.quantity = flt((invoice_item.quantity or 0) + 1, 2)
		invoice_item.amount = flt((invoice_item.quantity or 0) * daily_rate, 2)
		if billable_seats:
			self.billable_seats = billable_seats

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

		_, daily_rate = self._get_seat_usage_pricing(usage_record)
		for row in self.items:
			conditions = (
				row.document_type == usage_record.document_type
				and row.document_name == usage_record.document_name
				and row.plan == usage_record.plan
				and flt(row.rate or 0, 2) == daily_rate
			)
			if row.document_type == "Marketplace App":
				conditions = conditions and row.site == usage_record.site

			if not conditions:
				continue

			usage_record.db_set("invoice", None)
			remaining = frappe.db.count(
				"Usage Record",
				{
					"invoice": self.name,
					"document_type": usage_record.document_type,
					"document_name": usage_record.document_name,
					"plan": usage_record.plan,
				},
			)
			if not remaining:
				self.remove(row)
				self.save()
			return

	def get_invoice_item_for_usage_record(self, usage_record):
		if self._is_seat_usage_record(usage_record):
			_, daily_rate = self._get_seat_usage_pricing(usage_record)
			for row in self.items:
				conditions = (
					row.document_type == usage_record.document_type
					and row.document_name == usage_record.document_name
					and row.plan == usage_record.plan
					and flt(row.rate or 0, 2) == daily_rate
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
			if item.description:
				continue
			if not item.plan:
				continue
			plan = frappe.get_cached_doc("Site Plan", item.plan)
			if not is_seat_based_plan(plan):
				continue
			how_many_days = f"{cint(item.quantity)} day{'s' if item.quantity > 1 else ''}"
			site_name = (item.document_name or "").split(".archived")[0]
			item.description = f"{site_name} active for {how_many_days} on {getattr(plan, 'plan_title', None) or plan.name} plan"

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
		self.billable_seats = cint(getattr(self, "billable_seats", 0) or 0)
		self.price_per_seat = flt(latest_item.rate or 0, 2)
