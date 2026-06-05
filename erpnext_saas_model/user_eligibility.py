from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime


def _log_user_eligibility(event_type, payload, decision=None, status="info"):
    payload = payload or {}

    entry = {
        "event_type": event_type,
        "payload": payload,
        "decision": decision,
        "timestamp": now_datetime(),
    }

    message = json.dumps(entry, default=str, sort_keys=True)

    # proves function is called
    frappe.errprint(f"USER ELIGIBILITY HIT: {message}")

    # writes to site log
    logger = frappe.logger(
        "erpnext_saas_model_user_eligibility",
        allow_site=True,
    )
    logger.setLevel("INFO")

    log_method = {
        "info": logger.info,
        "warning": logger.warning,
        "error": logger.error,
    }.get(status, logger.info)

    log_method(message)
