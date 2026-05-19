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

	def get_price_per_seat(self) -> float:
		"""Returns the price per seat, formatted to 2 decimal places."""
		return flt(getattr(self, "price_per_seat", 0) or 0, 2)

	def validate(self):
		"""
		Standard validation hook.
		- Ensures parent validation logic (roles, active subs) is executed.
		- Defaults min_seats to 1 for seat-based plans to prevent division errors.
		"""
		super().validate()
		if self.is_seat_based():
			if not cint(getattr(self, "min_seats", 0) or 0):
				self.min_seats = 1

	def get_seat_pricing_summary(self, seats: int) -> dict[str, float | int | str]:
		"""
		Generates a summary of pricing for a specific seat count.
		Used by frontend previews.
		"""
		seats = cint(seats)
		price = self.get_price_per_seat()
		total = flt(price * seats, 2)
		return {
			"plan": self.name,
			"plan_title": getattr(self, "plan_title", None) or self.name,
			"billable_seats": seats,
			"price_per_seat": price,
			"total_amount": total,
		}
