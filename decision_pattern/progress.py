# progress.py
# A progress bar for slow waits, like a Decider 2B check on a laptop CPU.
#
# A model call can't report how far along it is, so the bar estimates:
# it fills over the time the LAST call took, and stops at 95% until the
# answer really arrives. It never claims to be done before it is.
#
# A background thread draws the bar while the main thread waits for the
# answer. Standard library only.
import sys
import threading
import time

BAR_WIDTH = 20


# Starts drawing the bar. Returns a "handle" to pass to stop_progress().
def start_progress(label, expected_seconds):
    stop_signal = threading.Event()
    # Only animate in a real terminal. When output goes to a file or a
    # pipe, \r tricks make a mess, so just print the label once.
    if not sys.stdout.isatty():
        print(f"{label}...")
        return {"stop": stop_signal, "thread": None}

    thread = threading.Thread(target=draw, args=(label, expected_seconds, stop_signal), daemon=True)
    thread.start()
    return {"stop": stop_signal, "thread": thread}


# Stops the bar and clears its line, so the next print starts clean.
def stop_progress(handle):
    handle["stop"].set()
    if handle["thread"] is not None:
        handle["thread"].join()


# Runs in the background thread: redraws the bar 5 times a second.
def draw(label, expected_seconds, stop_signal):
    started = time.perf_counter()
    line = ""
    while not stop_signal.is_set():
        elapsed = time.perf_counter() - started
        fraction = min(elapsed / expected_seconds, 0.95)
        filled = int(fraction * BAR_WIDTH)
        bar = "#" * filled + "-" * (BAR_WIDTH - filled)
        line = f"{label}  [{bar}]  {elapsed:.0f}s / ~{expected_seconds:.0f}s"
        # \r moves back to the start of the line, so the bar redraws in place.
        sys.stdout.write("\r" + line)
        sys.stdout.flush()
        stop_signal.wait(0.2)
    # Erase the bar: spaces over it, then back to the start.
    sys.stdout.write("\r" + " " * len(line) + "\r")
    sys.stdout.flush()
