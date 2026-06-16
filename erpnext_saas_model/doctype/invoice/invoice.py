from __future__ import annotations

import frappe
from frappe.utils import cint, flt, fmt_money

from press.press.doctype.invoice.invoice import Invoice as PressInvoice

from erpnext_saas_model.seat_billing import (
	get_plan_price_for_currency,
	get_seat_usage_record_remark,
	get_team_currency,
	is_seat_based_plan,
)


class Invoice(PressInvoice):
	def _is_seat_usage_record(self, usage_record) -> bool:
		if not usage_record.plan:
			return False

		plan = frappe.get_cached_doc(usage_record.plan_type, usage_record.plan)
		return is_seat_based_plan(plan)

	def _is_seat_invoice_item(self, item) -> bool:
		if not getattr(item, "plan", None):
			return False

		plan = frappe.get_cached_doc("Site Plan", item.plan)
		return is_seat_based_plan(plan)

	def _get_seat_usage_description(self, usage_record) -> str:
		if getattr(usage_record, "remark", None):
			return usage_record.remark
		if getattr(usage_record, "seat_change_log", None):
			return get_seat_usage_record_remark(
				seat_change_log=usage_record.seat_change_log,
				team=getattr(usage_record, "team", None),
			)

		return get_seat_usage_record_remark(
			subscription=getattr(usage_record, "subscription", None),
			team=getattr(usage_record, "team", None),
			reference_at=getattr(usage_record, "snapshot_taken_at", None) or getattr(usage_record, "date", None),
			fallback_billable_seats=getattr(usage_record, "billable_seats", None),
		)

	def _get_seat_usage_item_signature(
		self,
		usage_record,
		billable_seats: int,
		description: str,
		daily_rate: float,
	) -> tuple[str | None, str | None, str | None, str | None, int, str, float]:
		site = usage_record.site if getattr(usage_record, "document_type", None) == "Marketplace App" else None
		return (
			getattr(usage_record, "document_type", None),
			getattr(usage_record, "document_name", None),
			getattr(usage_record, "plan", None),
			site,
			cint(billable_seats or 0),
			description or "",
			flt(daily_rate or 0, 2),
		)

	def _seat_usage_item_matches(
		self,
		item,
		usage_record,
		billable_seats: int,
		description: str,
		daily_rate: float,
	) -> bool:
		if not self._is_seat_invoice_item(item):
			return False

		return self._get_seat_usage_item_signature(
			usage_record=usage_record,
			billable_seats=billable_seats,
			description=description,
			daily_rate=daily_rate,
		) == (
			getattr(item, "document_type", None),
			getattr(item, "document_name", None),
			getattr(item, "plan", None),
			getattr(item, "site", None) if getattr(item, "document_type", None) == "Marketplace App" else None,
			cint(getattr(item, "billable_seats", 0) or 0),
			getattr(item, "description", None) or "",
			flt(getattr(item, "rate", 0) or 0, 2),
		)

	def _get_last_seat_usage_invoice_item(self, usage_record, billable_seats: int, description: str, daily_rate: float):
		if not self.items:
			return None

		last_item = self.items[-1]
		if self._seat_usage_item_matches(last_item, usage_record, billable_seats, description, daily_rate):
			return last_item
		return None

	def _find_seat_usage_invoice_item(self, usage_record, billable_seats: int, description: str, daily_rate: float):
		for row in reversed(self.items):
			if self._seat_usage_item_matches(row, usage_record, billable_seats, description, daily_rate):
				return row
		return None

	def _get_seat_usage_pricing(self, usage_record) -> tuple[int, float]:
		"""
		Returns the invoice seat count and per-day rate.
		"""
		billable_seats = cint(getattr(self, "billable_seats", 0) or getattr(usage_record, "billable_seats", 0) or 1)
		daily_rate = flt(getattr(usage_record, "amount", 0) or 0, 2)
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
		description = self._get_seat_usage_description(usage_record)

		invoice_item = self._get_last_seat_usage_invoice_item(usage_record, billable_seats, description, daily_rate)
		if not invoice_item:
			invoice_item = self.append(
				"items",
				{
					"document_type": usage_record.document_type,
					"document_name": usage_record.document_name,
					"plan": usage_record.plan,
					"description": description,
					"usage_record": usage_record.name,
					"seat_change_log": getattr(usage_record, "seat_change_log", None),
					"billable_seats": billable_seats,
					"quantity": 0,
					"rate": daily_rate,
					"site": usage_record.site,
				},
			)
		else:
			if not getattr(invoice_item, "usage_record", None):
				invoice_item.usage_record = usage_record.name
			if not getattr(invoice_item, "seat_change_log", None):
				invoice_item.seat_change_log = getattr(usage_record, "seat_change_log", None)
			if not getattr(invoice_item, "billable_seats", None):
				invoice_item.billable_seats = billable_seats
			invoice_item.rate = daily_rate
			if not getattr(invoice_item, "description", None):
				invoice_item.description = description
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

		billable_seats, daily_rate = self._get_seat_usage_pricing(usage_record)
		description = self._get_seat_usage_description(usage_record)
		row = self._find_seat_usage_invoice_item(usage_record, billable_seats, description, daily_rate)
		if not row:
			return

		usage_record.db_set("invoice", None)
		row.quantity = flt((row.quantity or 0) - 1, 2)
		row.amount = flt((row.quantity or 0) * flt(row.rate or daily_rate, 2), 2)
		if row.quantity <= 0:
			self.remove(row)
		self.save()

	def get_invoice_item_for_usage_record(self, usage_record):
		if self._is_seat_usage_record(usage_record):
			billable_seats, daily_rate = self._get_seat_usage_pricing(usage_record)
			description = self._get_seat_usage_description(usage_record)
			return self._find_seat_usage_invoice_item(usage_record, billable_seats, description, daily_rate)

		if hasattr(PressInvoice, "get_invoice_item_for_usage_record"):
			return PressInvoice.get_invoice_item_for_usage_record(self, usage_record)
		return None

	def validate_items(self):
		if hasattr(PressInvoice, "validate_items"):
			return PressInvoice.validate_items(self)

	def update_item_descriptions(self):
		if hasattr(PressInvoice, "update_item_descriptions"):
			PressInvoice.update_item_descriptions(self)

		for item in self.items:
			if not self._is_seat_invoice_item(item):
				continue

			usage_record_name = getattr(item, "usage_record", None)
			if not usage_record_name:
				continue

			usage_record = frappe.get_cached_doc("Usage Record", usage_record_name)
			seat_description = self._get_seat_usage_description(usage_record)
			if seat_description:
				item.description = seat_description

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
		plan = frappe.get_cached_doc("Site Plan", latest_item.plan)
		team_currency = get_team_currency(self.team)
		self.billable_seats = cint(getattr(self, "billable_seats", 0) or 0)
		self.price_inr = flt(getattr(plan, "price_inr", 0) or 0, 2)
		self.price_usd = flt(getattr(plan, "price_usd", 0) or 0, 2)
		selected_price = get_plan_price_for_currency(plan, team_currency)
		self.total_amount = flt(selected_price * self.billable_seats, 2)
