# app.py
# The Spend Gate as a full-screen terminal app, built with Textual.
#
#     python app.py        (or: python start.py, which also starts Decider 2B)
#
# Why a full-screen app: a Decider 2B check takes 20-45 seconds on a laptop
# CPU. In the simple CLI (python agent.py) the whole program waits during that
# time. Here the agent runs in a background thread, so the screen stays alive:
# you can scroll, open the report or check your budget while a check runs.
#
# Layout:
#   ┌ log: every step, Decider panel and decision ─┬ sidebar: who, budgets, ┐
#   │                                               │ last verdict, orders   │
#   ├ activity line: spinner + what's running + timer ──────────────────────┤
#   └ input: requests and commands (→ accepts a suggestion) ─────────────────┘
#
# The tools, the guardrail and the rules are the same code as the CLI.
# This file only changes how things are shown and how the human answers.
import json
import os
import threading
import time
import urllib.request

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Footer, Header, Input, Label, OptionList, RichLog, Static
from textual.widgets.option_list import Option

import agent
import ledger
import policy
import policy_admin
import session_ui as ui
from decision_pattern.decider_client import ask_decider, yes_no_question
from decision_pattern.spend_guardrail import SpendGuardrail

COMMAND_WORDS = ["report", "whoami", "inventory", "policy", "cancel", "stop", "help", "clear", "quit"] + list(agent.SCENARIOS)
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ---------------------------------------------------------------
# SCREENS
# ---------------------------------------------------------------

# The demo roster as one line, so people know which names have which role.
def roster_hint():
    parts = []
    for name in policy.POLICY["roster"]:
        entry = policy.POLICY["roster"][name]
        if entry.get("department"):
            parts.append(f"{name} ({entry['department']} {entry['role']})")
        else:
            parts.append(f"{name} (app {entry['role']})")
    return "Demo roles: " + " · ".join(parts) + " · any other name = member"


# Sign-in: a name, then a department. Returns (name, department, role).
# The role comes from the roster in policy.json, never from the user.
class SignInScreen(Screen):
    def compose(self) -> ComposeResult:
        with Vertical(id="signin"):
            yield Static(ui.banner_panel(agent.LLM_PROVIDER))
            yield Label("Sign in  ·  demo: any name, no password. In production this is SSO.", classes="muted")
            yield Label(roster_hint(), classes="muted")
            yield Input(placeholder="Your name", id="name", max_length=40)
            yield Label("", id="name-error", classes="error")
            yield Label("Department  ·  pick one with the arrow keys and Enter", classes="muted")
            options = []
            for department in ledger.DEPARTMENT_BUDGETS:
                budget = ledger.DEPARTMENT_BUDGETS[department]
                left = ledger.remaining(department)
                prompt = Text(f"{department:26} ", style="bold") + ui.budget_bar(left, budget)
                prompt.append(f"  {ui.money(left)} of {ui.money(budget)}", style="dim")
                options.append(Option(prompt, id=department))
            yield OptionList(*options, id="departments")

    def on_mount(self):
        self.query_one("#name", Input).focus()

    # Enter on the name: check it, then move to the department list.
    def on_input_submitted(self, event: Input.Submitted):
        name = event.value.strip()
        error = self.query_one("#name-error", Label)
        if not ui.valid_name(name):
            error.update(ui.NAME_RULE)
            return
        error.update("")
        role, department = policy_admin.role_of(name)
        # Leaders belong to a department in the roster: no need to pick one.
        if department:
            self.dismiss((policy_admin.canonical_name(name), department, role))
            return
        self.query_one("#departments", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        name = policy_admin.canonical_name(self.query_one("#name", Input).value)
        if not ui.valid_name(name):
            self.query_one("#name-error", Label).update(ui.NAME_RULE)
            self.query_one("#name", Input).focus()
            return
        role, department = policy_admin.role_of(name)
        self.dismiss((name, department or event.option.id, role))


# The policy, and no-code changes for people whose role allows them.
# Pick a setting, type a value, press Enter to preview "old -> new", then Save.
# Every check happens in policy_admin.py; this screen only shows the results.
class PolicyScreen(ModalScreen):
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.selected = None      # the (setting, target) being changed
        self.previewed = None     # the exact text that was previewed

    def compose(self) -> ComposeResult:
        role = self.session.get("role", "member")
        with Vertical(id="policy"):
            yield Label(f"Policy  ·  signed in as {self.session['user']} ({role})", classes="approval-title")
            # The long part scrolls; the input and the buttons below stay on screen.
            with VerticalScroll(id="policy-body"):
                yield Static(ui.policy_panel(self.session), id="policy-view")
                if policy_admin.settings_for(self.session):
                    yield Label("Change a setting: pick it with the arrows and Enter", classes="muted")
                    yield OptionList(*self.setting_options(), id="settings")
            if policy_admin.settings_for(self.session):
                yield Input(placeholder="Pick a setting first", id="value", disabled=True)
                yield Label("", id="preview")
                with Horizontal():
                    yield Button("Save", id="save", variant="success", disabled=True)
                    yield Button("Close (Esc)", id="close")
            else:
                yield Label(f"Your role ({role}) can read the policy but not change it. "
                            "Department leaders and the app owner can.", classes="muted")
                with Horizontal():
                    yield Button("Close (Esc)", id="close")

    def setting_options(self):
        options = []
        for setting, target in policy_admin.settings_for(self.session):
            prompt = Text(policy_admin.label(setting, target), style="bold")
            # Numbers show their current value; add/remove show the list in the panel above.
            if setting in ("budget", "approval_over", "reorder_at", "order_qty"):
                prompt.append(f"   now {policy_admin.current_value(setting, target)}", style="dim")
            options.append(Option(prompt, id=f"{setting}|{target or ''}"))
        return options

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        setting, target = event.option.id.split("|", 1)
        self.selected = (setting, target or None)
        box = self.query_one("#value", Input)
        box.disabled = False
        box.value = ""
        if setting.startswith("add_"):
            box.placeholder = "Name to add, then Enter"
        elif setting.startswith("remove_"):
            box.placeholder = "Name to remove, then Enter"
        else:
            box.placeholder = f"New value (now {policy_admin.current_value(setting, target or None)}), then Enter"
        self.query_one("#preview", Label).update("")
        self.query_one("#save", Button).disabled = True
        box.focus()

    # Enter: check the change and show what would happen. Nothing is saved yet.
    def on_input_submitted(self, event: Input.Submitted):
        if self.selected is None:
            return
        setting, target = self.selected
        ok, message, new_value = policy_admin.check_change(self.session, setting, target, event.value)
        preview = self.query_one("#preview", Label)
        if not ok:
            preview.update(Text(message, style="red"))
            self.query_one("#save", Button).disabled = True
            return
        self.previewed = event.value
        line = Text(f"{policy_admin.label(setting, target)}: ", style="bold")
        line.append(f"{policy_admin.current_value(setting, target)}  ->  {policy_admin.format_value(setting, new_value)}")
        line.append("   Press Save to apply.", style="dim")
        preview.update(line)
        self.query_one("#save", Button).disabled = False
        self.query_one("#save", Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "save":
            self.save()

    # Saves exactly what was previewed. Not while a request is running:
    # a change must never apply halfway through an order.
    def save(self):
        preview = self.query_one("#preview", Label)
        if self.app.busy:
            preview.update(Text("A request is running. Save after it finishes.", style="yellow"))
            return
        setting, target = self.selected
        ok, message = policy_admin.apply_change(self.session, setting, target, self.previewed)
        preview.update(Text(message, style="green" if ok else "red"))
        self.query_one("#save", Button).disabled = True
        if ok:
            self.query_one("#policy-view", Static).update(ui.policy_panel(self.session))
            settings = self.query_one("#settings", OptionList)
            settings.clear_options()
            settings.add_options(self.setting_options())
            self.app.write_log(ui.step_text("Policy changed", Text(message), dot="green"))

    def action_close(self):
        self.dismiss(None)


# Asks before quitting: when you press Esc with nothing running, or when you
# quit while a request is still running.
class QuitScreen(ModalScreen):
    BINDINGS = [("y", "answer(True)", "Quit"), ("n", "answer(False)", "Stay"), ("escape", "answer(False)", "Stay")]

    def __init__(self, busy):
        super().__init__()
        self.busy = busy

    def compose(self) -> ComposeResult:
        with Vertical(id="approval"):
            if self.busy:
                yield Label("A request is still running", classes="approval-title")
                yield Static("Quit and cancel it? The agent stops before its next step, "
                             "so nothing more gets ordered. Orders already placed stay placed.")
            else:
                yield Label("Quit the app?", classes="approval-title")
                yield Static("Your orders and policy changes are already saved in the logs.")
            with Horizontal():
                yield Button("Quit (y)", id="quit", variant="error")
                yield Button("Stay (n)", id="stay", variant="primary")

    def on_mount(self):
        # Idle: Enter quits. Busy: the safe choice (Stay) has focus.
        if self.busy:
            self.query_one("#stay", Button).focus()
        else:
            self.query_one("#quit", Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "quit")

    def action_answer(self, quit_now):
        self.dismiss(quit_now)


# A human approval as a pop-up. Escape counts as Deny: fail closed.
class ApprovalScreen(ModalScreen):
    BINDINGS = [("y", "answer(True)", "Approve"), ("n", "answer(False)", "Deny"),
                ("escape", "answer(False)", "Deny")]

    def __init__(self, question):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="approval"):
            yield Label("A human decision is needed", classes="approval-title")
            # Text(), not markup: the question can contain untrusted values.
            yield Static(Text(self.question))
            with Horizontal():
                yield Button("Approve (y)", id="approve", variant="success")
                yield Button("Deny (n)", id="deny", variant="error")

    def on_mount(self):
        self.query_one("#deny", Button).focus()  # the safe choice has focus

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "approve")

    def action_answer(self, approved):
        self.dismiss(approved)


# ---------------------------------------------------------------
# THE DISPLAY
# The same functions as session_ui's display, but for this app. They're
# called from the agent's background thread, so every screen change goes
# through app.call_from_thread(): only the app's own thread may touch widgets.
# ---------------------------------------------------------------

class TextualDisplay:
    def __init__(self, app):
        self.app = app
        self.agent_text = []

    # Hands a screen change to the app's thread. Once the app is closing,
    # it does nothing, so a request being cancelled can't throw errors
    # at a screen that's already gone.
    def post(self, callback, *args):
        if not self.app.is_running:
            return
        try:
            self.app.call_from_thread(callback, *args)
        except RuntimeError:
            pass

    def write(self, renderable):
        self.post(self.app.write_log, renderable)

    def show_request(self, request):
        self.write(Text(""))
        self.write(ui.request_text(request))
        self.post(self.app.set_activity, "Agent is planning")

    def result(self, text, style="dim"):
        self.write(ui.result_text(text, style))

    def show_tool_result(self, text):
        self.result(text)

    def show_price_block(self, problem):
        self.write(ui.price_block_text(problem))

    def show_spend_gate(self, decision, department, vendor, amount, reason):
        self.write(ui.spend_gate_text(decision, department, vendor, amount, reason))

    def show_error(self, error):
        self.write(ui.error_text(error))

    def show_summary(self, entries):
        if entries:
            self.write(ui.summary_table(entries))
        else:
            self.result("No purchases were proposed.")

    # Strands' callback: tool calls become step lines, text is collected
    # until the message is complete.
    def on_agent_event(self, **kwargs):
        if kwargs.get("data"):
            if not self.agent_text:
                self.post(self.app.set_activity, "Agent is writing")
            self.agent_text.append(kwargs["data"])
        tool_use = kwargs.get("event", {}).get("contentBlockStart", {}).get("start", {}).get("toolUse")
        if tool_use:
            self.flush_agent_text()
            self.write(ui.step_text(tool_use["name"], dot=ui.ACCENT))
            self.post(self.app.set_activity, f"Running {tool_use['name']}")
        if kwargs.get("complete"):
            self.flush_agent_text()
            self.post(self.app.set_activity, "Agent is planning")

    def flush_agent_text(self):
        text = "".join(self.agent_text).strip()
        self.agent_text.clear()
        if text:
            self.write(ui.agent_message_text(text))

    # The guardrail's display.
    def show_check(self, entry):
        self.write(ui.check_panel(entry))
        self.post(self.app.remember_verdict, entry)

    def show_note(self, text):
        self.result(f"Decider 2B: {text}", style="yellow")

    def wait(self, label, expected_seconds, work):
        self.post(self.app.set_activity, label, expected_seconds)
        try:
            return work()
        finally:
            self.post(self.app.set_activity, "Agent is planning")

    # Shows the approval pop-up and waits for the answer. If the app closes
    # before anyone answers, the answer is no.
    def ask_yes_no(self, question):
        answered = threading.Event()
        answer = {"approved": False}

        def on_answer(approved):
            answer["approved"] = bool(approved)
            answered.set()

        if not self.app.is_running:
            return False
        self.post(self.app.push_screen, ApprovalScreen(question), on_answer)
        while not answered.wait(0.5):
            if not self.app.is_running:
                return False
        return answer["approved"]

    # The guardrail's ask_human wants "y" or "n" back.
    def ask_human(self, prompt):
        if self.ask_yes_no(prompt):
            return "y"
        return "n"


# ---------------------------------------------------------------
# THE APP
# ---------------------------------------------------------------

class SpendGateApp(App):
    TITLE = "AI Agent Spend Gate"
    SUB_TITLE = "The agent proposes · Decider 2B checks · the rules decide"
    CSS = """
    #body { height: 1fr; }
    #log { width: 1fr; border: round cyan; padding: 0 1; }
    #sidebar { width: 56; border: round cyan; padding: 0 1; }
    #sidebar Static { margin-bottom: 1; }
    #activity-row { height: 1; }
    #activity { width: 1fr; height: 1; padding: 0 2; }
    #cancel { display: none; margin: 0 2; }
    #prompt { border: round cyan; }
    .muted { color: $text-muted; margin-top: 1; }
    .error { color: $error; }
    SignInScreen { align: center middle; }
    #signin { width: 90; height: auto; border: round cyan; padding: 1 2; }
    #departments { height: auto; max-height: 10; }
    ApprovalScreen { align: center middle; }
    #approval { width: 72; height: auto; border: thick yellow; padding: 1 2; background: $panel; }
    #approval Horizontal { height: auto; align: center middle; margin-top: 1; }
    #approval Button { margin: 0 2; }
    PolicyScreen { align: center middle; }
    #policy { width: 100; height: 90%; border: thick cyan; padding: 1 2; background: $panel; }
    #policy-body { height: 1fr; }
    #policy Horizontal { height: auto; align: center middle; margin-top: 1; }
    #policy Button { margin: 0 2; }
    #settings { height: auto; max-height: 10; }
    .approval-title { text-style: bold; color: yellow; margin-bottom: 1; }
    """
    BINDINGS = [
        Binding("f1", "command('help')", "Help"),
        Binding("f2", "command('report')", "Report"),
        Binding("f3", "command('whoami')", "Who am I"),
        Binding("f4", "command('inventory')", "Inventory"),
        Binding("f5", "command('policy')", "Policy"),
        Binding("escape", "cancel_request", "Cancel / Quit"),
        Binding("ctrl+l", "command('clear')", "Clear"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.display_ui = TextualDisplay(self)
        self.guardrail = None
        self.busy = False
        self.cancelling = False
        self.last_entry = None
        self.activity_label = ""
        self.activity_started = 0.0
        self.activity_expected = None
        self.frame = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield RichLog(id="log", wrap=True, markup=False, highlight=False, min_width=40)
            with Vertical(id="sidebar"):
                yield Static(id="who")
                yield Static(id="budgets")
                yield Static(id="last")
                yield Static(id="orders")
        with Horizontal(id="activity-row"):
            yield Static(id="activity")
            yield Button("■ Cancel (Esc)", id="cancel", variant="error", compact=True)
        yield Input(placeholder="Ask for a purchase, or type a command  (→ accepts a suggestion)",
                    id="prompt", suggester=SuggestFromList(COMMAND_WORDS, case_sensitive=False))
        yield Footer()

    def on_mount(self):
        # Every step the agent takes is shown through this app from now on.
        agent.UI = self.display_ui
        self.guardrail = SpendGuardrail(guarded_tools=["place_order"], goal_check=agent.check_goal,
                                        display=self.display_ui, ask_human=self.display_ui.ask_human,
                                        categories=agent.category_options)
        self.set_interval(0.1, self.tick)
        self.push_screen(SignInScreen(), self.signed_in)

    def signed_in(self, result):
        agent.SESSION["user"], agent.SESSION["department"], agent.SESSION["role"] = result
        self.write_log(ui.step_text("Signed in", Text(f"{result[0]} · {result[1]} · {result[2]}"), dot="green"))
        self.write_log(ui.help_panel(list(agent.SCENARIOS)))
        self.refresh_sidebar()
        self.query_one("#prompt", Input).focus()
        self.start_thread(self.warm_up)

    # ---- the log, the sidebar and the activity line ----

    def write_log(self, renderable):
        self.query_one("#log", RichLog).write(renderable)
        self.refresh_sidebar()

    def remember_verdict(self, entry):
        self.last_entry = entry

    def refresh_sidebar(self):
        if not agent.SESSION.get("user"):
            return
        department = agent.SESSION["department"]
        who = Text("SIGNED IN\n", style=ui.TITLE)
        who.append(f"{agent.SESSION['user']}", style="bold")
        who.append(f"  {agent.SESSION.get('role', 'member')}\n", style=ui.ACCENT)
        who.append(f"{department}  ·  LLM: {agent.LLM_PROVIDER}", style="dim")
        self.query_one("#who", Static).update(who)

        budgets = Table.grid(padding=(0, 1))
        for name in ledger.DEPARTMENT_BUDGETS:
            budget = ledger.DEPARTMENT_BUDGETS[name]
            left = ledger.remaining(name)
            marker = "›" if name == department else " "
            budgets.add_row(Text(marker, style=ui.ACCENT), Text(name, style="bold"),
                            ui.budget_bar(left, budget, width=10),
                            Text(ui.money(left), style=ui.money_color(left, budget)))
        self.query_one("#budgets", Static).update(budgets)

        last = Text("LAST DECIDER CHECK\n", style=ui.TITLE)
        if self.last_entry is None:
            last.append("none yet", style="dim")
        else:
            last.append_text(ui.decision_text(self.last_entry["verdict"].upper()))
            last.append(f"  {self.last_entry['latency_ms'] / 1000:.0f}s\n", style="dim")
            last.append_text(ui.describe_order(self.last_entry["arguments"]))
        self.query_one("#last", Static).update(last)

        orders = Text(f"ORDERS · {len(ledger.orders)}\n", style=ui.TITLE)
        for order in ledger.orders[-5:]:
            orders.append(f"{order['quantity']} x {order['item']}  {ui.money(order['amount'])}\n")
        if not ledger.orders:
            orders.append("none yet", style="dim")
        self.query_one("#orders", Static).update(orders)

    # What's running right now, with a spinner and a timer.
    def set_activity(self, label, expected_seconds=None):
        self.activity_label = label
        self.activity_started = time.perf_counter()
        self.activity_expected = expected_seconds

    def clear_activity(self):
        self.activity_label = ""

    def tick(self):
        line = Text()
        if self.activity_label:
            self.frame = (self.frame + 1) % len(SPINNER)
            elapsed = time.perf_counter() - self.activity_started
            line.append(SPINNER[self.frame] + " ", style=ui.ACCENT)
            line.append(f"{self.activity_label}…  {elapsed:.0f}s")
            if self.activity_expected:
                line.append(f"  (last one took {self.activity_expected:.0f}s)", style="dim")
        else:
            line.append("● ", style="green")
            line.append("Ready · type a request, or a command (F1 help)", style="dim")
        self.query_one("#activity", Static).update(line)
        self.query_one("#cancel", Button).display = self.busy and not self.cancelling

    # ---- input ----

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "prompt":
            return
        text = event.value.strip()
        event.input.value = ""
        if text:
            self.action_command(text)

    # Commands work any time, even while a request runs. Requests run one at
    # a time, because they share the session's budget and inventory.
    def action_command(self, text):
        command = text.lower()
        if command == "quit":
            self.action_quit()
        elif command == "help":
            self.write_log(ui.help_panel(list(agent.SCENARIOS)))
        elif command == "report":
            self.write_log(ui.report_group())
        elif command == "whoami":
            self.write_log(ui.whoami_panel(agent.SESSION))
        elif command == "inventory":
            self.write_log(ui.inventory_panel(agent.inventory_text()))
        elif command in ("cancel", "stop"):
            self.action_cancel_request()
        elif command == "policy":
            self.push_screen(PolicyScreen(agent.SESSION))
        elif command == "clear":
            self.query_one("#log", RichLog).clear()
        elif self.busy:
            self.write_log(ui.result_text("Still working on the last request. Requests run one at a time; "
                                          "commands like report work now.", style="yellow"))
        else:
            self.busy = True
            self.start_thread(self.run_request, text)

    # Stops the running request now: the guardrail stops waiting on Decider
    # and denies the call, and the agent stops before its next step.
    # Nothing more gets ordered. Called by Esc, the Cancel button, or typing
    # "cancel" / "stop".
    def action_cancel_request(self):
        if not self.busy:
            self.push_screen(QuitScreen(busy=False), self.quit_answered)
            return
        if self.cancelling:
            return
        self.cancelling = True
        agent.cancel_running()
        # A waiting approval pop-up counts as "no".
        if isinstance(self.screen, ApprovalScreen):
            self.screen.dismiss(False)
        self.set_activity("Cancelling: no more orders will be placed")
        self.write_log(ui.result_text("Cancelling the request…", style="yellow"))

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.action_cancel_request()

    # Quit right away when idle; ask first while a request is running.
    # A plain def, not "async def": an async function called without
    # "await" never runs, which is why typing "quit" used to do nothing.
    def action_quit(self):
        if not self.busy:
            self.exit()
            return
        self.push_screen(QuitScreen(busy=True), self.quit_answered)

    def quit_answered(self, quit_now):
        if quit_now:
            agent.cancel_running()
            self.exit()

    # Calls back into the app's thread from a background thread (safe once
    # the app is closing too).
    def post(self, callback, *args):
        if not self.is_running:
            return
        try:
            self.call_from_thread(callback, *args)
        except RuntimeError:
            pass

    # Starts background work in a daemon thread: one that can never stop
    # the program from exiting. (A normal worker thread would make quit wait
    # until a slow model call finished.)
    def start_thread(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()
        return thread

    # ---- background work ----

    # Runs one request in a background thread, so the screen stays responsive.
    def run_request(self, text):
        try:
            agent.run_scenario_or_request(text, self.guardrail)
        finally:
            self.post(self.request_done)

    def request_done(self):
        self.busy = False
        self.cancelling = False
        self.clear_activity()
        self.refresh_sidebar()

    # Loads Decider 2B and the local model while the user reads the help,
    # so the first real order doesn't pay the start-up cost.
    def warm_up(self):
        self.post(self.set_activity, "Warming up Decider 2B and the LLM")
        started = time.perf_counter()
        try:
            ask_decider("Warm-up request.", {"ready": yes_no_question("Is this a warm-up?", "yes", "no")})
            decider = f"Decider 2B ready ({time.perf_counter() - started:.0f}s)"
            style = "dim"
        except Exception:
            decider = "Decider 2B isn't running. Start everything with: python start.py"
            style = "yellow"
        self.post(self.write_log, ui.result_text(decider, style))
        if agent.LLM_PROVIDER == "ollama":
            self.post(self.write_log, ui.result_text(warm_ollama(), "dim"))
        self.post(self.clear_activity)


# Asks Ollama to load the model into memory now (an empty prompt loads it
# without generating anything) and keep it loaded for 30 minutes.
def warm_ollama():
    body = json.dumps({"model": agent.OLLAMA_MODEL_ID, "prompt": "", "keep_alive": "30m"}).encode()
    request = urllib.request.Request(f"{agent.OLLAMA_HOST}/api/generate", data=body, method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()
    except OSError:
        return "Ollama isn't reachable. Install and open it from https://ollama.com"
    return f"{agent.OLLAMA_MODEL_ID} loaded ({time.perf_counter() - started:.0f}s)"


if __name__ == "__main__":
    app = SpendGateApp()
    app.run()
    # If a request was cancelled on the way out, its thread may still be
    # waiting on a model. The screen is closed and every log row is already
    # written, so exit now instead of waiting for that thread.
    if app.busy:
        print("Cancelled the running request. Nothing more was ordered.")
        os._exit(0)
