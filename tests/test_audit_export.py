# tests/test_audit_export.py
# Proves the logs are tamper-evident, each role gets the right audit scope,
# and the Terraform export enforces the same hard limits as the app.
#
#     python -m unittest discover tests
import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audit_chain
import audit_export
import ledger
import policy_admin

OWNER = {"user": "Tyler Bynum", "role": "owner", "department": "security"}
LEADER = {"user": "Kim Alvarez", "role": "leader", "department": "marketing"}
MEMBER = {"user": "Guest", "role": "member", "department": "operations"}


class AuditTests(unittest.TestCase):
    # Logs and exports go to a temp folder; the real logs are never touched.
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.real = (ledger.AUDIT_LOG, policy_admin.CHANGE_LOG, audit_export.EXPORTS)
        ledger.AUDIT_LOG = os.path.join(self.folder, "audit_log.csv")
        policy_admin.CHANGE_LOG = os.path.join(self.folder, "policy_changes.csv")
        audit_export.EXPORTS = os.path.join(self.folder, "exports")
        ledger.audit("Kim Alvarez", "marketing", "spend gate", "Paperleaf Co", "printer paper", 5,
                     "office supplies", 90.0, "APPROVED", "within policy")
        ledger.audit("Rick Sullivan", "information technology", "guardrail", "Cobalt Systems", "laptops", 2,
                     "office supplies", "", "DENY", "item looks like 'it hardware' but was labeled 'office supplies'")
        ledger.audit("Kim Alvarez", "marketing", "spend gate", "Quickship Depot", "printer paper", 5,
                     "office supplies", 77.5, "BLOCKED", "vendor 'Quickship Depot' is not approved")

    def tearDown(self):
        ledger.AUDIT_LOG, policy_admin.CHANGE_LOG, audit_export.EXPORTS = self.real

    # ---- tamper evidence ----

    def test_an_untouched_log_verifies(self):
        ok, rows, message, head = audit_chain.verify(ledger.AUDIT_LOG)
        self.assertTrue(ok)
        self.assertEqual(rows, 3)

    def test_an_edited_row_is_caught_at_that_row(self):
        with open(ledger.AUDIT_LOG, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        rows[2][rows[0].index("decision")] = "APPROVED"     # someone flips a DENY to APPROVED
        with open(ledger.AUDIT_LOG, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        ok, checked, message, head = audit_chain.verify(ledger.AUDIT_LOG)
        self.assertFalse(ok)
        self.assertIn("row 2", message)

    def test_a_deleted_row_is_caught(self):
        with open(ledger.AUDIT_LOG, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        del rows[1]                                           # someone removes the first decision
        with open(ledger.AUDIT_LOG, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        self.assertFalse(audit_chain.verify(ledger.AUDIT_LOG)[0])

    # ---- who may export what ----

    def test_members_cannot_export(self):
        self.assertFalse(audit_export.build_audit_pack(MEMBER)[0])
        self.assertFalse(audit_export.export_terraform(MEMBER)[0])

    def test_leaders_cannot_export_terraform(self):
        self.assertFalse(audit_export.export_terraform(LEADER)[0])

    def test_a_leaders_pack_holds_only_their_department(self):
        ok, message, summary = audit_export.build_audit_pack(LEADER)
        self.assertTrue(ok)
        with open(os.path.join(summary["folder"], "decisions.csv"), encoding="utf-8") as f:
            departments = {row["department"] for row in csv.DictReader(f)}
        self.assertEqual(departments, {"marketing"})

    def test_the_owners_pack_holds_everything(self):
        ok, message, summary = audit_export.build_audit_pack(OWNER)
        self.assertEqual(summary["decisions"], 3)
        self.assertEqual(len(summary["exceptions"]), 2)       # the DENY and the BLOCKED

    def test_the_manifest_matches_every_file(self):
        ok, message, summary = audit_export.build_audit_pack(OWNER)
        with open(os.path.join(summary["folder"], "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        for name, digest in manifest["files_sha256"].items():
            self.assertEqual(audit_export.file_sha256(os.path.join(summary["folder"], name)), digest)
        self.assertIn("audit_report.md", manifest["files_sha256"])

    # ---- Terraform ----

    def test_terraform_limits_come_from_the_apps_hard_limits(self):
        ok, message, folder = audit_export.export_terraform(OWNER)
        self.assertTrue(ok)
        with open(os.path.join(folder, "variables.tf"), encoding="utf-8") as f:
            variables = f.read()
        self.assertIn(f"var.approval_over <= {policy_admin.MAX_APPROVAL_OVER}", variables)
        self.assertIn(f"b <= {policy_admin.MAX_BUDGET}", variables)
        for word in policy_admin.NEVER_ALLOWED_WORDS:
            self.assertIn(word, variables)

    def test_terraform_leaves_people_out(self):
        ok, message, folder = audit_export.export_terraform(OWNER)
        with open(os.path.join(folder, "terraform.tfvars.json"), encoding="utf-8") as f:
            values = json.load(f)
        self.assertNotIn("roster", values)
        self.assertNotIn("Tyler Bynum", json.dumps(values))


if __name__ == "__main__":
    unittest.main()
