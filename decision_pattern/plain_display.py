# plain_display.py
# The guardrail's default display: plain text plus a stdlib progress bar.
#
# The guardrail never prints on its own. It calls three functions on a
# "display", and this module is the default one. Any module (or object)
# with the same three functions can replace it, for example a fancier
# terminal UI, a web page, or a logger:
#
#     show_check(entry)                  one finished check, with its scores
#     show_note(text)                    a short one-line message
#     wait(label, expected_seconds, work) call work() while showing the wait,
#                                          and return what work() returns
#
# Standard library only, so the pattern works with no extra installs.
import json
import sys

from decision_pattern.progress import start_progress, stop_progress

# Verdict colors in a real terminal: green = proceed, red = deny,
# yellow = guide or confirm. Plain text when output goes to a file.
VERDICT_COLORS = {"proceed": "32", "deny": "31", "guide": "33", "confirm": "33"}


def paint(verdict):
    if not sys.stdout.isatty():
        return verdict.upper()
    return f"\033[{VERDICT_COLORS.get(verdict, '1')}m{verdict.upper()}\033[0m"


# Prints one guardrail check so you can see the numbers behind the verdict.
def show_check(entry):
    print()
    print(f"[Decider 2B guardrail] {entry['tool']} {json.dumps(entry['arguments'])}")
    print(f"    grounded       : {entry['grounded']:.2f}")
    print(f"    injected       : {entry['injected']:.2f}")
    print(f"    item category  : {entry['item_category']} ({entry['category_confidence']:.2f})")
    print(f"    user goal      : {entry['user_goal']} ({entry['goal_confidence']:.2f})")
    print(f"    -> {paint(entry['verdict'])}: {entry['reason']}  [{entry['latency_ms']} ms]")


def show_note(text):
    print(f"\n[Decider 2B guardrail] {text}")


# Runs work() with a progress bar on screen.
# try/finally: the bar stops even if work() fails, so it never keeps
# drawing over an error message.
def wait(label, expected_seconds, work):
    handle = start_progress(label, expected_seconds)
    try:
        return work()
    finally:
        stop_progress(handle)
