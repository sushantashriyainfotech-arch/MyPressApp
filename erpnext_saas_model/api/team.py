from __future__ import annotations

import frappe


@frappe.whitelist()
def get_current_team_locale(team_name: str | None = None) -> dict[str, str | None]:
	"""Return only the requested team's country and currency."""
	if not team_name:
		return {"country": None, "currency": None}

	team = frappe.get_value("Team", team_name, ["country", "currency"], as_dict=True)
	if not team:
		return {"country": None, "currency": None}

	return {
		"country": team.get("country"),
		"currency": team.get("currency"),
	}
