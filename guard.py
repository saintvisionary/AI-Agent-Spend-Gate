# guard.py
# AI Agent Spend Gate: the policy decision point.
#
# An AI agent asks to make a purchase. This file decides whether the
# purchase is APPROVED, NEEDS APPROVAL (a human must sign off), or BLOCKED,
# and gives a short reason for every decision.
#
# How to run (from the project folder):
#     python guard.py
# Then type a vendor, category and amount. Type 'demo' to run the sample
# requests, or 'quit' to exit.

# math is part of Python's standard library. We use math.isfinite()
# to reject amounts that aren't real numbers, like NaN and infinity.
import math


import policy

# ---------------------------------------------------------------
# POLICY
# The values live in policy.json (loaded by policy.py), so a department
# leader can change them in the app without editing code. The rules below
# read them every time they decide, so a change applies to the next request.
# ---------------------------------------------------------------

# Allowlist: only these categories can be bought. Anything else is blocked.
# (The same list object as in the policy, so changes show up here too.)
ALLOWED_CATEGORIES = policy.POLICY["allowed_categories"]

# Allowlist: only these vendors are approved (real companies used as examples).
APPROVED_VENDORS = policy.POLICY["approved_vendors"]


# Purchases over this amount need a human to approve them.
# A function, not a constant: a number can't be shared like a list can,
# so the rules ask for the current value each time.
def approval_over():
    return policy.POLICY["approval_over"]


# ---------------------------------------------------------------
# DECISION
# ---------------------------------------------------------------

# Control: the single decision point for every purchase.
# Checks run in order. Every check that can BLOCK comes before
# anything that can APPROVE, so a request can't skip a rule.
# Returns two values: the decision and a short reason.
# remaining_budget is optional: the department's money left this period.
# Leave it out (None) to skip the budget rule, like the demo below does.
def check_request(vendor, category, amount, remaining_budget=None):
    # Rule 0a: input validation. The amount must be a number.
    # isinstance() asks "is this value an int or a float?"
    # Without this check, text like "86" would crash the comparisons below.
    # True and False count as ints in Python (True == 1), so they're
    # blocked separately. An LLM sending "amount": true must not be approved.
    if isinstance(amount, bool):
        return "BLOCKED", "amount must be a number"
    if not isinstance(amount, (int, float)):
        return "BLOCKED", "amount must be a number"

    # Rule 0b: input validation. The amount must be a real, finite number.
    # Python treats NaN ("not a number") and infinity as floats. NaN is
    # dangerous: every comparison with it is False, so without this check
    # it slips past both "<= 0" and "> 500" and gets APPROVED.
    if not math.isfinite(amount):
        return "BLOCKED", "amount must be a real number"

    # Rule 0c: input validation. A purchase must be for more than $0.
    if amount <= 0:
        return "BLOCKED", "amount must be more than $0"

    # Rule 0d: input validation. Money has at most 2 decimal places.
    # round(amount, 2) keeps 2 decimals, so 0.001 becomes 0.0 and doesn't match.
    if round(amount, 2) != amount:
        return "BLOCKED", "amount can't have fractions of a cent"

    # Rule 1: category must be on the allowlist.
    if category not in ALLOWED_CATEGORIES:
        return "BLOCKED", f"category '{category}' is not allowed"

    # Rule 2: vendor must be on the allowlist.
    # Matching is exact, so "paperleaf co" (lowercase) is blocked. That fails
    # closed: an unexpected value is denied, never allowed.
    if vendor not in APPROVED_VENDORS:
        return "BLOCKED", f"vendor '{vendor}' is not approved"

    # Rule 2b: the department must have the money left.
    # This is a BLOCK, so it runs before Rule 3: a human is never asked
    # to approve spending the department doesn't have.
    if remaining_budget is not None and amount > remaining_budget:
        return "BLOCKED", f"over remaining budget (${remaining_budget:.2f} left)"

    # Rule 3: large purchases go to a human (four-eyes approval).
    if amount > approval_over():
        return "NEEDS APPROVAL", f"over ${approval_over()}, a human must approve"

    # Rule 4: every check passed.
    return "APPROVED", "within policy"


# ---------------------------------------------------------------
# INPUT
# ---------------------------------------------------------------

# Turns typed text into a number. input() always returns text, so "86"
# has to be converted before the guard can compare it.
# This function never makes a decision. If the text can't be converted,
# it's returned unchanged and check_request() blocks it (Rule 0a).
def parse_amount(text):
    # Remove spaces around the text, and one leading $ if there is one.
    # text[1:] means "the text from the second character onward".
    text = text.strip()
    if text.startswith("$"):
        text = text[1:]

    # try/except: attempt the conversion, and if Python raises a
    # ValueError (the text isn't a number), handle it instead of crashing.
    try:
        number = float(text)
    except ValueError:
        return text

    # Show whole numbers without a decimal: 86 instead of 86.0
    if number.is_integer():
        return int(number)
    return number


# ---------------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------------

# Formats an amount as money, putting the minus sign before the $.
# Example: -5 becomes "-$5" instead of "$-5".
# Values that aren't real amounts (text, NaN, infinity) are shown in quotes.
def format_money(amount):
    if isinstance(amount, bool):
        return f"'{amount}'"
    if not isinstance(amount, (int, float)):
        return f"'{amount}'"
    if not math.isfinite(amount):
        return f"'{amount}'"
    if amount < 0:
        return f"-${-amount}"
    return f"${amount}"


# Asks check_request() for a decision, then prints one clear line.
# Deciding and printing are separate jobs, so the same decision can
# later be sent somewhere else (like a log) without touching the rules.
def show_decision(vendor, category, amount):
    decision, reason = check_request(vendor, category, amount)
    print(f"{decision} {vendor} {format_money(amount)}: {reason}")


# ---------------------------------------------------------------
# DEMO
# Sample requests, including what an attacker (or a buggy agent) might try.
# ---------------------------------------------------------------

def run_demo():
    vendor = "Staples"
    show_decision(vendor, "office supplies", 86)              # normal purchase
    show_decision(vendor, "office supplies", 900)             # over $500
    show_decision(vendor, "gift cards", 200)                  # category not allowed
    show_decision("Shady Deals LLC", "office supplies", 50)   # unknown vendor
    show_decision("staples", "office supplies", 50)  # wrong capitalization
    show_decision(vendor, "office supplies", 500)             # exactly the limit
    show_decision(vendor, "office supplies", 500.01)          # one cent over
    show_decision(vendor, "office supplies", 0)               # zero dollars
    show_decision(vendor, "office supplies", -5)              # negative amount
    show_decision(vendor, "office supplies", "86")            # text, not a number
    show_decision(vendor, "office supplies", float("nan"))    # not a number (NaN)
    show_decision(vendor, "office supplies", True)            # True counts as 1 in Python
    show_decision(vendor, "office supplies", 0.001)           # a fraction of a cent


# ---------------------------------------------------------------
# INTERACTIVE MODE
# ---------------------------------------------------------------

# Asks for one request at a time until the user types 'quit'.
# "while True" repeats forever; "break" is the only way out of the loop.
# "continue" skips the rest of this pass and starts the next one.
def run_interactive():
    print("AI Agent Spend Gate")
    print("Enter a purchase request. Type 'demo' for sample requests or 'quit' to exit.")

    while True:
        print()
        vendor = input("Vendor: ").strip()

        if vendor.lower() == "quit":
            break
        if vendor.lower() == "demo":
            run_demo()
            continue

        category = input("Category: ").strip()
        amount = parse_amount(input("Amount: "))
        show_decision(vendor, category, amount)

    print("Goodbye.")


# This block runs only when the file is started directly (python guard.py).
# If another file imports guard.py to reuse check_request(), it doesn't run.
# Ctrl+C (KeyboardInterrupt) or the end of input (EOFError) exits cleanly
# instead of showing an error.
if __name__ == "__main__":
    try:
        run_interactive()
    except (KeyboardInterrupt, EOFError):
        print()
        print("Goodbye.")
