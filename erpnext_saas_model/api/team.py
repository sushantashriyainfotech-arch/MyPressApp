from __future__ import annotations

import frappe
from press.utils import get_current_team


@frappe.whitelist()
def get_current_team(team):
    team = get_current_team(True)
    return team