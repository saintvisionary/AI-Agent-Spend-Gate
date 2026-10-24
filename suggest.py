# suggest.py
# Learns from the memory of human decisions and suggests standing approvals.
#
# The control: separation of duties. This file only READS the decision history
# and PRINTS suggestions. It never changes policy.json. A human decides, using
# the Policy screen, and that change is audited like any other.
#
# The memory is untrusted, so a suggestion needs evidence an attacker can't fake
# by submitting orders, or by taking over one approver's account:
#   1. at least 5 human approvals for the same department, vendor and category
#   2. from at least 2 different people (one person can't train it)
#   3. spread over at least 14 days (a burst in one day doesn't count)
#   4. no human rejections for the same thing (the humans must agree)
# It also flags orders split to stay under the approval limit.
#
#     python suggest.py                                   (the app's own log)
#     python suggest.py sample_logs/human_decisions.csv   (fake sample memory)
#
# Standard library only.
import csv
import json
import sys
from datetime import datetime

DEFAULT_LOG = "logs/audit_log.csv"
POLICY_FILE = "policy.json"

HUMAN_YES = "approved by a human"
HUMAN_NO = "rejected by the human approver"
RULE_YES = "within policy"

MIN_APPROVALS = 5
MIN_PEOPLE = 2
MIN_DAYS = 14
MIN_SPLIT_ORDERS = 3


# Reads the decision history. The only function that knows where memory
# lives, so a CSV can become a database without touching the logic below.
def load_decisions(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"No decision history at {path}. Use the app, or pass a CSV made from the template.")
        return []


# Reads the approval limit, so the split-order check matches the real policy.
def approval_limit():
    try:
        with open(POLICY_FILE, encoding="utf-8") as f:
            return float(json.load(f)["approval_over"])
    except (FileNotFoundError, KeyError, ValueError):
        print(f"Couldn't read approval_over from {POLICY_FILE}, using $500.")
        return 500.0


# Turns an amount from the log into a number. Bad values (empty, "nan") give None.
def to_amount(text):
    try:
        amount = float(text)
    except ValueError:
        return None
    if amount != amount or amount <= 0:        # NaN is the only value not equal to itself
        return None
    return amount


# Groups human decisions by (department, vendor, category).
# Each group keeps its approvals and counts its rejections.
def group_human_decisions(rows):
    groups = {}
    for row in rows:
        if row["reason"] != HUMAN_YES and row["reason"] != HUMAN_NO:
            continue                           # a rule decided this one, not a person
        key = (row["department"], row["vendor"], row["category"])
        if key not in groups:
            groups[key] = {"approvals": [], "rejections": 0}
        if row["reason"] == HUMAN_YES:
            groups[key]["approvals"].append(row)
        else:
            groups[key]["rejections"] += 1
    return groups


# Days between the earliest and latest approval in a group.
# Finds both by looking at every row, so an imported CSV in any order works.
def days_covered(approvals):
    earliest = None
    latest = None
    for row in approvals:
        when = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S")
        if earliest is None or when < earliest:
            earliest = when
        if latest is None or when > latest:
            latest = when
    return (latest - earliest).days


# Applies the 4 safety rules. Returns (True, "") or (False, why it's held).
def check_evidence(group):
    approvals = group["approvals"]
    if group["rejections"] > 0:
        return False, f"humans disagree ({len(approvals)} approved, {group['rejections']} rejected)"
    if len(approvals) < MIN_APPROVALS:
        return False, f"only {len(approvals)} approvals, needs {MIN_APPROVALS}"
    people = []
    for row in approvals:
        if row["user"] not in people:
            people.append(row["user"])
    if len(people) < MIN_PEOPLE:
        return False, f"only 1 approver ({people[0]}), needs {MIN_PEOPLE} different people"
    days = days_covered(approvals)
    if days < MIN_DAYS:
        return False, f"all within {days} days, needs {MIN_DAYS}"
    return True, ""


# The largest amount humans approved: the cap a standing approval would get.
def largest_amount(approvals):
    largest = 0.0
    for row in approvals:
        amount = to_amount(row["amount"])
        if amount is not None and amount > largest:
            largest = amount
    return largest


# Flags rule-approved orders that look split to stay under the approval limit:
# the same department, vendor and item, on the same day, adding up past the limit.
def find_split_orders(rows, limit):
    days = {}
    for row in rows:
        amount = to_amount(row["amount"])
        if row["reason"] != RULE_YES or amount is None:
            continue
        key = (row["department"], row["vendor"], row["item"], row["time"][:10])
        if key not in days:
            days[key] = []
        days[key].append(amount)
    flags = []
    for key, amounts in days.items():
        if len(amounts) >= MIN_SPLIT_ORDERS and sum(amounts) > limit:
            flags.append((key, amounts))
    return flags


# Prints the report. Suggestions are text for a human; nothing is applied.
def print_report(groups, flags, limit):
    print("\nSuggestions (a human decides; nothing here changes the policy)\n")
    if not groups and not flags:
        print("Nothing to suggest yet: no human approvals or split orders in this history.")
    for key, group in groups.items():
        department, vendor, category = key
        ok, why = check_evidence(group)
        if ok:
            cap = largest_amount(group["approvals"])
            print(f"SUGGEST  {department} · {vendor} · {category}: standing approval up to ${cap:,.2f}")
            print(f"         evidence: {len(group['approvals'])} human approvals over {days_covered(group['approvals'])} days")
        else:
            print(f"HOLD     {department} · {vendor} · {category}: {why}")
    for key, amounts in flags:
        department, vendor, item, day = key
        print(f"FLAG     {department} · {vendor} · {item}: {len(amounts)} orders on {day}, "
              f"${sum(amounts):,.2f} in total, each under the ${limit:,.0f} approval limit")


def main():
    path = DEFAULT_LOG
    if len(sys.argv) > 1:
        path = sys.argv[1]
    rows = load_decisions(path)
    if not rows:
        print("No decisions to learn from yet.")
        return
    limit = approval_limit()
    print_report(group_human_decisions(rows), find_split_orders(rows, limit), limit)


if __name__ == "__main__":
    main()
