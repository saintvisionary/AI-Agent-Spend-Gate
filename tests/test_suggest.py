# tests/test_suggest.py
# Proves the suggester learns only from evidence that's hard to fake:
# several people, over time, who agree. And that it flags split orders.
#
#     python -m unittest discover tests
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import suggest

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "sample_logs", "human_decisions.csv")


# One fake log row, with only the columns the suggester reads.
def row(time, user, reason, amount="999.96", vendor="Dell", department="information technology",
        category="it hardware", item="monitors"):
    return {"time": time, "user": user, "department": department, "vendor": vendor,
            "category": category, "item": item, "amount": amount, "reason": reason}


# Five approvals, two people, spread over four weeks: enough evidence.
def good_history():
    return [row("2026-09-01 09:00:00", "Rick Sullivan", suggest.HUMAN_YES),
            row("2026-09-08 09:00:00", "Tyler Bynum", suggest.HUMAN_YES),
            row("2026-09-15 09:00:00", "Rick Sullivan", suggest.HUMAN_YES),
            row("2026-09-22 09:00:00", "Tyler Bynum", suggest.HUMAN_YES),
            row("2026-09-29 09:00:00", "Rick Sullivan", suggest.HUMAN_YES)]


def evidence(rows):
    groups = suggest.group_human_decisions(rows)
    return suggest.check_evidence(groups[("information technology", "Dell", "it hardware")])


class SuggestTests(unittest.TestCase):
    def test_enough_evidence_is_suggested(self):
        self.assertEqual(evidence(good_history()), (True, ""))

    def test_one_person_cant_train_it(self):
        rows = good_history()
        for r in rows:
            r["user"] = "Kim Alvarez"
        ok, why = evidence(rows)
        self.assertFalse(ok)
        self.assertIn("1 approver", why)

    def test_a_burst_in_one_day_doesnt_count(self):
        rows = good_history()
        for r in rows:
            r["time"] = "2026-10-06" + r["time"][10:]
        ok, why = evidence(rows)
        self.assertFalse(ok)
        self.assertIn("needs 14", why)

    def test_rows_in_any_order_count_the_same(self):
        rows = good_history()
        rows.reverse()
        self.assertEqual(evidence(rows), (True, ""))

    def test_one_rejection_holds_it(self):
        rows = good_history() + [row("2026-10-01 09:00:00", "Tyler Bynum", suggest.HUMAN_NO)]
        ok, why = evidence(rows)
        self.assertFalse(ok)
        self.assertIn("disagree", why)

    def test_rule_approvals_are_not_memory(self):
        rows = good_history()
        for r in rows:
            r["reason"] = suggest.RULE_YES
        self.assertEqual(suggest.group_human_decisions(rows), {})

    def test_split_orders_are_flagged(self):
        rows = []
        for minute in ["10", "20", "30"]:
            rows.append(row(f"2026-10-09 09:{minute}:00", "Ruth Okafor", suggest.RULE_YES, amount="472.41",
                            vendor="Office Depot", department="operations", item="printer paper"))
        flags = suggest.find_split_orders(rows, 500.0)
        self.assertEqual(len(flags), 1)

    def test_bad_amounts_are_ignored(self):
        for text in ["", "nan", "-5", "abc"]:
            self.assertIsNone(suggest.to_amount(text))

    def test_sample_log_has_every_pattern(self):
        rows = suggest.load_decisions(SAMPLE)
        groups = suggest.group_human_decisions(rows)
        suggested = []
        for key, group in groups.items():
            if suggest.check_evidence(group)[0]:
                suggested.append(key)
        self.assertEqual(suggested, [("information technology", "Dell", "it hardware")])
        self.assertEqual(len(suggest.find_split_orders(rows, 500.0)), 1)


if __name__ == "__main__":
    unittest.main()
