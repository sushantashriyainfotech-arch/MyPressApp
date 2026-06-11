from urllib.parse import urlparse

import frappe
from frappe.utils import get_url


DEFAULT_APP_NAME = "App"


def _get_website_settings():
	try:
		return frappe.get_cached_doc("Website Settings")
	except Exception:
		return None


def get_saas_brand_name(app_name=None):
	settings = _get_website_settings()
	if settings and settings.app_name:
		return settings.app_name.strip()

	if app_name:
		return str(app_name).strip()

	if getattr(frappe.local, "site", None):
		return frappe.local.site

	return DEFAULT_APP_NAME


def get_saas_team_name(app_name=None):
	return f"Team {get_saas_brand_name(app_name)}"


def brand_saas_text(text):
	if text is None:
		return text

	brand_name = get_saas_brand_name()
	return str(text).replace("Frappe Cloud", brand_name)


def get_saas_brand_logo(logo=None):
	settings = _get_website_settings()
	settings_logo = (settings.app_logo if settings else "") or ""
	logo = settings_logo.strip() or (logo or "").strip()

	if not logo:
		return ""

	parsed = urlparse(logo)
	if parsed.scheme and parsed.scheme not in ("http", "https"):
		return ""

	if logo.startswith(("http://", "https://")):
		return logo

	if not logo.startswith("/"):
		logo = f"/{logo}"

	return get_url(logo)


def get_saas_url(path=None):
	path = (path or "").strip()

	if path.startswith(("http://", "https://")):
		return path

	if path and not path.startswith("/"):
		path = f"/{path}"

	return get_url(path or None)


def apply_saas_email_subject(email):
	subject = brand_saas_text(email.subject)
	if subject == email.subject:
		return

	email.subject = subject
	email.set_header("Subject", subject)
