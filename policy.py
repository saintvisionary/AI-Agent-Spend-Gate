# policy.py
# Loads and saves the purchasing policy (policy.json).
#
# Where it sits: the Spend Gate rules (guard.py) and the budgets (ledger.py)
# read the policy from here every time they decide. Only policy_admin.py
# changes it, and only for a signed-in person with the right role. The agent
# has no tool that reaches this file, so it can't change its own limits.
#
# Important: the rest of the code keeps references to the lists and dicts
# inside POLICY (for example guard.APPROVED_VENDORS is the same list). So
# changes must edit them IN PLACE (append, remove, update), never replace them.
import copy
import json
import os

POLICY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy.json")

# Used if policy.json is missing or broken. Strict on purpose: if the policy
# can't be read, the gate falls back to a small, safe policy, never an open one.
DEFAULTS = {
    "allowed_categories": ["office supplies"],
    "approved_vendors": [],
    "approval_over": 500,
    "department_budgets": {"operations": 0, "marketing": 0},
    "reorder": {},
    "roster": {},
}

REQUIRED_TYPES = {
    "allowed_categories": list,
    "approved_vendors": list,
    "approval_over": (int, float),
    "department_budgets": dict,
    "reorder": dict,
    "roster": dict,
}


# Reads policy.json. Returns the policy and a warning (None if it loaded fine).
def load():
    try:
        with open(POLICY_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as error:
        return copy.deepcopy(DEFAULTS), f"policy.json could not be read ({error}); using the safe defaults"

    for key in REQUIRED_TYPES:
        if not isinstance(data.get(key), REQUIRED_TYPES[key]):
            return copy.deepcopy(DEFAULTS), f"policy.json has a missing or wrong '{key}'; using the safe defaults"
    return data, None


# Writes the policy back. It writes a temporary file first, then swaps it in,
# so a crash halfway through can't leave a half-written policy.json.
def save():
    temporary = POLICY_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(POLICY, f, indent=2)
    os.replace(temporary, POLICY_FILE)


POLICY, LOAD_WARNING = load()
if LOAD_WARNING:
    print(f"WARNING: {LOAD_WARNING}")
