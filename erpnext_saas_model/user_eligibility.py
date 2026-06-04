from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime


def _log_user_eligibility(event_type: str, payload: dict, decision: dict | None = None, status: str = "info"):
	entry = {
		"event_type": event_type,
		"payload": payload,
		"decision": decision,
		"status": status,
		"timestamp": now_datetime(),
	}
	message = json.dumps(entry, default=str, sort_keys=True)
	logger = frappe.logger("erpnext_saas_model.user_eligibility")
	logger.info(message)
