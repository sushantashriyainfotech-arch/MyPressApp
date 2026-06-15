from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from erpnext_saas_model.doctype.subscription.subscription import Subscription
from erpnext_saas_model.doctype.subscription import subscription as subscription_module


class TestSubscriptionUsageRecord(FrappeTestCase):
	def test_create_usage_record_defaults_date_to_today(self):
			subscription = SimpleNamespace(plan="PLAN-001", plan_type="Site Plan", name="SUB-001")
			plan = SimpleNamespace(name="PLAN-001")
			result_record = SimpleNamespace(name="UR-001")
			today = "2026-05-26"

			with patch.object(subscription_module.frappe.utils, "today", return_value=today), patch.object(
				subscription_module.frappe.utils, "now_datetime", return_value=datetime(2026, 5, 26, 19, 0, 0)
			), patch.object(subscription_module.frappe, "get_cached_doc", return_value=plan), patch.object(
				subscription_module, "is_seat_based_plan", return_value=True
			), patch.object(
				subscription_module, "create_seat_usage_record", return_value=result_record
			) as create_usage_record:
				result = Subscription.create_usage_record(subscription)

			create_usage_record.assert_called_once_with(subscription, date=getdate(today), force=True)
			self.assertIs(result, result_record)

	def test_create_usage_record_allows_midnight_snapshot(self):
			subscription = SimpleNamespace(plan="PLAN-001", plan_type="Site Plan", name="SUB-001")
			plan = SimpleNamespace(name="PLAN-001")
			result_record = SimpleNamespace(name="UR-001")
			today = "2026-05-26"

			with patch.object(subscription_module.frappe.utils, "today", return_value=today), patch.object(
				subscription_module.frappe.utils, "now_datetime", return_value=datetime(2026, 5, 26, 0, 0, 0)
			), patch.object(subscription_module.frappe, "get_cached_doc", return_value=plan), patch.object(
				subscription_module, "is_seat_based_plan", return_value=True
			), patch.object(
				subscription_module, "create_seat_usage_record", return_value=result_record
			) as create_usage_record:
				result = Subscription.create_usage_record(subscription)

			create_usage_record.assert_called_once_with(subscription, date=getdate(today), force=True)
			self.assertIs(result, result_record)
