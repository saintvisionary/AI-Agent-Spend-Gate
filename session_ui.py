# session_ui.py
# The terminal look and the sign-in for the interactive session.
#
# Where it sits: in front of everything. It decides WHO is using the agent
# (name + department) before any request runs. The agent and the LLM never
# get to change that answer.
#
# This is a demo sign-in: any valid name works and there's no password.
# In production, the name and department would come from SSO (for example
# IAM Identity Center), not from typed text.
import os
import re
import sys

import ledger

# Colors only work in a real terminal. When output goes to a file or a pipe,
# the color codes would show up as junk, so they're switched off.
USE_COLOR = sys.stdout.isatty()
if USE_COLOR and os.name == "nt":
    os.system("")  # turns on color support in the Windows console

COLORS = {"green": "32", "red": "31", "yellow": "33", "cyan": "36", "bold": "1", "dim": "2"}

# Which color each decision gets.
DECISION_COLORS = {
    "APPROVED": "green", "PROCEED": "green",
    "BLOCKED": "red", "DENY": "red",
    "NEEDS APPROVAL": "yellow", "GUIDE": "yellow", "CONFIRM": "yellow",
}

# A valid name: starts with a letter, then letters, spaces, - ' or . (40 max).
# Blocks CSV injection (a name like "=HYPERLINK(...)" becomes a formula when
# the audit log opens in Excel) and emails, which must never reach the log.
NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z .'-]{0,39}")

LOGO = r"""
   +--------------------------------------------------------------+
   |    ___                                                       |
   |   / $ \     A I   A G E N T   S P E N D   G A T E            |
   |  | $$$ |                                                     |
   |   \ $ /     The agent proposes. Decider 2B checks.           |
   |    '-'      The rules decide.                                |
   |                                                              |
   +--------------------------------------------------------------+
"""


# Wraps text in a color code, or returns it unchanged if colors are off.
def color(text, name):
    if not USE_COLOR:
        return text
    return f"\033[{COLORS[name]}m{text}\033[0m"


# Colors a decision word by what it means: green = go, red = stop, yellow = a person or a retry.
def color_decision(decision):
    return color(decision, DECISION_COLORS.get(decision, "bold"))


def print_banner(llm_name):
    print(color(LOGO, "cyan"))
    print(color(f"   LLM: {llm_name}   Decider 2B: guardrail on every order   Data: all made up", "dim"))
    print()


# Asks for a name until it's valid. Returns the name.
def sign_in():
    print(color("Sign in (demo: any name, no password. In production this is SSO.)", "dim"))
    while True:
        try:
            name = input("Name: ").strip()
        except EOFError:
            return "demo user"
        # fullmatch: the WHOLE name must fit the pattern, not just the start.
        if NAME_PATTERN.fullmatch(name):
            return name
        print("Use letters, spaces, - ' or . only (up to 40 characters), starting with a letter.")


# Shows a numbered list of departments. Accepts the number or the name.
def choose_department():
    names = list(ledger.DEPARTMENT_BUDGETS)
    print("\nDepartment:")
    for number, department in enumerate(names, start=1):
        print(f"  {number}. {department:12} ${ledger.remaining(department):.2f} left")
    while True:
        try:
            answer = input("Pick a number: ").strip().lower()
        except EOFError:
            return names[0]
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        if answer in names:
            return answer
        print(f"Type a number from 1 to {len(names)}.")


# The prompt shows who is signed in, for which department, and the money left.
def prompt(session):
    left = ledger.remaining(session["department"])
    who = color(f"{session['user']}@{session['department']}", "bold")
    return f"\n{who} (${left:.2f} left) > "


def print_whoami(session):
    print(f"Signed in as {session['user']}, ordering for {session['department']}.")
    print(f"Budget left: ${ledger.remaining(session['department']):.2f}")
