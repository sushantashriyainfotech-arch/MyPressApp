from __future__ import annotations

from frappe.utils import cint, flt

from press.press.doctype.site_plan.plan import Plan as PressSitePlan


class SitePlan(PressSitePlan):
	def is_seat_based(self) -> bool:
		return (getattr(self, "billing_type", None) or "") == "Seat Based"

	def get_price_per_seat(self) -> float:
		return flt(getattr(self, "price_per_seat", 0) or 0, 2)

	def get_seat_pricing_summary(self, seats: int) -> dict[str, float | int | str]:
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

	def validate(self):
		super().validate()
		if self.is_seat_based() and not cint(getattr(self, "min_seats", 0) or 0):
			self.min_seats = 1
