# policy_admin.py
# No-code policy changes: who may change which setting, the limits nobody can
# override, and the audit log of every change.
#
# Where it sits: the app's Policy screen (F5) calls this file. It is the ONLY
# code that changes the policy. There is no agent tool for it, so the AI
# agent (or text injected into it) can never widen its own permissions.
#
# Roles come from the roster in policy.json, like groups from SSO would:
#   member   can order and look, but change nothing
#   leader   can change their own department's budget, and reorder settings
#            for the items their department uses
#   owner    can change everything, including vendors, categories and the
#            approval limit
# Any name that isn't in the roster signs in as a member.
import csv
import math
import os
import re
import time

import catalog
import policy

# HARD LIMITS. These are in code, not in policy.json, on purpose: no role
# can change them from the app. Some controls shouldn't be configurable.
MAX_BUDGET = 10000          # per department
MAX_APPROVAL_OVER = 5000    # the human-approval limit can't go above this
MAX_REORDER = 1000          # reorder points and order quantities
# Cash-like purchases can never be allowed: they're the classic fraud cash-out.
NEVER_ALLOWED_WORDS = ["gift", "prepaid", "cash", "crypto", "wire", "money order"]

CHANGE_LOG = os.path.join("logs", "policy_changes.csv")
CHANGE_COLUMNS = ["time", "user", "role", "setting", "target", "old", "new"]

# Vendor names: letters, digits, spaces and & . , ' - (2-60 characters),
# starting with a letter or digit, so a name can't start a CSV formula (=, +, -, @).
VENDOR_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 &.,'-]{1,59}")
CATEGORY_PATTERN = re.compile(r"[a-z][a-z ]{1,39}")

# What each setting is called on screen.
LABELS = {
    "budget": "Budget",
    "approval_over": "Approval limit (orders over this need a human)",
    "reorder_at": "Reorder point",
    "order_qty": "Order quantity",
    "add_vendor": "Add an approved vendor",
    "remove_vendor": "Remove an approved vendor",
    "add_category": "Allow a category",
    "remove_category": "Stop allowing a category",
}


# ---------------------------------------------------------------
# WHO IS THIS?
# ---------------------------------------------------------------

# Looks a name up in the roster (capital letters don't matter).
# Returns (role, department). Unknown names are members with no department.
def role_of(name):
    for roster_name in policy.POLICY["roster"]:
        if roster_name.lower() == name.strip().lower():
            entry = policy.POLICY["roster"][roster_name]
            return entry.get("role", "member"), entry.get("department")
    return "member", None


# The roster's spelling of a name ("tyler bynum" -> "Tyler Bynum"), so the
# audit logs always record one consistent identity. Unknown names stay as typed.
def canonical_name(name):
    for roster_name in policy.POLICY["roster"]:
        if roster_name.lower() == name.strip().lower():
            return roster_name
    return name.strip()


# The permission rule: can this person change this setting?
# target is the department (for budgets) or the item (for reorder settings).
def can_change(session, setting, target=None):
    role = session.get("role", "member")
    if role == "owner":
        return True
    if role == "leader":
        if setting == "budget":
            return target == session.get("department")
        # Reorder settings only for items their department uses.
        if setting in ("reorder_at", "order_qty"):
            return catalog.department_uses(session.get("department"), target)
    return False


# Every setting this person may change, as (setting, target) pairs.
def settings_for(session):
    choices = []
    for department in policy.POLICY["department_budgets"]:
        choices.append(("budget", department))
    choices.append(("approval_over", None))
    for item in policy.POLICY["reorder"]:
        choices.append(("reorder_at", item))
        choices.append(("order_qty", item))
    for setting in ["add_vendor", "remove_vendor", "add_category", "remove_category"]:
        choices.append((setting, None))
    allowed = []
    for setting, target in choices:
        if can_change(session, setting, target):
            allowed.append((setting, target))
    return allowed


def label(setting, target):
    if target:
        return f"{LABELS[setting]}: {target}"
    return LABELS[setting]


# The current value of a setting, as the text shown on screen.
def current_value(setting, target):
    data = policy.POLICY
    if setting == "budget":
        return f"${data['department_budgets'][target]:,.2f}"
    if setting == "approval_over":
        return f"${data['approval_over']:,.2f}"
    if setting in ("reorder_at", "order_qty"):
        return str(data["reorder"][target][setting])
    if setting in ("add_vendor", "remove_vendor"):
        return ", ".join(data["approved_vendors"]) or "(none)"
    return ", ".join(data["allowed_categories"]) or "(none)"


# A new value as it will look on screen: money with $ and cents, counts as-is.
def format_value(setting, value):
    if setting in ("budget", "approval_over"):
        return f"${value:,.2f}"
    return str(value)


# ---------------------------------------------------------------
# CHECKING A CHANGE
# ---------------------------------------------------------------

# Turns typed text into a number, or None if it isn't a usable one.
# Same idea as the amount checks in guard.py: no NaN, no infinity, no negatives.
def parse_number(text, whole=False):
    text = text.strip().replace("$", "").replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if whole:
        if not number.is_integer():
            return None
        return int(number)
    return round(number, 2)


# Checks a change WITHOUT making it. Returns (ok, message, new_value).
# The Policy screen calls this first to show "old -> new" before saving.
def check_change(session, setting, target, text):
    if policy.LOAD_WARNING:
        return False, "The policy file didn't load, so changes are switched off (fail closed).", None
    if not can_change(session, setting, target):
        return False, f"Your role ({session.get('role', 'member')}) can't change this setting.", None
    if setting == "budget":
        return check_number(text, 0, MAX_BUDGET, whole=False)
    if setting == "approval_over":
        return check_number(text, 1, MAX_APPROVAL_OVER, whole=False)
    if setting == "reorder_at":
        return check_number(text, 0, MAX_REORDER, whole=True)
    if setting == "order_qty":
        return check_number(text, 1, MAX_REORDER, whole=True)
    if setting == "add_vendor":
        return check_new_vendor(text.strip())
    if setting == "remove_vendor":
        return check_existing(text.strip(), policy.POLICY["approved_vendors"], "vendor")
    if setting == "add_category":
        return check_new_category(text.strip().lower())
    if setting == "remove_category":
        return check_existing(text.strip().lower(), policy.POLICY["allowed_categories"], "category")
    return False, "Unknown setting.", None


def check_number(text, low, high, whole):
    number = parse_number(text, whole)
    if number is None:
        kind = "a whole number" if whole else "a number"
        return False, f"Type {kind}, like 750.", None
    if number < low or number > high:
        return False, f"It must be between {low:,} and {high:,} (a hard limit nobody can change here).", None
    return True, "ok", number


def check_new_vendor(name):
    if not VENDOR_PATTERN.fullmatch(name):
        return False, "Use 2-60 letters, digits, spaces or & . , ' - and start with a letter or digit.", None
    for vendor in policy.POLICY["approved_vendors"]:
        if vendor.lower() == name.lower():
            return False, f"{vendor} is already approved.", None
    return True, "ok", name


def check_new_category(name):
    if not CATEGORY_PATTERN.fullmatch(name):
        return False, "Use 2-40 lowercase letters and spaces.", None
    for word in NEVER_ALLOWED_WORDS:
        if word in name:
            return False, f"'{name}' looks cash-like. Cash-like categories can never be allowed.", None
    if name in policy.POLICY["allowed_categories"]:
        return False, f"'{name}' is already allowed.", None
    return True, "ok", name


# For removals: the typed name must match one that's on the list.
def check_existing(name, options, kind):
    for option in options:
        if option.lower() == name.lower():
            return True, "ok", option
    return False, f"There's no {kind} called '{name}' on the list.", None


# ---------------------------------------------------------------
# MAKING A CHANGE
# ---------------------------------------------------------------

# Checks the change again (never trust that the screen already did),
# applies it, saves policy.json and writes the audit row.
# Returns (ok, message).
def apply_change(session, setting, target, text):
    ok, message, new_value = check_change(session, setting, target, text)
    if not ok:
        return False, message
    old = current_value(setting, target)
    data = policy.POLICY
    # Edit in place: other files hold references to these lists and dicts.
    if setting == "budget":
        data["department_budgets"][target] = new_value
    elif setting == "approval_over":
        data["approval_over"] = new_value
    elif setting in ("reorder_at", "order_qty"):
        data["reorder"][target][setting] = new_value
    elif setting == "add_vendor":
        data["approved_vendors"].append(new_value)
    elif setting == "remove_vendor":
        data["approved_vendors"].remove(new_value)
    elif setting == "add_category":
        data["allowed_categories"].append(new_value)
    elif setting == "remove_category":
        data["allowed_categories"].remove(new_value)
    new = current_value(setting, target)
    try:
        policy.save()
    except OSError as error:
        return False, f"Changed for this session, but policy.json couldn't be saved: {error}"
    audit(session, setting, target, old, new)
    return True, f"{label(setting, target)}: {old} -> {new}"


# Writes one row per change. Who changed what, from what, to what, and when.
def audit(session, setting, target, old, new):
    os.makedirs("logs", exist_ok=True)
    new_file = not os.path.exists(CHANGE_LOG)
    try:
        with open(CHANGE_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(CHANGE_COLUMNS)
            writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), session.get("user"), session.get("role"),
                             setting, target or "", old, new])
    except OSError as error:
        print(f"WARNING: could not write the policy change log: {error}")
