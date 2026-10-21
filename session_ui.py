# session_ui.py
# Everything the user sees in the interactive session, drawn with Rich.
#
# Where it sits: in front of everything. It signs the user in (name +
# department) before any request runs, and it draws each step after:
# the agent's tool calls, Decider 2B's checks, and the Spend Gate's decisions.
#
# Display rules (borrowed from how good AI terminals show work):
#   - each step is one line starting with ⏺, its result indented under ⎿
#   - color is rare and means something: green = go, red = stop,
#     yellow = a person or a retry, cyan = this app
#   - important results (Decider verdicts) get a frame
#   - who you are and the money left are always on screen at the prompt
#
# Security: LLM output and tool data are UNTRUSTED. Rich treats [square
# brackets] as style commands, so untrusted text is always wrapped in Text()
# or escape()d. Otherwise an agent could restyle or hide parts of the screen.
#
# This is a demo sign-in: any valid name works and there's no password.
# In production, the name and department would come from SSO.
import re
import sys

from rich import box
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

import ledger

# Box characters need UTF-8. Without this, Python on Windows can crash when
# output goes to a file that isn't UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

console = Console(highlight=False)

ACCENT = "cyan"
TITLE = "bold black on cyan"   # section labels: a cyan block, like a tab

LOGO = r"""    ___
   / $ \     A I   A G E N T   S P E N D   G A T E
  | $$$ |
   \ $ /     The agent proposes. Decider 2B checks.
    '-'      The rules decide."""

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

COMMANDS = [
    ("report", "budgets and orders so far"),
    ("whoami", "who is signed in, and the budget left"),
    ("inventory", "what's on the shelf"),
    ("help", "show this menu"),
    ("quit", "exit"),
]


# ---------------------------------------------------------------
# SMALL HELPERS
# ---------------------------------------------------------------

def decision_text(decision):
    return Text(decision, style=f"bold {DECISION_COLORS.get(decision, 'white')}")


def money(amount):
    return f"${amount:,.2f}"


# Green above half the budget left, yellow above a fifth, red below that.
def money_color(left, budget):
    if left > budget * 0.5:
        return "green"
    if left > budget * 0.2:
        return "yellow"
    return "red"


# A bar of how much budget is left, like ██████░░░░ for 60%.
def budget_bar(left, budget, width=12):
    filled = round(width * left / budget) if budget else 0
    return Text("█" * filled + "░" * (width - filled), style=money_color(left, budget))


# A score from 0 to 1 as a short bar, so the numbers are easy to compare.
def score_bar(score, width=10):
    filled = round(score * width)
    return Text("▰" * filled + "▱" * (width - filled), style="dim")


# One step line: "⏺ title  detail". The dot's color shows what kind of step.
def step(title, detail=None, dot="white"):
    line = Text("⏺ ", style=dot)
    line.append(title, style="bold")
    if detail is not None:
        line.append("  ")
        line.append(detail if isinstance(detail, Text) else Text(str(detail)))
    console.print(line)


# The result under a step: "  ⎿  first line", then the rest indented.
def result(text, style="dim"):
    lines = str(text).splitlines() or [""]
    console.print(Text("  ⎿  " + lines[0], style=style))
    for line in lines[1:]:
        console.print(Text("     " + line, style=style))


def warn(message):
    console.print(Text("! ", style="bold yellow") + Text(message))


# ---------------------------------------------------------------
# SIGN-IN SCREENS
# ---------------------------------------------------------------

def print_banner(llm_name):
    body = Group(
        Text(LOGO, style=f"bold {ACCENT}"),
        Text(""),
        Text(f"LLM: {llm_name}  ·  guardrail: Decider 2B on every order  ·  data: all made up", style="dim"),
    )
    console.print(Panel(body, border_style=ACCENT, box=box.ROUNDED, padding=(1, 2), expand=False))


# A section title: a cyan block label, then a thin line.
def section(title):
    console.print()
    console.print(Text(f" {title.upper()} ", style=TITLE) + Text(" " + "─" * 40, style="dim"))


# Asks for a name until it's valid. Returns the name.
def sign_in():
    section("Sign in")
    console.print(Text("Demo: any name, no password. In production this is SSO.", style="dim"))
    while True:
        try:
            name = console.input(f"[{ACCENT}]›[/] Name: ").strip()
        except EOFError:
            return "demo user"
        # fullmatch: the WHOLE name must fit the pattern, not just the start.
        if NAME_PATTERN.fullmatch(name):
            return name
        warn("Use letters, spaces, - ' or . only (up to 40 characters), starting with a letter.")


# Shows a numbered list of departments with budget bars.
# Accepts the number or the name.
def choose_department():
    names = list(ledger.DEPARTMENT_BUDGETS)
    table = Table.grid(padding=(0, 2))
    for number, department in enumerate(names, start=1):
        budget = ledger.DEPARTMENT_BUDGETS[department]
        left = ledger.remaining(department)
        table.add_row(Text(f"[{number}]", style=ACCENT), Text(department, style="bold"),
                      budget_bar(left, budget), Text(f"{money(left)} of {money(budget)}", style="dim"))
    section("Department")
    console.print(table)
    while True:
        try:
            answer = console.input(f"[{ACCENT}]›[/] Pick a number: ").strip().lower()
        except EOFError:
            return names[0]
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        if answer in names:
            return answer
        warn(f"Type a number from 1 to {len(names)}.")


def print_signed_in(session):
    console.print()
    step("Signed in", Text(f"{session['user']} · {session['department']}"), dot="green")


def print_help(scenarios):
    table = Table.grid(padding=(0, 3))
    for command, description in COMMANDS:
        table.add_row(Text(command, style=ACCENT), Text(description, style="dim"))
    example = Text("  Ask in plain English, for example: ", style="dim")
    example.append("we need printer paper by tomorrow", style="italic")
    samples = Text("  Sample scenarios: ", style="dim")
    samples.append("  ".join(scenarios), style=ACCENT)
    console.print()
    console.print(Panel(Group(example, Text(""), table, Text(""), samples),
                        title=f"[{TITLE}] WHAT YOU CAN DO [/]", title_align="left",
                        border_style=ACCENT, box=box.ROUNDED, expand=False))


# ---------------------------------------------------------------
# THE PROMPT
# A status line (who, where, money left) above a short input arrow.
# ---------------------------------------------------------------

def ask_command(session):
    department = session["department"]
    left = ledger.remaining(department)
    budget = ledger.DEPARTMENT_BUDGETS[department]
    status = Text(f"{session['user']} · {department} · ", style="dim")
    status.append(f"{money(left)} left", style=money_color(left, budget))
    console.print()
    console.rule(style="dim")
    console.print(status)
    return console.input(f"[bold {ACCENT}]>[/] ").strip()


# A yes/no question for a human approver. No answer counts as no.
def ask_yes_no(question):
    try:
        answer = console.input(f"[bold yellow]?[/] {escape(question)} [dim](y/n)[/] ")
    except EOFError:
        return False
    return answer.strip().lower() == "y"


# ---------------------------------------------------------------
# A REQUEST, STEP BY STEP
# ---------------------------------------------------------------

def show_request(request):
    console.print()
    console.print(Text("> ", style=f"bold {ACCENT}") + Text(request, style="bold"))
    console.print(Text("  The agent plans, then Decider 2B checks every order before it runs.", style="dim"))


# Strands calls this for every event while the agent runs (a "callback").
# It replaces Strands' default printer, which shows the model's raw stream.
# Text arrives in small pieces, so it's collected until the message is done.
agent_text = []


def on_agent_event(**kwargs):
    if kwargs.get("data"):
        agent_text.append(kwargs["data"])
    tool_use = kwargs.get("event", {}).get("contentBlockStart", {}).get("start", {}).get("toolUse")
    if tool_use:
        flush_agent_text()
        step(tool_use["name"], dot=ACCENT)
    if kwargs.get("complete"):
        flush_agent_text()


def flush_agent_text():
    text = "".join(agent_text).strip()
    agent_text.clear()
    if text:
        console.print()
        console.print(Text("⏺ ", style="white") + Text(text))


# What a read-only tool returned, shown under its step line.
def show_tool_result(text):
    result(text)


def show_price_block(problem):
    step("Price check", Text("BLOCKED", style="bold red") + Text(f"  {problem}"), dot="red")


def show_spend_gate(decision, department, vendor, amount, reason):
    detail = decision_text(decision)
    detail.append(f"  {department} · {vendor} · {money(amount)}", style="white")
    step("Spend Gate", detail, dot=DECISION_COLORS.get(decision, "white"))
    result(reason)


def show_error(error):
    step("The request failed", Text(f"{type(error).__name__}: {error}"), dot="red")


def show_summary(entries):
    if not entries:
        result("No purchases were proposed.")
        return
    table = Table(box=box.SIMPLE, show_edge=False, pad_edge=False)
    table.add_column("Decider 2B", style="bold")
    table.add_column("Order")
    table.add_column("Time", justify="right", style="dim")
    for entry in entries:
        table.add_row(decision_text(entry["verdict"].upper()), describe_order(entry["arguments"]),
                      f"{entry['latency_ms'] / 1000:.0f}s")
    console.print()
    console.print(table)


# "5 x printer paper · Northbeam Office Supply · $17.20 each" from tool arguments.
def describe_order(arguments):
    parts = [f"{arguments.get('quantity', '?')} x {arguments.get('item', '?')}", str(arguments.get("vendor", "?"))]
    if isinstance(arguments.get("unit_price"), (int, float)):
        parts.append(f"{money(arguments['unit_price'])} each")
    return Text(" · ".join(parts))


# ---------------------------------------------------------------
# THE GUARDRAIL'S DISPLAY
# SpendGuardrail(display=session_ui) calls these three functions.
# ---------------------------------------------------------------

def show_check(entry):
    verdict = entry["verdict"].upper()
    color = DECISION_COLORS.get(verdict, "white")
    scores = Table.grid(padding=(0, 2))
    scores.add_row(Text("grounded", style="dim"), score_bar(entry["grounded"]), f"{entry['grounded']:.2f}")
    scores.add_row(Text("injected", style="dim"), score_bar(entry["injected"]), f"{entry['injected']:.2f}")
    scores.add_row(Text("item looks like", style="dim"), score_bar(entry["category_confidence"]),
                   Text(f"{entry['item_category']} ({entry['category_confidence']:.2f})"))
    if entry["user_goal"] != "not checked":
        scores.add_row(Text("user goal", style="dim"), score_bar(entry["goal_confidence"]),
                       Text(f"{entry['user_goal']} ({entry['goal_confidence']:.2f})"))
    verdict_line = Text(f"{verdict}", style=f"bold {color}") + Text(f"  {entry['reason']}")
    body = Group(describe_order(entry["arguments"]), Text(""), scores, Text(""), verdict_line)
    console.print(Panel(body, title=f"Decider 2B · {entry['tool']}", title_align="left",
                        subtitle=f"{entry['latency_ms'] / 1000:.1f}s", subtitle_align="right",
                        border_style=color, box=box.ROUNDED, expand=False, padding=(0, 1)))


def show_note(text):
    result(f"Decider 2B: {text}", style="yellow")


# A spinner with the time so far, while work() runs. It disappears when done.
def wait(label, expected_seconds, work):
    columns = [SpinnerColumn(style=ACCENT), TextColumn(f"{label}…"),
               TimeElapsedColumn(), TextColumn(f"[dim](last one took {expected_seconds:.0f}s)[/]")]
    with Progress(*columns, console=console, transient=True) as progress:
        progress.add_task(label, total=None)
        return work()


# ---------------------------------------------------------------
# REPORTS
# ---------------------------------------------------------------

def print_whoami(session):
    department = session["department"]
    left = ledger.remaining(department)
    budget = ledger.DEPARTMENT_BUDGETS[department]
    table = Table.grid(padding=(0, 2))
    table.add_row(Text("User", style="dim"), Text(session["user"], style="bold"))
    table.add_row(Text("Department", style="dim"), Text(department, style="bold"))
    table.add_row(Text("Budget", style="dim"), budget_bar(left, budget) + Text(f"  {money(left)} left of {money(budget)}"))
    console.print()
    console.print(Panel(table, title=f"[{TITLE}] WHO AM I [/]", title_align="left", border_style=ACCENT, box=box.ROUNDED, expand=False))


def print_report():
    budgets = Table(title=" BUDGETS ", title_justify="left", title_style=TITLE, box=box.ROUNDED, border_style=ACCENT)
    budgets.add_column("Department", style="bold", header_style=f"bold {ACCENT}")
    budgets.add_column("Left")
    budgets.add_column("Spent", justify="right")
    budgets.add_column("Remaining", justify="right")
    for department in ledger.DEPARTMENT_BUDGETS:
        budget = ledger.DEPARTMENT_BUDGETS[department]
        left = ledger.remaining(department)
        budgets.add_row(department, budget_bar(left, budget), money(ledger.spent[department]),
                        Text(money(left), style=money_color(left, budget)))

    orders = Table(title=" ORDERS THIS SESSION ", title_justify="left", title_style=TITLE, box=box.ROUNDED, border_style=ACCENT)
    orders.add_column("Who")
    orders.add_column("Department")
    orders.add_column("Order")
    orders.add_column("Amount", justify="right")
    for order in ledger.orders:
        orders.add_row(Text(order["user"]), order["department"],
                       Text(f"{order['quantity']} x {order['item']} · {order['vendor']}"), money(order["amount"]))
    if not ledger.orders:
        orders.add_row(Text("No orders yet.", style="dim"), "", "", "")

    console.print()
    console.print(budgets)
    console.print(orders)
    console.print(Text(f"Every decision is in {ledger.AUDIT_LOG}", style="dim"))


def print_inventory(text):
    console.print()
    console.print(Panel(Text(text), title=f"[{TITLE}] INVENTORY [/]", title_align="left", border_style=ACCENT, box=box.ROUNDED, expand=False))
