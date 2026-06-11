from urllib.parse import urlparse
from email.header import Header
from email.utils import formataddr, parseaddr

import frappe
from frappe.utils import get_url


DEFAULT_APP_NAME = "ASH"


def _get_website_settings():
	try:
		return frappe.get_cached_doc("Website Settings")
	except Exception:
		return None


def get_saas_brand_name(app_name=None):
	settings = _get_website_settings()
	if settings and settings.app_name and settings.app_name.strip().lower() != "frappe":
		return settings.app_name.strip()

	if app_name and str(app_name).strip().lower() != "frappe":
		return str(app_name).strip()

	if not (settings and settings.app_name) and not app_name and getattr(frappe.local, "site", None):
		return frappe.local.site

	return DEFAULT_APP_NAME


def get_saas_team_name(app_name=None):
	return f"Team {get_saas_brand_name(app_name)}"


def brand_saas_text(text):
	if text is None:
		return text

	brand_name = get_saas_brand_name()
	return str(text).replace("Frappe Cloud", brand_name).replace("Frappe", brand_name)


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
	if subject != email.subject:
		email.subject = subject
		email.set_header("Subject", subject)

	_, sender_email = parseaddr(email.sender or "")
	if not sender_email:
		return

	sender = formataddr((str(Header(get_saas_brand_name(), "utf-8")), sender_email))
	email.sender = sender
	email.set_header("From", sender)
