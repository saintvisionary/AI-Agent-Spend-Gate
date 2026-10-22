# audit_chain.py
# Tamper-evident audit logs: every row carries a hash chain.
#
# Each row's row_hash is the SHA-256 of (the previous row's hash + this row's
# values). Change, delete or reorder any row, and every hash after it stops
# matching, so verify() points at the first row that was tampered with.
#
# The honest limit: someone who can rewrite the WHOLE file can recompute every
# hash. That's why the audit pack records the latest hash ("the head"): two
# packs from different days must agree on everything up to the older head.
# In production, the head would also be sent somewhere the writer can't edit
# (a SIEM, or a write-once S3 bucket).
#
# Standard library only.
import csv
import hashlib
import os
import time

GENESIS = "0" * 64   # the "previous hash" of the very first row


def row_hash(previous_hash, values):
    text = previous_hash + "|" + "|".join(str(value) for value in values)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Reads a log's rows (without the header). Returns [] if there's no log yet.
def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return rows[1:]


def last_hash(path):
    rows = read_rows(path)
    if not rows:
        return GENESIS
    return rows[-1][-1]


# Appends one row, chained to the row before it.
# columns: the column names WITHOUT row_hash (it's added here).
def append_row(path, columns, values):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    header = columns + ["row_hash"]
    set_aside_if_different(path, header)
    new_file = not os.path.exists(path)
    chained = row_hash(last_hash(path), values)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(header)
        writer.writerow(list(values) + [chained])


# A log written by an older version (different columns) is renamed, not
# mixed in or deleted. Old rows are kept as they were.
def set_aside_if_different(path, header):
    if not os.path.exists(path):
        return
    with open(path, newline="", encoding="utf-8") as f:
        first_line = f.readline().strip()
    if first_line != ",".join(header):
        os.replace(path, path.replace(".csv", f"_old_{int(time.time())}.csv"))


# Recomputes the whole chain.
# Returns (ok, rows_checked, message, head_hash).
def verify(path):
    rows = read_rows(path)
    previous = GENESIS
    for number, row in enumerate(rows, start=1):
        values, stored = row[:-1], row[-1]
        expected = row_hash(previous, values)
        if stored != expected:
            return False, number - 1, f"row {number} doesn't match the chain (edited, deleted or moved)", previous
        previous = stored
    return True, len(rows), f"all {len(rows)} rows match the chain", previous
