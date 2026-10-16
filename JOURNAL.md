# Build Journal

A record of the problems I hit while building **AI Agent Spend Gate**, what caused them, and how I fixed them. I'm learning Python through this project, so mistakes are part of the record.

- **Problems and fixes:** bugs and wrong behavior in the code
- **Design decisions:** choices I made, the options I considered, and why

---

## Problems and fixes

<!--
Copy this template for each new entry. Newest entries go at the top.

### YYYY-MM-DD · Short title
- **Problem:** what I was trying to do and what went wrong
- **What I saw:** the exact error message or wrong output
- **Cause:** why it happened
- **Fix:** what I changed
- **What I learned:** the concept behind it
-->

### 2026-10-17 · "nan" as the amount was APPROVED
- **Problem:** while adding typed input, I tested what Python accepts as a number. Typing `nan` as the amount got the purchase approved.
- **What I saw:** `check_request("Staples", "office supplies", float("nan"))` returned `('APPROVED', 'within policy')`. `inf` returned `NEEDS APPROVAL`.
- **Cause:** `float("nan")` and `float("inf")` are valid Python floats, so they passed the "is it a number" check. Every comparison with NaN is False, so `nan <= 0` and `nan > 500` were both False. The request fell through every rule to the approve line.
- **Fix:** added Rule 0b, which uses `math.isfinite()` to block NaN and infinity before any amount comparison.
- **What I learned:** "is it a number" and "is it a valid amount" are different checks. A deny-by-default design still fails if a value can make every block rule come back False.

### 2026-10-16 · Text instead of a number would crash the guard
- **Problem:** passing the amount as text (`"86"` instead of `86`) would crash `check_request()`.
- **What I saw:** `TypeError: '<=' not supported between instances of 'str' and 'int'`
- **Cause:** Python can't compare text to a number. The first rule, `amount <= 0`, assumed the amount was always a number.
- **Fix:** added Rule 0a, which uses `isinstance()` to check that the amount is a number before any other rule runs. Bad input is now `BLOCKED` with a reason instead of crashing.
- **What I learned:** validate the type of input before using it. A crash in a security control is a failure too, because nothing gets decided or recorded.
---

## Design decisions

<!--
### YYYY-MM-DD · Decision title
- **Decision:** what I had to choose
- **Options:** what I considered
- **Chose:** what I picked
- **Why:** the reasoning, including the tradeoff
-->

### 2026-10-16 · Block rules run before approve rules
- **Decision:** what order to check the rules in.
- **Options:** (1) check the amount limit first; (2) run every rule that can block before anything that can approve.
- **Chose:** option 2.
- **Why:** if the amount check ran first, a $900 gift card request would come back `NEEDS APPROVAL` and a human might approve something the policy should never allow. With blocking rules first, the only way to reach `APPROVED` is to pass every check.

### 2026-10-16 · Exact vendor matching (fail closed)
- **Decision:** whether `"staples"` should match `"Staples"`.
- **Options:** (1) ignore capitalization; (2) require an exact match.
- **Chose:** exact match for now.
- **Why:** an unexpected value is denied, never allowed. The tradeoff is that a legitimate request with different capitalization gets blocked. That's safer than the alternative, and it can be handled later by cleaning up input before the check.

### 2026-10-16 · Deciding and printing are separate functions
- **Decision:** whether `check_request()` should print its own result.
- **Options:** (1) one function that decides and prints; (2) `check_request()` only returns a decision, and `show_decision()` prints it.
- **Chose:** option 2.
- **Why:** the decision can be reused anywhere, such as a log or another program, without touching the rules. It also makes the rules easier to test.
