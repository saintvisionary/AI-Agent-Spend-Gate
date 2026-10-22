# start.py
# One command to set up and run everything:
#
#     python start.py              the full-screen app (app.py)
#     python start.py --cli        the simple terminal version (agent.py)
#     python start.py restock      one scenario, then exit
#     python start.py --check      report what's ready and what's missing (changes nothing)
#
# Or double-click "Start Spend Gate.bat" (Windows) / start.command (Mac).
#
# It works with any Python 3.10+ and needs nothing installed first. It does
# not need the virtual environment to be activated, so PowerShell's script
# policy never gets in the way.
#
# Steps: check Python -> create .venv and install packages -> pick the LLM
# (Bedrock if AWS credentials exist, otherwise local Ollama) -> start
# Decider 2B in the background -> run the agent -> stop Decider afterwards.
#
# Standard library only, because it runs before anything is installed.
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

PROJECT = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(PROJECT, ".venv")
REQUIREMENTS = os.path.join(PROJECT, "requirements.txt")
INSTALLED_MARKER = os.path.join(VENV, "requirements.sha256")
LOG_DIR = os.path.join(PROJECT, "logs")

DECIDER_MODEL = "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"
DECIDER_PORT = 8099
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")


def say(text):
    print(f"[start] {text}", flush=True)


def stop(text):
    print(f"\n[start] STOPPED: {text}")
    sys.exit(1)


# Paths inside the venv are different on Windows (Scripts\) and Mac/Linux (bin/).
def venv_file(name):
    if os.name == "nt":
        return os.path.join(VENV, "Scripts", name + ".exe")
    return os.path.join(VENV, "bin", name)


# Is something listening on this port on this computer?
def port_open(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------
# STEP 1-2: PYTHON AND PACKAGES
# ---------------------------------------------------------------

def check_python():
    if sys.version_info < (3, 10):
        stop(f"Python 3.10 or newer is needed; this is {sys.version.split()[0]}.")
    say(f"Python {sys.version.split()[0]}")


# Fingerprint of requirements.txt, so packages are only reinstalled when it changes.
def requirements_hash():
    with open(REQUIREMENTS, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def install_packages():
    if not os.path.exists(venv_file("python")):
        say("Creating the virtual environment (.venv)...")
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)

    if os.path.exists(INSTALLED_MARKER):
        with open(INSTALLED_MARKER) as f:
            if f.read() == requirements_hash():
                say("Packages already installed")
                return

    say("Installing packages. The first time takes several minutes (PyTorch is large)...")
    result = subprocess.run([venv_file("python"), "-m", "pip", "install", "-r", REQUIREMENTS])
    if result.returncode != 0:
        stop("Package install failed. Check your internet connection and run python start.py again.")
    with open(INSTALLED_MARKER, "w") as f:
        f.write(requirements_hash())


# ---------------------------------------------------------------
# STEP 3: THE LLM
# ---------------------------------------------------------------

# Bedrock if AWS credentials are set up, otherwise Ollama.
# LLM_PROVIDER=bedrock or LLM_PROVIDER=ollama overrides the choice.
def pick_llm():
    choice = os.environ.get("LLM_PROVIDER")
    if choice is None:
        check = "import boto3; print(boto3.Session().get_credentials() is not None)"
        found = subprocess.run([venv_file("python"), "-c", check], capture_output=True, text=True)
        if found.stdout.strip() == "True":
            choice = "bedrock"
        else:
            choice = "ollama"
            say("No AWS credentials found, so using a local model through Ollama")
    if choice == "ollama":
        prepare_ollama()
    say(f"LLM: {choice}")
    return choice


def prepare_ollama():
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as response:
            models = json.load(response).get("models", [])
    except OSError:
        stop("Ollama isn't running. Install it from https://ollama.com (free), open it, "
             "then run python start.py again.")
    names = [model.get("name", "") for model in models]
    if OLLAMA_MODEL in names:
        say(f"Ollama model {OLLAMA_MODEL} is ready")
        return
    say(f"Downloading {OLLAMA_MODEL} for Ollama (about 2 GB, one time)...")
    pull_ollama_model()


# Asks Ollama to download the model and prints progress as it arrives.
def pull_ollama_model():
    body = json.dumps({"model": OLLAMA_MODEL}).encode()
    request = urllib.request.Request(f"{OLLAMA_URL}/api/pull", data=body, method="POST")
    last_percent = -10
    with urllib.request.urlopen(request) as response:
        for line in response:
            update = json.loads(line)
            if "error" in update:
                stop(f"Ollama couldn't download {OLLAMA_MODEL}: {update['error']}")
            if update.get("total") and update.get("completed"):
                percent = int(100 * update["completed"] / update["total"])
                if percent >= last_percent + 10:
                    say(f"  {percent}%")
                    last_percent = percent
    say(f"Ollama model {OLLAMA_MODEL} is ready")


# ---------------------------------------------------------------
# STEP 4: DECIDER 2B
# ---------------------------------------------------------------

# Starts the Decider server in the background unless one is already running.
# Returns the process if this script started it (so it can be stopped later).
def start_decider():
    if port_open(DECIDER_PORT):
        say(f"Decider 2B is already running on port {DECIDER_PORT}")
        return None

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, "decider.log")
    say("Starting Decider 2B (needs about 6 GB of free RAM). The first run downloads the model...")
    log = open(log_path, "w", encoding="utf-8")
    command = [venv_file("strands-decider"), "serve", DECIDER_MODEL,
               "--port", str(DECIDER_PORT), "--device", "cpu"]
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=PROJECT)
    wait_for_decider(process, log_path)
    return process


def wait_for_decider(process, log_path):
    started = time.time()
    checks = 0
    while not port_open(DECIDER_PORT):
        if process.poll() is not None:
            stop(f"Decider 2B exited during startup. See {log_path} for the reason.")
        time.sleep(5)
        checks = checks + 1
        if checks % 6 == 0:  # every 30 seconds
            say(f"  still starting ({int(time.time() - started)}s). Progress is in {log_path}")
    say(f"Decider 2B is ready ({int(time.time() - started)}s)")


# ---------------------------------------------------------------
# STEP 5-6: RUN, THEN CLEAN UP
# ---------------------------------------------------------------

# No arguments: the full-screen app (app.py).
# --cli: the simple terminal version (agent.py).
# A scenario or request: run it once in the simple version and exit.
def run_agent(llm):
    env = dict(os.environ, LLM_PROVIDER=llm, OLLAMA_MODEL=OLLAMA_MODEL)
    args = sys.argv[1:]
    if not args:
        say("Starting the app\n")
        command = [venv_file("python"), os.path.join(PROJECT, "app.py")]
    else:
        if args[0] == "--cli":
            args = args[1:]
        say("Starting the agent\n")
        command = [venv_file("python"), os.path.join(PROJECT, "agent.py")] + args
    return subprocess.run(command, env=env, cwd=PROJECT).returncode


# ---------------------------------------------------------------
# --check: REPORT WHAT'S READY, CHANGE NOTHING
# ---------------------------------------------------------------

# Free memory in GB, or None if this computer won't say.
def free_ram_gb():
    try:
        if os.name == "nt":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.ullAvailPhys / 1024 ** 3
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024 ** 3
    except (AttributeError, OSError, ValueError):
        return None


def ollama_status():
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as response:
            names = [model.get("name", "") for model in json.load(response).get("models", [])]
    except OSError:
        return False, "not running (install from https://ollama.com, then open it)"
    if OLLAMA_MODEL in names:
        return True, f"running, {OLLAMA_MODEL} downloaded"
    return True, f"running; {OLLAMA_MODEL} will be downloaded on first start (about 2 GB)"


# Prints one line per item: OK, or what's missing and how to fix it.
def check_setup():
    ready = True
    print("AI Agent Spend Gate: setup check (nothing is changed)\n")

    version = sys.version.split()[0]
    python_ok = sys.version_info >= (3, 10)
    print(f"  [{'OK' if python_ok else '!!'}] Python {version}" + ("" if python_ok else " (3.10 or newer needed)"))
    ready = ready and python_ok

    installed = os.path.exists(INSTALLED_MARKER)
    if installed:
        with open(INSTALLED_MARKER) as f:
            installed = f.read() == requirements_hash()
    print(f"  [{'OK' if installed else '..'}] Packages" + (" installed" if installed
          else ": not installed yet (the first start installs them; several minutes)"))

    aws = False
    if os.path.exists(venv_file("python")):
        check = "import boto3; print(boto3.Session().get_credentials() is not None)"
        found = subprocess.run([venv_file("python"), "-c", check], capture_output=True, text=True)
        aws = found.stdout.strip() == "True"
    ollama_ok, ollama_text = ollama_status()
    print(f"  [{'OK' if aws else '..'}] AWS credentials for Bedrock: " + ("found" if aws else "not found (fine if you use Ollama)"))
    print(f"  [{'OK' if ollama_ok else '..'}] Ollama: {ollama_text}")
    if not aws and not ollama_ok:
        print("  [!!] No LLM available: install Ollama (free) or set up AWS credentials")
        ready = False

    decider = port_open(DECIDER_PORT)
    print(f"  [OK] Decider 2B: " + ("running" if decider else "not running (start.py starts it for you)"))

    ram = free_ram_gb()
    if ram is not None:
        enough = decider or ram >= 6
        print(f"  [{'OK' if enough else '!!'}] Free memory: {ram:.1f} GB" +
              ("" if enough else " (Decider 2B needs about 6 GB; close other apps first)"))

    print("\nReady to start." if ready else "\nNot ready yet: fix the [!!] items above.")
    return ready


def main():
    if "--check" in sys.argv:
        sys.exit(0 if check_setup() else 1)
    check_python()
    install_packages()
    llm = pick_llm()
    decider = start_decider()
    try:
        code = run_agent(llm)
    except KeyboardInterrupt:
        code = 0
    finally:
        # Only stop Decider if this script started it.
        if decider is not None:
            say("Stopping Decider 2B")
            decider.terminate()
    sys.exit(code)


if __name__ == "__main__":
    main()
