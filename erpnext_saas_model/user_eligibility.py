from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime


def _log_user_eligibility(event_type: str, payload: dict, decision: dict | None = None, status: str = "warning"):
	entry = {
		"event_type": event_type,
		"payload": payload,
		"decision": decision,
		"timestamp": now_datetime(),
	}
	message = json.dumps(entry, default=str, sort_keys=True)
	title = f"erpnext_saas_model.user_eligibility:{event_type}"
	if status == "error":
		title = f"{title}:error"
	elif status == "warning":
		title = f"{title}:warning"
	else:
		title = f"{title}:info"

	frappe.log_error(message, title)
