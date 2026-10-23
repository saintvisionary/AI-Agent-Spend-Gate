# catalog.py
# What the company keeps on the shelf, which departments use each item,
# and today's market data from each vendor.
#
# The vendors are real companies, used as realistic examples. The prices,
# delivery times and stock levels are made up: they are NOT quotes from these
# companies, and none of them is affiliated with or endorses this project.
#
# Where it sits: the agent's tools read this (check_inventory, get_price_quotes),
# and place_order checks against it (catalog check: entitlement, real category,
# quoted price). Reorder points and order quantities are policy, not stock, so
# they live in policy.json, where a department leader can change them in the app.

DEPARTMENTS = [
    "operations",
    "marketing",
    "legal",
    "security",
    "finance and accounting",
    "research and development",
    "information technology",
    "human resources",
]

# What's on the shelf.
#   on_hand   how many there are now
#   unit      what one "1" means
#   category  the purchase category the policy checks
#   used_by   which departments use it. This is the entitlement: a department
#             can only see and order the items it uses.
#   note      free text from the shared warehouse feed (anyone can edit it,
#             which is how the "injection" scenario gets in)
INVENTORY = {
    "printer paper": {"on_hand": 4, "unit": "case of 10 reams", "category": "office supplies",
                      "used_by": DEPARTMENTS, "note": ""},
    "blue pens": {"on_hand": 30, "unit": "box of 12", "category": "office supplies",
                  "used_by": DEPARTMENTS, "note": ""},
    "file folders": {"on_hand": 3, "unit": "box of 100", "category": "office supplies",
                     "used_by": ["legal", "finance and accounting", "human resources"], "note": ""},
    "receipt printer rolls": {"on_hand": 2, "unit": "case of 50", "category": "office supplies",
                              "used_by": ["finance and accounting", "operations"], "note": ""},
    "laptops": {"on_hand": 3, "unit": "business laptop", "category": "it hardware",
                "used_by": ["information technology", "research and development", "security"], "note": ""},
    "monitors": {"on_hand": 9, "unit": "27-inch monitor", "category": "it hardware",
                 "used_by": ["information technology", "research and development"], "note": ""},
    "usb security keys": {"on_hand": 12, "unit": "FIDO2 security key", "category": "security supplies",
                          "used_by": ["security", "information technology"], "note": ""},
    "badge card stock": {"on_hand": 1, "unit": "pack of 500 PVC cards", "category": "security supplies",
                         "used_by": ["human resources", "security"], "note": ""},
    "office suite licenses": {"on_hand": 8, "unit": "user license per year", "category": "software",
                              "used_by": ["information technology"], "note": ""},
    "case law database seats": {"on_hand": 2, "unit": "seat per month", "category": "legal services",
                                "used_by": ["legal"], "note": ""},
    "lab gloves": {"on_hand": 5, "unit": "box of 100 nitrile", "category": "lab supplies",
                   "used_by": ["research and development"], "note": ""},
    "3d printer filament": {"on_hand": 6, "unit": "1 kg spool", "category": "lab supplies",
                            "used_by": ["research and development", "marketing"], "note": ""},
    "safety vests": {"on_hand": 4, "unit": "high-visibility vest", "category": "safety equipment",
                     "used_by": ["security", "operations"], "note": ""},
    "compliance training seats": {"on_hand": 0, "unit": "course seat", "category": "training",
                                  "used_by": ["human resources", "legal"], "note": ""},
    "trade show banners": {"on_hand": 1, "unit": "8 ft banner", "category": "advertising",
                           "used_by": ["marketing"], "note": ""},
}

# Today's market data: price per unit, delivery time and stock at each vendor.
# Amazon Business and Newegg are often the cheapest, but they're NOT on this
# company's approved vendor list (policy.json). The market doesn't know your
# policy; the Spend Gate does.
PRICE_QUOTES = {
    "printer paper": {
        "Office Depot": {"price": 52.49, "delivery_days": 3, "in_stock": True},
        "Staples": {"price": 54.99, "delivery_days": 1, "in_stock": True},
        "Amazon Business": {"price": 47.99, "delivery_days": 1, "in_stock": True},
    },
    "blue pens": {
        "Office Depot": {"price": 9.99, "delivery_days": 3, "in_stock": False},
        "Staples": {"price": 11.29, "delivery_days": 2, "in_stock": True},
        "Amazon Business": {"price": 8.49, "delivery_days": 1, "in_stock": True},
    },
    "file folders": {
        "Office Depot": {"price": 18.99, "delivery_days": 3, "in_stock": True},
        "Staples": {"price": 21.49, "delivery_days": 1, "in_stock": True},
    },
    "receipt printer rolls": {
        "Office Depot": {"price": 44.99, "delivery_days": 3, "in_stock": True},
        "Staples": {"price": 47.99, "delivery_days": 1, "in_stock": True},
    },
    "laptops": {
        "Dell": {"price": 1349.00, "delivery_days": 5, "in_stock": True},
        "CDW": {"price": 1389.00, "delivery_days": 2, "in_stock": True},
        "Newegg": {"price": 1199.00, "delivery_days": 6, "in_stock": True},
    },
    "monitors": {
        "Dell": {"price": 249.99, "delivery_days": 5, "in_stock": True},
        "CDW": {"price": 264.99, "delivery_days": 2, "in_stock": True},
        "Newegg": {"price": 219.99, "delivery_days": 4, "in_stock": True},
    },
    "usb security keys": {
        "Yubico": {"price": 55.00, "delivery_days": 3, "in_stock": True},
        "CDW": {"price": 58.00, "delivery_days": 2, "in_stock": True},
    },
    "badge card stock": {
        "ID Wholesaler": {"price": 89.00, "delivery_days": 3, "in_stock": True},
        "Staples": {"price": 104.99, "delivery_days": 2, "in_stock": True},
    },
    "office suite licenses": {
        "Microsoft": {"price": 144.00, "delivery_days": 1, "in_stock": True},
        "CDW": {"price": 151.20, "delivery_days": 1, "in_stock": True},
    },
    "case law database seats": {
        "LexisNexis": {"price": 195.00, "delivery_days": 1, "in_stock": True},
        "Thomson Reuters": {"price": 210.00, "delivery_days": 1, "in_stock": True},
    },
    "lab gloves": {
        "VWR": {"price": 15.95, "delivery_days": 3, "in_stock": True},
        "Fisher Scientific": {"price": 16.40, "delivery_days": 2, "in_stock": True},
        "Amazon Business": {"price": 12.99, "delivery_days": 1, "in_stock": True},
    },
    "3d printer filament": {
        "MatterHackers": {"price": 28.99, "delivery_days": 3, "in_stock": True},
        "Amazon Business": {"price": 22.99, "delivery_days": 1, "in_stock": True},
    },
    "safety vests": {
        "Grainger": {"price": 14.25, "delivery_days": 2, "in_stock": True},
        "Uline": {"price": 12.50, "delivery_days": 3, "in_stock": False},
    },
    "compliance training seats": {
        "Skillsoft": {"price": 45.00, "delivery_days": 1, "in_stock": True},
    },
    "trade show banners": {
        "Vistaprint": {"price": 349.00, "delivery_days": 4, "in_stock": True},
    },
}

# What each category means. Decider 2B uses these descriptions to judge
# what an item REALLY is, whatever the agent labeled it. The cash-like ones
# are here so Decider can name them, not because they can be bought.
CATEGORY_DESCRIPTIONS = {
    "office supplies": "paper, pens, folders, printer rolls and similar desk supplies",
    "advertising": "ads, banners, promotions, flyers or marketing services",
    "it hardware": "laptops, monitors, keyboards and other computer equipment",
    "software": "software licenses, seats and subscriptions for applications",
    "legal services": "legal research databases, legal services and their seats",
    "lab supplies": "lab gloves, filament, chemicals and research materials",
    "safety equipment": "safety vests, helmets and protective gear",
    "security supplies": "security keys, badge stock, locks and access-control supplies",
    "training": "courses, training seats and certifications",
    "gift cards": "gift cards, prepaid cards or anything that works like cash",
}


# Does this department use this item? (The entitlement check.)
def department_uses(department, item):
    if item not in INVENTORY:
        return False
    return department in INVENTORY[item]["used_by"]
