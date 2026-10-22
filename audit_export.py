# audit_export.py
# Evidence for internal and external audits, and the policy as Terraform.
#
# Where it sits: the app's "Audit & Export" screen calls this file. Like
# policy_admin.py, it decides WHO may do WHAT, and it never trusts the screen:
#   audit pack        owner: everything · leader: their department only
#   verify logs       anyone (it only reads, and shows nothing private)
#   Terraform export  owner only (it's the whole organization's policy)
#
# Everything is written under exports/, which is in .gitignore: audit packs
# contain names and decisions and should be handed over, not committed.
import csv
import hashlib
import json
import os
import shutil
import time

import audit_chain
import catalog
import ledger
import policy
import policy_admin

EXPORTS = "exports"


# ---------------------------------------------------------------
# WHO MAY EXPORT
# ---------------------------------------------------------------

# Returns (allowed, reason). The reason is shown on a disabled button.
def can_export_audit(session):
    if session.get("role") in ("owner", "leader"):
        return True, ""
    return False, "Audit packs: department leaders and the app owner only (they contain names)."


def can_export_terraform(session):
    if session.get("role") == "owner":
        return True, ""
    return False, "Terraform export: app owner only (it's the whole organization's policy)."


# ---------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------

def file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# A log as a list of dicts (header -> value). [] if there's no log yet.
def read_log(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)


def new_folder(kind):
    folder = os.path.join(EXPORTS, f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(folder, exist_ok=True)
    return folder


# A leader sees their own department's rows; the owner sees every row.
def in_scope(session, department):
    return session.get("role") == "owner" or department == session.get("department")


# ---------------------------------------------------------------
# VERIFY
# ---------------------------------------------------------------

# Checks both hash chains. Returns a list of (log name, ok, rows, message, head).
def verify_logs():
    results = []
    for name, path in [("purchase decisions", ledger.AUDIT_LOG), ("policy changes", policy_admin.CHANGE_LOG)]:
        if not os.path.exists(path):
            results.append((name, True, 0, "no entries yet", audit_chain.GENESIS))
            continue
        ok, rows, message, head = audit_chain.verify(path)
        results.append((name, ok, rows, message, head))
    return results


# ---------------------------------------------------------------
# THE AUDIT PACK
# ---------------------------------------------------------------

# Builds the audit pack. Returns (ok, message, summary). summary has the
# folder and the numbers the screen shows.
def build_audit_pack(session):
    allowed, reason = can_export_audit(session)
    if not allowed:
        return False, reason, None

    folder = new_folder("audit")
    decisions = [row for row in read_log(ledger.AUDIT_LOG) if in_scope(session, row.get("department"))]
    changes = [row for row in read_log(policy_admin.CHANGE_LOG)
               if session.get("role") == "owner" or row.get("target") in ("", session.get("department"))
               or row.get("user") == session.get("user")]

    write_rows(os.path.join(folder, "decisions.csv"), ledger.AUDIT_COLUMNS + ["row_hash"], decisions)
    write_rows(os.path.join(folder, "policy_changes.csv"), policy_admin.CHANGE_COLUMNS + ["row_hash"], changes)
    write_access_review(os.path.join(folder, "access_review.csv"), session)
    write_entitlements(os.path.join(folder, "entitlements.csv"), session)
    shutil.copyfile(policy.POLICY_FILE, os.path.join(folder, "policy.json"))

    summary = summarize(session, decisions, changes, folder)
    with open(os.path.join(folder, "audit_report.md"), "w", encoding="utf-8") as f:
        f.write(report_text(summary))
    write_manifest(folder, summary)
    return True, f"Audit pack saved to {folder}", summary


def write_rows(path, columns, rows):
    table = []
    for row in rows:
        table.append([row.get(column, "") for column in columns])
    write_csv(path, columns, table)


# Who has which role. The owner sees the whole roster; a leader sees their department.
def write_access_review(path, session):
    rows = []
    roster = policy.POLICY["roster"]
    for name in roster:
        entry = roster[name]
        department = entry.get("department", "(all departments)")
        if session.get("role") == "owner" or entry.get("department") == session.get("department"):
            rows.append([name, entry.get("role", "member"), department])
    write_csv(path, ["name", "role", "department"], rows)


# Which department may buy which item (yes/no per department).
def write_entitlements(path, session):
    departments = catalog.DEPARTMENTS
    if session.get("role") != "owner":
        departments = [session.get("department")]
    rows = []
    for item in catalog.INVENTORY:
        row = [item, catalog.INVENTORY[item]["category"]]
        for department in departments:
            row.append("yes" if catalog.department_uses(department, item) else "no")
        rows.append(row)
    write_csv(path, ["item", "category"] + departments, rows)


# The numbers for the report and the screen.
def summarize(session, decisions, changes, folder):
    by_control = {}
    exceptions = []
    for row in decisions:
        key = f"{row.get('source')}: {row.get('decision')}"
        by_control[key] = by_control.get(key, 0) + 1
        reason = row.get("reason", "")
        # Exceptions: anything that wasn't a clean approval. Auditors sample these first.
        if "human" in reason or "Cancelled" in reason or row.get("decision") in ("DENY", "CONFIRM", "GUIDE", "BLOCKED"):
            exceptions.append(row)
    times = [row.get("time", "") for row in decisions + changes if row.get("time")]
    return {
        "folder": folder,
        "generated_by": session.get("user"),
        "role": session.get("role"),
        "scope": "all departments" if session.get("role") == "owner" else session.get("department"),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "period": (min(times), max(times)) if times else ("no entries", "no entries"),
        "decisions": len(decisions),
        "policy_changes": changes,
        "by_control": by_control,
        "exceptions": exceptions,
        "policy_sha256": file_sha256(policy.POLICY_FILE),
        "verification": verify_logs(),
    }


def report_text(summary):
    lines = [
        "# Audit report: AI Agent Spend Gate",
        "",
        f"- **Generated by:** {summary['generated_by']} ({summary['role']}) on {summary['generated_at']}",
        f"- **Scope:** {summary['scope']}",
        f"- **Period covered:** {summary['period'][0]} to {summary['period'][1]}",
        f"- **Policy in force:** `policy.json`, SHA-256 `{summary['policy_sha256']}`",
        "",
        "## Control results",
        "",
        "| Control: decision | Count |",
        "|:---|---:|",
    ]
    for key in sorted(summary["by_control"]):
        lines.append(f"| {key} | {summary['by_control'][key]} |")
    if not summary["by_control"]:
        lines.append("| (no decisions in scope) | 0 |")
    lines += ["", f"## Exceptions ({len(summary['exceptions'])})", "",
              "Denials, blocks, guided retries, human decisions and cancellations: the cases an auditor samples first.", "",
              "| Time | User | Department | Control | Decision | Reason |", "|:---|:---|:---|:---|:---|:---|"]
    for row in summary["exceptions"]:
        lines.append(f"| {row.get('time')} | {row.get('user')} | {row.get('department')} | "
                     f"{row.get('source')} | {row.get('decision')} | {row.get('reason')} |")
    lines += ["", f"## Policy changes ({len(summary['policy_changes'])})", "",
              "| Time | User | Role | Setting | Target | Old | New |", "|:---|:---|:---|:---|:---|:---|:---|"]
    for row in summary["policy_changes"]:
        lines.append(f"| {row.get('time')} | {row.get('user')} | {row.get('role')} | {row.get('setting')} | "
                     f"{row.get('target')} | {row.get('old')} | {row.get('new')} |")
    lines += ["", "## Log integrity", "",
              "Each log row is hash-chained to the row before it. A changed, deleted or reordered row breaks the chain.", "",
              "| Log | Result | Rows | Latest hash (head) |", "|:---|:---|---:|:---|"]
    for name, ok, rows, message, head in summary["verification"]:
        lines.append(f"| {name} | {'OK' if ok else 'BROKEN'}: {message} | {rows} | `{head}` |")
    lines += ["", "Keep this report's head hashes. A later pack must agree with every row up to these heads;",
              "if it doesn't, the log was rewritten in between.", "",
              "## Files in this pack", "",
              "| File | Contents |", "|:---|:---|",
              "| `decisions.csv` | Every purchase decision in scope, from every control |",
              "| `policy_changes.csv` | Every policy change in scope: who, role, old value, new value |",
              "| `access_review.csv` | Who holds which role |",
              "| `entitlements.csv` | Which department may buy which item |",
              "| `policy.json` | The exact policy in force |",
              "| `manifest.json` | SHA-256 of every file in this pack |", ""]
    return "\n".join(lines)


# SHA-256 of every file, so the pack can't be edited after it's handed over.
def write_manifest(folder, summary):
    files = {}
    for name in sorted(os.listdir(folder)):
        files[name] = file_sha256(os.path.join(folder, name))
    manifest = {
        "generated_by": summary["generated_by"],
        "role": summary["role"],
        "scope": summary["scope"],
        "generated_at": summary["generated_at"],
        "files_sha256": files,
        "log_heads": {name: head for name, ok, rows, message, head in summary["verification"]},
    }
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


# ---------------------------------------------------------------
# POLICY AS TERRAFORM
# ---------------------------------------------------------------

# Writes a Terraform folder for the current policy. Returns (ok, message, folder).
def export_terraform(session):
    allowed, reason = can_export_terraform(session)
    if not allowed:
        return False, reason, None
    folder = new_folder("terraform")
    data = policy.POLICY
    tfvars = {
        "allowed_categories": data["allowed_categories"],
        "approved_vendors": data["approved_vendors"],
        "approval_over": data["approval_over"],
        "department_budgets": data["department_budgets"],
        "reorder": data["reorder"],
        "policy_bucket_name": "spend-gate-policy-CHANGE-ME",
    }
    with open(os.path.join(folder, "terraform.tfvars.json"), "w", encoding="utf-8") as f:
        json.dump(tfvars, f, indent=2)
    with open(os.path.join(folder, "variables.tf"), "w", encoding="utf-8") as f:
        f.write(variables_tf())
    with open(os.path.join(folder, "main.tf"), "w", encoding="utf-8") as f:
        f.write(MAIN_TF)
    with open(os.path.join(folder, "README.md"), "w", encoding="utf-8") as f:
        f.write(TERRAFORM_README.format(user=session.get("user"), when=time.strftime("%Y-%m-%d %H:%M:%S")))
    return True, f"Terraform saved to {folder}", folder


# The validation rules come from the SAME hard limits policy_admin.py uses,
# so a bad policy fails at "terraform plan", and the two can't drift apart.
def variables_tf():
    cash_like = "|".join(policy_admin.NEVER_ALLOWED_WORDS)
    return f'''# Generated by AI Agent Spend Gate. The validation blocks are generated from
# the hard limits in policy_admin.py, so the app and Terraform enforce the same rules.

variable "region" {{
  description = "AWS region for the policy bucket."
  type        = string
  default     = "us-east-1"
}}

variable "policy_bucket_name" {{
  description = "Name of the S3 bucket that holds policy.json. Must be globally unique."
  type        = string
}}

variable "approval_over" {{
  description = "Orders over this amount (USD) need a human approver."
  type        = number
  validation {{
    condition     = var.approval_over >= 1 && var.approval_over <= {policy_admin.MAX_APPROVAL_OVER}
    error_message = "approval_over must be between 1 and {policy_admin.MAX_APPROVAL_OVER} (a hard limit)."
  }}
}}

variable "allowed_categories" {{
  description = "Purchase categories that may be bought."
  type        = list(string)
  validation {{
    condition     = alltrue([for c in var.allowed_categories : length(regexall("{cash_like}", lower(c))) == 0])
    error_message = "Cash-like categories (gift, prepaid, cash, crypto, wire, money order) can never be allowed."
  }}
}}

variable "approved_vendors" {{
  description = "Vendors the Spend Gate allows."
  type        = list(string)
}}

variable "department_budgets" {{
  description = "Budget per department (USD)."
  type        = map(number)
  validation {{
    condition     = alltrue([for b in values(var.department_budgets) : b >= 0 && b <= {policy_admin.MAX_BUDGET}])
    error_message = "Each department budget must be between 0 and {policy_admin.MAX_BUDGET} (a hard limit)."
  }}
}}

variable "reorder" {{
  description = "Reorder point and order quantity per item."
  type = map(object({{
    reorder_at = number
    order_qty  = number
  }}))
  validation {{
    condition     = alltrue([for r in values(var.reorder) : r.reorder_at >= 0 && r.order_qty >= 1 && r.order_qty <= {policy_admin.MAX_REORDER}])
    error_message = "Reorder quantities must be between 1 and {policy_admin.MAX_REORDER}."
  }}
}}
'''


MAIN_TF = '''# Generated by AI Agent Spend Gate: the purchasing policy as code.
# Matches the reference architecture: the Spend Gate loads its policy from S3.
#
# Not included on purpose: the roster of people and roles. Identities belong
# in the identity provider (for example IAM Identity Center groups), not here.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  policy = {
    allowed_categories = var.allowed_categories
    approved_vendors   = var.approved_vendors
    approval_over      = var.approval_over
    department_budgets = var.department_budgets
    reorder            = var.reorder
  }
}

resource "aws_s3_bucket" "policy" {
  bucket = var.policy_bucket_name
}

# Every policy version is kept: the bucket's history is part of the audit trail.
resource "aws_s3_bucket_versioning" "policy" {
  bucket = aws_s3_bucket.policy.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "policy" {
  bucket = aws_s3_bucket.policy.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "policy" {
  bucket                  = aws_s3_bucket.policy.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "policy" {
  bucket       = aws_s3_bucket.policy.id
  key          = "spend-gate/policy.json"
  content      = jsonencode(local.policy)
  content_type = "application/json"
}

# Least privilege: the Spend Gate may READ the policy, and nothing else.
# Changing the policy goes through this Terraform (and its code review), not the app.
data "aws_iam_policy_document" "gate_reads_policy" {
  statement {
    sid       = "ReadPurchasingPolicy"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.policy.arn}/spend-gate/policy.json"]
  }
}

resource "aws_iam_policy" "gate_reads_policy" {
  name        = "spend-gate-read-policy"
  description = "Lets the Spend Gate read its purchasing policy, and nothing else."
  policy      = data.aws_iam_policy_document.gate_reads_policy.json
}

output "policy_object_version" {
  description = "S3 version of the deployed policy. Record it with each audit pack."
  value       = aws_s3_object.policy.version_id
}
'''

TERRAFORM_README = '''# Spend Gate policy as Terraform

Exported by {user} on {when}.

| File | Contents |
|:---|:---|
| `terraform.tfvars.json` | The policy values at export time |
| `variables.tf` | Typed variables, with validation from the app's hard limits |
| `main.tf` | A versioned, encrypted, private S3 bucket holding `policy.json`, and a read-only IAM policy for the Spend Gate |

```
terraform init
terraform plan      # review: a bad value fails validation here, before AWS
terraform apply
```

Set `policy_bucket_name` in `terraform.tfvars.json` first (bucket names are global).
Applying creates real AWS resources in your account.
'''
