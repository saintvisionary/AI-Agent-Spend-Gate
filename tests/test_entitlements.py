# tests/test_entitlements.py
# Proves a department can only see and order the items it uses, and that
# the catalog's real category beats whatever label the LLM sends.
#
#     python -m unittest discover tests
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent
import catalog
import ledger


# Stands in for the screen, so the tests run quietly.
class QuietUI:
    def __getattr__(self, name):
        return lambda *args, **kwargs: False


class EntitlementTests(unittest.TestCase):
    def setUp(self):
        self.real_log, self.real_ui = ledger.AUDIT_LOG, agent.UI
        ledger.AUDIT_LOG = os.path.join(tempfile.mkdtemp(), "audit_log.csv")
        agent.UI = QuietUI()
        self.saved_session = dict(agent.SESSION)

    def tearDown(self):
        ledger.AUDIT_LOG, agent.UI = self.real_log, self.real_ui
        agent.SESSION.clear()
        agent.SESSION.update(self.saved_session)

    def order(self, department, item, vendor, price, category, quantity=1):
        agent.SESSION.update({"user": "Test User", "department": department, "role": "member"})
        return agent.place_order(vendor=vendor, item=item, quantity=quantity, unit_price=price, category=category)

    def test_inventory_lists_only_the_departments_items(self):
        agent.SESSION["department"] = "marketing"
        text = agent.inventory_text()
        self.assertIn("trade show banners", text)
        self.assertNotIn("laptops", text)
        self.assertNotIn("case law database seats", text)

    def test_department_cannot_order_an_item_it_does_not_use(self):
        result = self.order("marketing", "laptops", "Dell", 1349.00, "it hardware")
        self.assertIn("isn't entitled", result)

    def test_department_can_order_its_own_item(self):
        result = self.order("information technology", "monitors", "Dell", 249.99, "it hardware")
        self.assertIn("Order placed", result)

    def test_shared_items_work_for_every_department_that_uses_them(self):
        for department in catalog.INVENTORY["badge card stock"]["used_by"]:
            result = self.order(department, "badge card stock", "ID Wholesaler", 89.00, "security supplies")
            self.assertIn("Order placed", result, department)

    def test_the_catalog_category_beats_the_llms_label(self):
        result = self.order("information technology", "monitors", "Dell", 249.99, "office supplies")
        self.assertIn("is 'it hardware', not 'office supplies'", result)

    def test_unapproved_vendor_is_still_blocked_by_the_rules(self):
        result = self.order("information technology", "monitors", "Newegg", 219.99, "it hardware")
        self.assertIn("not approved", result)

    def test_every_department_has_a_budget_and_a_leader(self):
        import policy
        leaders = {}
        for name in policy.POLICY["roster"]:
            entry = policy.POLICY["roster"][name]
            # A leader, or the owner when they also lead a department.
            if entry.get("department"):
                leaders[entry["department"]] = name
        for department in catalog.DEPARTMENTS:
            self.assertIn(department, policy.POLICY["department_budgets"])
            self.assertIn(department, leaders)

    def test_every_item_has_quotes_and_reorder_settings(self):
        import policy
        for item in catalog.INVENTORY:
            self.assertIn(item, catalog.PRICE_QUOTES)
            self.assertIn(item, policy.POLICY["reorder"])
            self.assertIn(catalog.INVENTORY[item]["category"], policy.POLICY["allowed_categories"])


if __name__ == "__main__":
    unittest.main()
