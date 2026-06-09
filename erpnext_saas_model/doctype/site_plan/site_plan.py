from __future__ import annotations

from frappe.utils import cint, flt

from press.press.doctype.site_plan.site_plan import SitePlan as PressSitePlan


class SitePlan(PressSitePlan):
	"""
	Extended Site Plan controller to support seat-based billing metadata.
	Inherits from the core Press SitePlan to maintain standard infrastructure 
	validation logic.
	"""

	def is_seat_based(self) -> bool:
		"""Checks if the plan is configured for seat-based billing."""
		return (getattr(self, "billing_type", None) or "") == "Seat Based"

	def get_price_for_currency(self, currency: str) -> float:
		"""Returns the seat price for the requested currency."""
		currency = (currency or "USD").upper()
		if currency == "INR":
			return flt(getattr(self, "price_inr", 0) or getattr(self, "price_usd", 0) or 0, 2)
		return flt(getattr(self, "price_usd", 0) or getattr(self, "price_inr", 0) or 0, 2)

	def validate(self):
		"""
		Standard validation hook.
		- Safely calls parent validation logic if it exists (handles core Press overrides comfortably).
		- Defaults min_seats to 1 for seat-based plans to prevent division errors.
		"""
		if hasattr(PressSitePlan, "validate"):
			PressSitePlan.validate(self)

		if self.is_seat_based():
			if not cint(getattr(self, "min_seats", 0) or 0):
				self.min_seats = 1

	def get_seat_pricing_summary(self, seats: int, currency: str = "USD") -> dict[str, float | int | str]:
		"""
		Generates a summary of pricing for a specific seat count.
		Used by frontend previews.
		"""
		seats = cint(seats)
		selected_price = self.get_price_for_currency(currency)
		total = flt(selected_price * seats, 2)
		return {
			"plan": self.name,
			"plan_title": getattr(self, "plan_title", None) or self.name,
			"currency": (currency or "USD").upper(),
			"billable_seats": seats,
			"price_inr": flt(getattr(self, "price_inr", 0) or 0, 2),
			"price_usd": flt(getattr(self, "price_usd", 0) or 0, 2),
			"selected_price": selected_price,
			"total_amount": total,
		}
