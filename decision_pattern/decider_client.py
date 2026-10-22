# decider_client.py
# Talks to Strands Decider 2B running on this computer.
#
# Decider 2B is a small decision model. It doesn't write text. You send it
# a "state" (the facts) and typed questions, and it answers each one with a
# number between 0 and 1. For a yes/no question, the number is the
# probability that the answer is "yes".
#
# Start the Decider server first, in its own terminal:
#     strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --port 8099
#
# Only the standard library is used here: json to build the request,
# urllib to send it, os to read a setting, time to measure speed,
# threading to make a slow request cancellable.
import json
import os
import threading
import time
import urllib.error
import urllib.request

# Where the Decider server is listening. Set STRANDS_DECIDER_URL to change it.
DECIDER_URL = os.environ.get("STRANDS_DECIDER_URL", "http://127.0.0.1:8099")

# How long to wait for an answer, in seconds. On a laptop CPU with no GPU,
# the first request can take a while.
TIMEOUT_SECONDS = 120


# Builds a yes/no question. "criteria" says what "true" and "false" mean.
# Clear descriptions of true and false make the answers much sharper.
def yes_no_question(instructions, true_means, false_means):
    return {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": true_means, "false": false_means},
    }


# Builds a pick-one-option question. "options" maps each option's name to
# what that option means.
def choice_question(instructions, options):
    return {
        "type": "choice",
        "instructions": instructions,
        "criteria": options,
    }


# Sends one state and several questions in one request.
# The state is read once and shared by every question, so asking three
# questions costs much less than three separate requests.
# Returns two values: the answers (keyed by question name) and the time
# the round trip took, in milliseconds.
#
# Answer shapes:
#   yes/no:  {"type": "noul", "noul": 0.91}               (0.91 = 91% "yes")
#   choice:  {"type": "choice", "choice": "gift cards",
#             "probabilities": {...}, "confidence": 0.88}
def ask_decider(state, questions):
    body = json.dumps({"state": state, "questions": questions}).encode()
    request = urllib.request.Request(
        DECIDER_URL + "/v1/systemone",
        data=body,
        headers={"content-type": "application/json"},
    )

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
    except urllib.error.URLError as error:
        # Fail with a helpful message instead of a long traceback.
        raise RuntimeError(
            f"Decider server isn't answering at {DECIDER_URL} ({error}). "
            "Start it with: strands-decider serve "
            "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --port 8099"
        )
    except TimeoutError:
        # Connected, but no answer in time (for example, Decider is busy).
        raise RuntimeError(f"Decider didn't answer within {TIMEOUT_SECONDS} seconds. Try again in a moment.")
    elapsed_ms = (time.perf_counter() - start) * 1000

    return payload["answers"], elapsed_ms


# Raised when the user cancels while Decider is still thinking.
class Cancelled(Exception):
    pass


# The helper thread of the last request, if it may still be running.
# Cancelling stops US waiting, but the Decider server keeps working on that
# request and answers one request at a time. A new request sent now would
# queue behind it, and enough of them in a row would time out.
_last_helper = {"thread": None}


# Waits (cancellably) until a cancelled request has finished on the server.
def wait_for_server(cancel_signal):
    helper = _last_helper["thread"]
    while helper is not None and helper.is_alive():
        if cancel_signal.is_set():
            raise Cancelled()
        helper.join(0.1)


# Like ask_decider(), but it can be cancelled at any moment.
# A web request can't be stopped halfway, so it runs on its own helper
# thread, and this function waits for EITHER the answer OR the cancel
# signal (a threading.Event), checking 10 times a second. On cancel it
# raises Cancelled right away; the helper finishes on its own later and
# its answer is thrown away.
def ask_decider_or_cancel(state, questions, cancel_signal):
    wait_for_server(cancel_signal)
    outcome = {}

    def work():
        try:
            outcome["answer"] = ask_decider(state, questions)
        except Exception as error:
            outcome["error"] = error

    helper = threading.Thread(target=work, daemon=True)
    _last_helper["thread"] = helper
    helper.start()
    while helper.is_alive():
        if cancel_signal.is_set():
            raise Cancelled()
        helper.join(0.1)
    if cancel_signal.is_set():
        raise Cancelled()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["answer"]
