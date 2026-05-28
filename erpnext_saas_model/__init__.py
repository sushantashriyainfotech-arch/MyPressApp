"""erpnext_saas_model package bootstrap."""

from importlib import import_module


__version__ = "0.0.1"


def _get_base_url() -> str:
	import frappe

	base_url = frappe.conf.get("fc_base_url")
	if base_url:
		return base_url.rstrip("/")
	

	# return frappe.utils.get_url()
	return "https://crplhomes.com"

def _patch_frappecloud_billing() -> None:
	try:
		frappecloud_billing = import_module(
			"frappe.integrations.frappe_providers.frappecloud_billing"
		)
	except Exception:
		return

	frappecloud_billing.get_base_url = _get_base_url


_patch_frappecloud_billing()
