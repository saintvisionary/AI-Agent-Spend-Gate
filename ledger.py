# ledger.py
# Department budgets, the order history, and the audit log.
#
# Where it sits: the Spend Gate asks the ledger how much a department has
# left before it decides, and every decision is written here afterwards.
# Budgets and spending live in memory for one session. The audit log is a
# CSV file that keeps growing across sessions, so nothing is ever lost.
import csv
import os
import time

# How much each department can spend in this period. Made-up numbers.
DEPARTMENT_BUDGETS = {
    "operations": 1000,
    "marketing": 500,
}

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
# "guardrail" (Decider 2B), "price check", or "spend gate" (the rules).
def audit(user, department, source, vendor, item, quantity, category, amount, decision, reason):
    # Create logs/ the first time, and write the header row once.
    os.makedirs("logs", exist_ok=True)
    set_aside_old_log()
    new_file = not os.path.exists(AUDIT_LOG)
    try:
        with open(AUDIT_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(AUDIT_COLUMNS)
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"), AGENT_ID, user, department, source,
                vendor, item, quantity, category, amount, decision, reason,
            ])
    except OSError as error:
        # Logging must never crash the agent, but a missing log is a problem
        # someone needs to see, so say it loudly.
        print(f"WARNING: could not write the audit log: {error}")


# If the log on disk has different columns (an older version), rename it
# instead of mixing two formats in one file. Old rows are kept, not deleted.
def set_aside_old_log():
    if not os.path.exists(AUDIT_LOG):
        return
    with open(AUDIT_LOG, newline="", encoding="utf-8") as f:
        header = f.readline().strip()
    if header != ",".join(AUDIT_COLUMNS):
        os.replace(AUDIT_LOG, AUDIT_LOG.replace(".csv", f"_old_{int(time.time())}.csv"))
