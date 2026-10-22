# ledger.py
# Department budgets, the order history, and the audit log.
#
# Where it sits: the Spend Gate asks the ledger how much a department has
# left before it decides, and every decision is written here afterwards.
# Budgets and spending live in memory for one session. The audit log is a
# CSV file that keeps growing across sessions, so nothing is ever lost.
import os
import time

import audit_chain
import policy

# How much each department can spend in this period. Made-up numbers in
# policy.json; a department leader can change them in the app.
# (The same dict object as in the policy, so changes show up here too.)
DEPARTMENT_BUDGETS = policy.POLICY["department_budgets"]

# The audit log. logs/ is in .gitignore, so real runs never get committed.
AUDIT_LOG = os.path.join("logs", "audit_log.csv")
AUDIT_COLUMNS = [
    "time", "agent", "user", "department", "source", "vendor", "item",
    "quantity", "category", "amount", "decision", "reason",
]

# Who the agent is in the log. In production this would be its agent ID.
AGENT_ID = "agt_purchasing_01"

# Money spent so far, per department, and every order this session.
spent = {}
for department in DEPARTMENT_BUDGETS:
    spent[department] = 0
orders = []


# Money a department has left. This is the number the budget rule checks.
def remaining(department):
    return round(DEPARTMENT_BUDGETS[department] - spent[department], 2)


# Records an approved order: adds it to the department's spending.
def record_order(user, department, vendor, item, quantity, amount):
    spent[department] = round(spent[department] + amount, 2)
    orders.append({
        "user": user,
        "department": department,
        "vendor": vendor,
        "item": item,
        "quantity": quantity,
        "amount": amount,
    })


# Writes one decision to the audit log. source says which control made it:
# "guardrail" (Decider 2B), "catalog check", or "spend gate" (the rules).
# Each row is hash-chained to the one before it (see audit_chain.py), so an
# edited or deleted row shows up when the log is verified.
def audit(user, department, source, vendor, item, quantity, category, amount, decision, reason):
    values = [time.strftime("%Y-%m-%d %H:%M:%S"), AGENT_ID, user, department, source,
              vendor, item, quantity, category, amount, decision, reason]
    try:
        audit_chain.append_row(AUDIT_LOG, AUDIT_COLUMNS, values)
    except OSError as error:
        # Logging must never crash the agent, but a missing log is a problem
        # someone needs to see, so say it loudly.
        print(f"WARNING: could not write the audit log: {error}")
