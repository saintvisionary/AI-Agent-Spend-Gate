# tests/test_policy_admin.py
# Proves who can change which setting, that the hard limits hold, and that
# the Spend Gate rules use a change on the very next decision.
#
# Run from the project folder (no LLM or Decider needed):
#     python -m unittest discover tests
import copy
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import guard
import policy
import policy_admin

MEMBER = {"user": "Guest", "role": "member", "department": "operations"}  # not in the roster
OPS_LEADER = {"user": "Ruth Okafor", "role": "leader", "department": "operations"}
OWNER = {"user": "Tyler Bynum", "role": "owner", "department": "security"}


class PolicyAdminTests(unittest.TestCase):
    # Each test works on a copy of the policy in a temp folder, so the real
    # policy.json and logs are never touched.
    def setUp(self):
        self.saved = copy.deepcopy(policy.POLICY)
        self.folder = tempfile.mkdtemp()
        self.real_file, self.real_log = policy.POLICY_FILE, policy_admin.CHANGE_LOG
        policy.POLICY_FILE = os.path.join(self.folder, "policy.json")
        policy_admin.CHANGE_LOG = os.path.join(self.folder, "policy_changes.csv")

    def tearDown(self):
        # Restore IN PLACE, because guard.py and ledger.py hold references.
        for key in self.saved:
            if isinstance(self.saved[key], list):
                policy.POLICY[key][:] = self.saved[key]
            elif isinstance(self.saved[key], dict):
                policy.POLICY[key].clear()
                policy.POLICY[key].update(self.saved[key])
            else:
                policy.POLICY[key] = self.saved[key]
        policy.POLICY_FILE, policy_admin.CHANGE_LOG = self.real_file, self.real_log

    # ---- roles ----

    def test_roster_names_get_their_role(self):
        self.assertEqual(policy_admin.role_of("Ruth Okafor"), ("leader", "operations"))
        self.assertEqual(policy_admin.role_of("  tyler bynum "), ("owner", "security"))

    def test_unknown_names_are_members(self):
        self.assertEqual(policy_admin.role_of("Someone New"), ("member", None))

    # ---- permissions ----

    def test_member_can_change_nothing(self):
        self.assertEqual(policy_admin.settings_for(MEMBER), [])
        ok, message = policy_admin.apply_change(MEMBER, "budget", "operations", "5000")
        self.assertFalse(ok)
        self.assertEqual(policy.POLICY["department_budgets"]["operations"], self.saved["department_budgets"]["operations"])

    def test_leader_can_change_own_budget_only(self):
        self.assertTrue(policy_admin.apply_change(OPS_LEADER, "budget", "operations", "1500")[0])
        self.assertFalse(policy_admin.apply_change(OPS_LEADER, "budget", "marketing", "9000")[0])
        self.assertEqual(policy.POLICY["department_budgets"]["marketing"], self.saved["department_budgets"]["marketing"])

    def test_leader_reorder_rights_follow_entitlements(self):
        # Operations uses printer paper, but not lab gloves (research and development only).
        self.assertTrue(policy_admin.apply_change(OPS_LEADER, "reorder_at", "printer paper", "12")[0])
        self.assertFalse(policy_admin.apply_change(OPS_LEADER, "reorder_at", "lab gloves", "50")[0])

    def test_leader_cannot_change_org_wide_settings(self):
        self.assertFalse(policy_admin.apply_change(OPS_LEADER, "approval_over", None, "5000")[0])
        self.assertFalse(policy_admin.apply_change(OPS_LEADER, "add_vendor", None, "Shady Deals LLC")[0])

    def test_owner_can_change_org_wide_settings(self):
        self.assertTrue(policy_admin.apply_change(OWNER, "add_vendor", None, "Quickship Depot")[0])
        self.assertIn("Quickship Depot", guard.APPROVED_VENDORS)

    # ---- hard limits and validation ----

    def test_cash_like_categories_can_never_be_allowed(self):
        for name in ["gift cards", "prepaid cards", "cash advances", "crypto"]:
            ok, message = policy_admin.apply_change(OWNER, "add_category", None, name)
            self.assertFalse(ok, name)

    def test_hard_limits_hold_even_for_the_owner(self):
        self.assertFalse(policy_admin.apply_change(OWNER, "approval_over", None, "50000")[0])
        self.assertFalse(policy_admin.apply_change(OWNER, "budget", "operations", "999999")[0])

    def test_bad_numbers_are_refused(self):
        for text in ["nan", "inf", "-5", "lots", ""]:
            self.assertFalse(policy_admin.apply_change(OWNER, "budget", "operations", text)[0], text)
        self.assertFalse(policy_admin.apply_change(OWNER, "order_qty", "printer paper", "2.5")[0])

    def test_vendor_names_cannot_start_a_csv_formula(self):
        self.assertFalse(policy_admin.apply_change(OWNER, "add_vendor", None, "=HYPERLINK(\"x\")")[0])

    def test_changes_are_off_if_the_policy_did_not_load(self):
        real = policy.LOAD_WARNING
        policy.LOAD_WARNING = "broken file"
        try:
            self.assertFalse(policy_admin.apply_change(OWNER, "budget", "operations", "100")[0])
        finally:
            policy.LOAD_WARNING = real

    # ---- the rules use the change immediately ----

    def test_rules_use_a_new_approval_limit_on_the_next_decision(self):
        self.assertEqual(guard.check_request("Paperleaf Co", "office supplies", 450)[0], "APPROVED")
        policy_admin.apply_change(OWNER, "approval_over", None, "400")
        self.assertEqual(guard.check_request("Paperleaf Co", "office supplies", 450)[0], "NEEDS APPROVAL")

    def test_every_change_is_audited(self):
        policy_admin.apply_change(OPS_LEADER, "budget", "operations", "1200")
        with open(policy_admin.CHANGE_LOG, encoding="utf-8") as f:
            rows = f.read().splitlines()
        self.assertEqual(rows[0], ",".join(policy_admin.CHANGE_COLUMNS + ["row_hash"]))
        self.assertIn("Ruth Okafor,leader,budget,operations", rows[1])


if __name__ == "__main__":
    unittest.main()
