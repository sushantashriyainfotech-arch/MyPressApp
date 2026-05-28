from __future__ import annotations

import frappe
from frappe.rate_limiter import rate_limit

from press.api.client import dashboard_whitelist
from press.guards import feature_preview, team_guard
from press.press.doctype.team.team import Team as PressTeam

from erpnext_saas_model.seat_billing import validate_team_member_seat_limit


class Team(PressTeam):
	"""
	Extended Team controller to enforce seat limits before members are added.
	"""

	def _validate_member_capacity(self):
		validate_team_member_seat_limit(self.name)

	@dashboard_whitelist()
	@feature_preview.beta_testing()
	@team_guard.only_admin()
	def send_invitation(self, names: str):
		# Keep the original behavior, but reject invites when the seat cap is already full.
		self._validate_member_capacity()
		return super().send_invitation(names)

	@dashboard_whitelist()
	@rate_limit(limit=10, seconds=60 * 60)
	def invite_team_member(self, email, roles=None):
		# Block earlier than the downstream account request flow.
		self._validate_member_capacity()
		return super().invite_team_member(email, roles=roles)

	def create_user_for_member(
		self,
		first_name=None,
		last_name=None,
		email=None,
		password=None,
		press_roles=None,
		skip_validations=False,
	):
		# Direct member creation should obey the same seat cap.
		self._validate_member_capacity()
		return super().create_user_for_member(
			first_name=first_name,
			last_name=last_name,
			email=email,
			password=password,
			press_roles=press_roles,
			skip_validations=skip_validations,
		)
