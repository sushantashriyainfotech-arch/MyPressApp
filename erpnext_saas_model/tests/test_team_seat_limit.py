from __future__ import annotations

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from erpnext_saas_model.doctype.team.team import Team


class TestTeamSeatLimit(FrappeTestCase):
	def test_invite_team_member_checks_capacity_before_inviting(self):
		team = Team.__new__(Team)
		team.name = "TEAM-001"

		with patch(
			"erpnext_saas_model.doctype.team.team.validate_team_member_seat_limit"
		) as validate:
			with patch("press.press.doctype.team.team.Team.invite_team_member", return_value="ok") as base:
				result = Team.invite_team_member(team, "user@example.com", roles=["Press User"])

		validate.assert_called_once_with("TEAM-001")
		base.assert_called_once_with(team, "user@example.com", roles=["Press User"])
		self.assertEqual(result, "ok")

	def test_create_user_for_member_checks_capacity_before_creating(self):
		team = Team.__new__(Team)
		team.name = "TEAM-001"

		with patch(
			"erpnext_saas_model.doctype.team.team.validate_team_member_seat_limit"
		) as validate, patch("press.press.doctype.team.team.Team.create_user_for_member", return_value="created") as base:
			result = Team.create_user_for_member(team, email="user@example.com")

		validate.assert_called_once_with("TEAM-001")
		base.assert_called_once_with(team, email="user@example.com")
		self.assertEqual(result, "created")
