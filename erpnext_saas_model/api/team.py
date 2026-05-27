from __future__ import annotations

import frappe
from press.utils import get_current_team as _get_current_team


@frappe.whitelist()
def get_current_team():
    team = _get_current_team(get_doc=True)
    return team