# session_ui.py
# The Rich terminal display: the look of the app, and the simple CLI.
#
# Two kinds of functions live here:
#   - BUILDERS return a panel, table or line of text without printing it.
#     Both front ends use them, so they look the same:
#       python agent.py   prints them to the terminal (this file)
#       python app.py     writes them into the Textual app's log pane
#   - PRINTERS (show_..., print_...) print a builder's result. Together they
#     are the "display" the agent and the guardrail call (see agent.UI).
#
# Display rules (borrowed from how good AI terminals show work):
#   - each step is one line starting with ⏺, its result indented under ⎿
#   - color is rare and means something: green = go, red = stop,
#     yellow = a person or a retry, cyan = this app
#   - important results (Decider verdicts) get a frame
#
# Security: LLM output and tool data are UNTRUSTED. Rich treats [square
# brackets] as style commands, so untrusted text is always wrapped in Text()
# or escape()d. Otherwise an agent could restyle or hide parts of the screen.
#
# Sign-in here is a demo: any valid name works and there's no password.
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

import catalog
import ledger
import policy

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
NAME_RULE = "Use letters, spaces, - ' or . only (up to 40 characters), starting with a letter."

COMMANDS = [
    ("report", "budgets and orders so far"),
    ("whoami", "who is signed in, and the budget left"),
    ("inventory", "what's on the shelf"),
    ("policy", "the purchasing rules (leaders can change them in the app: F5)"),
    ("audit", "audit pack, log integrity check, policy as Terraform (in the app: F6)"),
    ("cancel", "stop the running request (or press Esc, or click Cancel)"),
    ("help", "show this menu"),
    ("quit", "exit (Esc also offers to quit when nothing is running)"),
]


def valid_name(name):
    # fullmatch: the WHOLE name must fit the pattern, not just the start.
    return NAME_PATTERN.fullmatch(name) is not None


# ---------------------------------------------------------------
# SMALL BUILDERS
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
def step_text(title, detail=None, dot="white"):
    line = Text("⏺ ", style=dot)
    line.append(title, style="bold")
    if detail is not None:
        line.append("  ")
        line.append(detail if isinstance(detail, Text) else Text(str(detail)))
    return line


# The result under a step: "  ⎿  first line", then the rest indented.
def result_text(text, style="dim"):
    lines = str(text).splitlines() or [""]
    out = Text("  ⎿  " + lines[0], style=style)
    for line in lines[1:]:
        out.append("\n     " + line, style=style)
    return out


def agent_message_text(text):
    return Text("⏺ ", style="white") + Text(text)


def request_text(request):
    line = Text("> ", style=f"bold {ACCENT}") + Text(request, style="bold")
    line.append("\n  The agent plans, then Decider 2B checks every order before it runs.", style="dim")
    return line


def price_block_text(problem):
    return step_text("Catalog check", Text("BLOCKED", style="bold red") + Text(f"  {problem}"), dot="red")


def spend_gate_text(decision, department, vendor, amount, reason):
    detail = decision_text(decision)
    detail.append(f"  {department} · {vendor} · {money(amount)}", style="white")
    return Group(step_text("Spend Gate", detail, dot=DECISION_COLORS.get(decision, "white")), result_text(reason))


def error_text(error):
    return step_text("The request failed", Text(f"{type(error).__name__}: {error}"), dot="red")


# "8 x printer paper · Office Depot · $52.49 each" from tool arguments.
def describe_order(arguments):
    parts = [f"{arguments.get('quantity', '?')} x {arguments.get('item', '?')}", str(arguments.get("vendor", "?"))]
    if isinstance(arguments.get("unit_price"), (int, float)):
        parts.append(f"{money(arguments['unit_price'])} each")
    return Text(" · ".join(parts))


# ---------------------------------------------------------------
# PANEL AND TABLE BUILDERS
# ---------------------------------------------------------------

def banner_panel(llm_name):
    body = Group(
        Text(LOGO, style=f"bold {ACCENT}"),
        Text(""),
        Text(f"LLM: {llm_name}  ·  guardrail: Decider 2B on every order  ·  data: all made up", style="dim"),
    )
    return Panel(body, border_style=ACCENT, box=box.ROUNDED, padding=(1, 2), expand=False)


# One Decider 2B check: the order, the scores as bars, and the verdict.
# The border color is the verdict's color.
def check_panel(entry):
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
    verdict_line = Text(verdict, style=f"bold {color}") + Text(f"  {entry['reason']}")
    body = Group(describe_order(entry["arguments"]), Text(""), scores, Text(""), verdict_line)
    return Panel(body, title=f"Decider 2B · {entry['tool']}", title_align="left",
                 subtitle=f"{entry['latency_ms'] / 1000:.1f}s", subtitle_align="right",
                 border_style=color, box=box.ROUNDED, expand=False, padding=(0, 1))


def summary_table(entries):
    table = Table(box=box.SIMPLE, show_edge=False, pad_edge=False)
    table.add_column("Decider 2B", style="bold")
    table.add_column("Order")
    table.add_column("Time", justify="right", style="dim")
    for entry in entries:
        table.add_row(decision_text(entry["verdict"].upper()), describe_order(entry["arguments"]),
                      f"{entry['latency_ms'] / 1000:.0f}s")
    return table


def help_panel(scenarios):
    table = Table.grid(padding=(0, 3))
    for command, description in COMMANDS:
        table.add_row(Text(command, style=ACCENT), Text(description, style="dim"))
    example = Text("  Ask in plain English, for example: ", style="dim")
    example.append("we need printer paper by tomorrow", style="italic")
    samples = Text("  Sample scenarios: ", style="dim")
    samples.append("  ".join(scenarios), style=ACCENT)
    return Panel(Group(example, Text(""), table, Text(""), samples),
                 title=f"[{TITLE}] WHAT YOU CAN DO [/]", title_align="left",
                 border_style=ACCENT, box=box.ROUNDED, expand=False)


def whoami_panel(session):
    department = session["department"]
    left = ledger.remaining(department)
    budget = ledger.DEPARTMENT_BUDGETS[department]
    table = Table.grid(padding=(0, 2))
    table.add_row(Text("User", style="dim"), Text(session["user"], style="bold"))
    table.add_row(Text("Role", style="dim"), Text(session.get("role", "member"), style="bold"))
    table.add_row(Text("Department", style="dim"), Text(department, style="bold"))
    table.add_row(Text("Budget", style="dim"), budget_bar(left, budget) + Text(f"  {money(left)} left of {money(budget)}"))
    return Panel(table, title=f"[{TITLE}] WHO AM I [/]", title_align="left", border_style=ACCENT, box=box.ROUNDED, expand=False)


def budgets_table():
    table = Table(title=" BUDGETS ", title_justify="left", title_style=TITLE, box=box.ROUNDED, border_style=ACCENT)
    table.add_column("Department", style="bold", header_style=f"bold {ACCENT}")
    table.add_column("Left")
    table.add_column("Spent", justify="right")
    table.add_column("Remaining", justify="right")
    for department in ledger.DEPARTMENT_BUDGETS:
        budget = ledger.DEPARTMENT_BUDGETS[department]
        left = ledger.remaining(department)
        table.add_row(department, budget_bar(left, budget), money(ledger.spent[department]),
                      Text(money(left), style=money_color(left, budget)))
    return table


def orders_table():
    table = Table(title=" ORDERS THIS SESSION ", title_justify="left", title_style=TITLE, box=box.ROUNDED, border_style=ACCENT)
    table.add_column("Who")
    table.add_column("Department")
    table.add_column("Order")
    table.add_column("Amount", justify="right")
    for order in ledger.orders:
        table.add_row(Text(order["user"]), order["department"],
                      Text(f"{order['quantity']} x {order['item']} · {order['vendor']}"), money(order["amount"]))
    if not ledger.orders:
        table.add_row(Text("No orders yet.", style="dim"), "", "", "")
    return table


def report_group():
    return Group(budgets_table(), orders_table(), Text(f"Every decision is in {ledger.AUDIT_LOG}", style="dim"))


# The current purchasing policy, for anyone to read. Reorder settings are
# need-to-know: only the items the person's department uses (all for the owner).
def policy_panel(session=None):
    data = policy.POLICY
    table = Table.grid(padding=(0, 2))
    table.add_row(Text("Approval limit", style="dim"), Text(f"orders over {money(data['approval_over'])} need a human"))
    table.add_row(Text("Approved vendors", style="dim"), Text(", ".join(data["approved_vendors"]) or "(none)"))
    table.add_row(Text("Allowed categories", style="dim"), Text(", ".join(data["allowed_categories"]) or "(none)"))
    for department in data["department_budgets"]:
        table.add_row(Text(f"Budget: {department}", style="dim"), Text(money(data["department_budgets"][department])))
    for item in data["reorder"]:
        if session and session.get("role") != "owner" and not catalog.department_uses(session.get("department"), item):
            continue
        settings = data["reorder"][item]
        table.add_row(Text(f"Reorder: {item}", style="dim"),
                      Text(f"below {settings['reorder_at']}, order {settings['order_qty']}"))
    return Panel(table, title=f"[{TITLE}] POLICY [/]", title_align="left", border_style=ACCENT, box=box.ROUNDED, expand=False)


# What a new audit pack contains, at a glance.
def audit_summary_panel(summary):
    table = Table.grid(padding=(0, 2))
    table.add_row(Text("Scope", style="dim"), Text(summary["scope"]))
    table.add_row(Text("Period", style="dim"), Text(f"{summary['period'][0]}  to  {summary['period'][1]}"))
    table.add_row(Text("Decisions", style="dim"), Text(str(summary["decisions"])))
    table.add_row(Text("Exceptions", style="dim"), Text(f"{len(summary['exceptions'])} (denied, blocked, human-decided or cancelled)"))
    table.add_row(Text("Policy changes", style="dim"), Text(str(len(summary["policy_changes"]))))
    for name, ok, rows, message, head in summary["verification"]:
        mark = Text("✓ ", style="green") if ok else Text("✗ ", style="bold red")
        table.add_row(Text(f"Log: {name}", style="dim"), mark + Text(message))
    table.add_row(Text("Saved to", style="dim"), Text(summary["folder"], style="bold"))
    return Panel(table, title=f"[{TITLE}] AUDIT PACK [/]", title_align="left", border_style="green", box=box.ROUNDED, expand=False)


# The hash-chain check for both logs.
def verify_panel(results):
    table = Table.grid(padding=(0, 2))
    all_ok = True
    for name, ok, rows, message, head in results:
        all_ok = all_ok and ok
        mark = Text("✓ ", style="bold green") if ok else Text("✗ ", style="bold red")
        table.add_row(mark + Text(name, style="bold"), Text(message))
        table.add_row(Text(""), Text(f"latest hash {head[:16]}…", style="dim"))
    color = "green" if all_ok else "red"
    title = "LOGS VERIFIED" if all_ok else "LOG TAMPERING DETECTED"
    return Panel(table, title=f"[{TITLE}] {title} [/]", title_align="left", border_style=color, box=box.ROUNDED, expand=False)


def terraform_panel(folder):
    table = Table.grid(padding=(0, 2))
    table.add_row(Text("terraform.tfvars.json", style="bold"), Text("the policy values right now", style="dim"))
    table.add_row(Text("variables.tf", style="bold"), Text("typed, with the app's hard limits as validation", style="dim"))
    table.add_row(Text("main.tf", style="bold"), Text("versioned private S3 bucket + read-only IAM policy", style="dim"))
    table.add_row(Text("Saved to", style="dim"), Text(folder, style="bold"))
    return Panel(table, title=f"[{TITLE}] POLICY AS TERRAFORM [/]", title_align="left", border_style=ACCENT, box=box.ROUNDED, expand=False)


def inventory_panel(text):
    return Panel(Text(text), title=f"[{TITLE}] INVENTORY [/]", title_align="left", border_style=ACCENT, box=box.ROUNDED, expand=False)


# ---------------------------------------------------------------
# THE CLI'S SIGN-IN (python agent.py)
# ---------------------------------------------------------------

def section(title):
    console.print()
    console.print(Text(f" {title.upper()} ", style=TITLE) + Text(" " + "─" * 40, style="dim"))


def warn(message):
    console.print(Text("! ", style="bold yellow") + Text(message))


def print_banner(llm_name):
    console.print(banner_panel(llm_name))


def sign_in():
    section("Sign in")
    console.print(Text("Demo: any name, no password. In production this is SSO.", style="dim"))
    while True:
        try:
            name = console.input(f"[{ACCENT}]›[/] Name: ").strip()
        except EOFError:
            return "demo user"
        if valid_name(name):
            return name
        warn(NAME_RULE)


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
    console.print(step_text("Signed in", Text(f"{session['user']} · {session['department']} · {session.get('role', 'member')}"), dot="green"))


def print_help(scenarios):
    console.print()
    console.print(help_panel(scenarios))


# A status line (who, where, money left) above a short input arrow.
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


def print_whoami(session):
    console.print()
    console.print(whoami_panel(session))


def print_report():
    console.print()
    console.print(report_group())


def print_inventory(text):
    console.print()
    console.print(inventory_panel(text))


# ---------------------------------------------------------------
# THE DISPLAY: what agent.py and the guardrail call while a request runs.
# app.py has a class with these same functions for the Textual app.
# ---------------------------------------------------------------

def show_request(request):
    console.print()
    console.print(request_text(request))


def result(text, style="dim"):
    console.print(result_text(text, style))


def show_tool_result(text):
    result(text)


def show_price_block(problem):
    console.print(price_block_text(problem))


def show_spend_gate(decision, department, vendor, amount, reason):
    console.print(spend_gate_text(decision, department, vendor, amount, reason))


def show_error(error):
    console.print(error_text(error))


def show_summary(entries):
    if not entries:
        result("No purchases were proposed.")
        return
    console.print()
    console.print(summary_table(entries))


# A yes/no question for a human approver. No answer counts as no.
def ask_yes_no(question):
    try:
        answer = console.input(f"[bold yellow]?[/] {escape(question)} [dim](y/n)[/] ")
    except EOFError:
        return False
    return answer.strip().lower() == "y"


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
        console.print(step_text(tool_use["name"], dot=ACCENT))
    if kwargs.get("complete"):
        flush_agent_text()


def flush_agent_text():
    text = "".join(agent_text).strip()
    agent_text.clear()
    if text:
        console.print()
        console.print(agent_message_text(text))


# The guardrail's display: SpendGuardrail(display=session_ui) calls these.
def show_check(entry):
    console.print(check_panel(entry))


def show_note(text):
    result(f"Decider 2B: {text}", style="yellow")


# A spinner with the time so far, while work() runs. It disappears when done.
def wait(label, expected_seconds, work):
    columns = [SpinnerColumn(style=ACCENT), TextColumn(f"{label}…"),
               TimeElapsedColumn(), TextColumn(f"[dim](last one took {expected_seconds:.0f}s)[/]")]
    with Progress(*columns, console=console, transient=True) as progress:
        progress.add_task(label, total=None)
        return work()
