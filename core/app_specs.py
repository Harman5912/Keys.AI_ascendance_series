"""
core/app_specs.py — what a "dashboard" or "Python desktop app" means here.

`core/build_recipes.py` tells the coding agent what files a dashboard needs.
This module is the deterministic half: it turns a request into the concrete
labels and sample data a rendered application is built from, so the artifact
exists even when no model is available or the model will not call a tool.

A spec never invents a data source. The schema is a real SQLite table, the
sample rows say they are samples, and the labels come from the words in the
brief (a fleet request gets vehicles and fuel, a newsroom request gets sections
and reads). Where the brief names nothing recognisable, the generic spec is
used rather than pretending to know the domain.

Detection is regex on the request, in the same style as `build_recipes`, so it
is deterministic and testable with no model in the loop.
"""

from __future__ import annotations

import re

# ── Dashboards ────────────────────────────────────────────────────────────
#
# `categories` drive the seed rows and the category bars; `labels` are the
# things being counted (vehicles, sections, ...); `amount_unit` is what the
# left axis is measured in; `series_label` names the line chart.

DASHBOARD_SPECS: dict[str, dict] = {
    "fleet": {
        "detect": r"\b(fleet|vehicle|vehicles|truck|trucks|lorry|driver|"
                  r"drivers|mileage|fuel|trip|trips|logistics|haulage)\b",
        "title": "Fleet Operations",
        "subject": "vehicles",
        "categories": ["Fuel", "Maintenance", "Trips", "Tolls", "Insurance"],
        "labels": ["V-1204", "V-3371", "V-4410", "V-5527", "V-6088", "V-7712"],
        "amount_unit": "Cost",
        "amount_prefix": "£",
        "series_label": "Cost per day",
        "quantity_label": "Litres",
        "kpi_labels": ("Total cost", "Distance events", "Open issues",
                       "Active vehicles"),
        "table_head": ("Date", "Vehicle", "Category", "Litres", "Cost"),
        "statuses": ["open", "closed", "open", "closed", "overdue"],
    },
    "newsroom": {
        "detect": r"\b(newsroom|editorial|articles?|stories|story|reads?|"
                  r"subscribers?|publication|publishing|journalis\w*|"
                  r"news\\b|magazine)\b",
        "title": "Newsroom Analytics",
        "subject": "articles",
        "categories": ["World", "Business", "Culture", "Science", "Opinion"],
        "labels": ["World", "Business", "Culture", "Science", "Opinion",
                   "Sport"],
        "amount_unit": "Reads",
        "amount_prefix": "",
        "series_label": "Reads per day",
        "quantity_label": "Reads",
        "kpi_labels": ("Total reads", "Read events", "Open tasks",
                       "Sections live"),
        "table_head": ("Date", "Section", "Category", "Reads", "Revenue"),
        "statuses": ["open", "closed", "open", "closed", "open"],
    },
    "inventory": {
        "detect": r"\b(inventory|stock|warehouse|sku|skus|reorder|"
                  r"stock levels|goods|supplies)\b",
        "title": "Inventory Overview",
        "subject": "stock items",
        "categories": ["Electronics", "Hardware", "Packaging", "Consumables",
                       "Spares"],
        "labels": ["SKU-1042", "SKU-2210", "SKU-3390", "SKU-4481", "SKU-5502",
                   "SKU-6613"],
        "amount_unit": "Value",
        "amount_prefix": "£",
        "series_label": "Stock value per day",
        "quantity_label": "Units",
        "kpi_labels": ("Stock value", "Units moved", "Below reorder",
                       "Active SKUs"),
        "table_head": ("Date", "SKU", "Category", "Units", "Value"),
        "statuses": ["open", "closed", "open", "overdue", "closed"],
    },
    "sales": {
        "detect": r"\b(sales|revenue|orders|checkout|basket|ecommerce|"
                  r"e-?commerce|store metrics|conversion)\b",
        "title": "Sales Overview",
        "subject": "orders",
        "categories": ["Online", "In store", "Wholesale", "Returns"],
        "labels": ["Espresso", "Filter pack", "Subscription", "Gift set",
                   "Grinder", "Mug"],
        "amount_unit": "Revenue",
        "amount_prefix": "£",
        "series_label": "Revenue per day",
        "quantity_label": "Units",
        "kpi_labels": ("Revenue", "Units sold", "Open orders", "Products"),
        "table_head": ("Date", "Product", "Channel", "Units", "Revenue"),
        "statuses": ["open", "closed", "closed", "open", "closed"],
    },
    "generic": {
        "detect": r"",
        "title": "Operations Dashboard",
        "subject": "records",
        "categories": ["Planned", "Delivered", "Support", "Overheads",
                       "Other"],
        "labels": ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"],
        "amount_unit": "Value",
        "amount_prefix": "",
        "series_label": "Value per day",
        "quantity_label": "Count",
        "kpi_labels": ("Total value", "Records", "Open items", "Categories"),
        "table_head": ("Date", "Item", "Category", "Count", "Value"),
        "statuses": ["open", "closed", "open", "closed", "open"],
    },
}

DASHBOARD_ORDER = ("fleet", "newsroom", "inventory", "sales")


def pick_dashboard(brief: str) -> tuple[str, dict]:
    """(key, spec) for a dashboard request. `generic` when nothing matches."""
    text = brief or ""
    for key in DASHBOARD_ORDER:
        if re.search(DASHBOARD_SPECS[key]["detect"], text, re.I):
            return key, DASHBOARD_SPECS[key]
    return "generic", DASHBOARD_SPECS["generic"]


# ── Python desktop apps ───────────────────────────────────────────────────

DESKTOP_SPECS: dict[str, dict] = {
    "ledger": {
        "detect": r"\b(ledger|bookkeeping|book-keeping|expenses?|spending|"
                  r"transactions?|accounts?|receipts?|budget|finance)\b",
        "title": "Ledger",
        "entity_one": "entry",
        "entity_many": "entries",
        "name_label": "Description",
        "category_label": "Category",
        "quantity_label": "Qty",
        "amount_label": "Amount",
        "categories": ["Income", "Software", "Travel", "Office", "Meals",
                       "Utilities"],
        "samples": [
            ("Invoice 1042 — Meridian", "Income", 1, 2400.00),
            ("Rent — October", "Office", 1, -1450.00),
            ("Design software", "Software", 2, -64.00),
            ("Client lunch", "Meals", 1, -38.50),
            ("Train to Leeds", "Travel", 1, -112.40),
            ("Electricity", "Utilities", 1, -96.20),
        ],
        "total_mode": "sum_amount",
        "total_label": "Balance",
        "low_stock": False,
    },
    "inventory": {
        "detect": r"\b(inventory|stock|warehouse|shop stock|reorder|"
                  r"low[- ]stock|shop floor|spare parts)\b",
        "title": "Stock Control",
        "entity_one": "item",
        "entity_many": "items",
        "name_label": "Item",
        "category_label": "Category",
        "quantity_label": "On hand",
        "amount_label": "Unit cost",
        "categories": ["Hardware", "Packaging", "Consumables", "Spares",
                       "Tools"],
        "samples": [
            ("Hex bolts M8 (100)", "Hardware", 340, 12.40),
            ("Shipping boxes", "Packaging", 8, 1.15),
            ("Gloves (pair)", "Consumables", 24, 3.80),
            ("Drive belt", "Spares", 2, 46.00),
            ("Torque wrench", "Tools", 5, 89.00),
            ("Tape roll", "Packaging", 0, 2.20),
        ],
        "total_mode": "sum_value",
        "total_label": "Stock value",
        "low_stock": True,
    },
    "generic": {
        "detect": r"",
        "title": "Records",
        "entity_one": "record",
        "entity_many": "records",
        "name_label": "Name",
        "category_label": "Category",
        "quantity_label": "Qty",
        "amount_label": "Value",
        "categories": ["General", "Planned", "Done"],
        "samples": [
            ("First record", "General", 1, 10.00),
            ("Second record", "Planned", 2, 25.50),
            ("Third record", "Done", 1, 5.00),
        ],
        "total_mode": "sum_amount",
        "total_label": "Total",
        "low_stock": False,
    },
}

DESKTOP_ORDER = ("ledger", "inventory")


def pick_desktop(brief: str) -> tuple[str, dict]:
    """(key, spec) for a Python desktop request. `generic` when nothing matches."""
    text = brief or ""
    for key in DESKTOP_ORDER:
        if re.search(DESKTOP_SPECS[key]["detect"], text, re.I):
            return key, DESKTOP_SPECS[key]
    return "generic", DESKTOP_SPECS["generic"]


# ── shared content ────────────────────────────────────────────────────────

def project_name(brief: str, fallback: str = "App") -> str:
    """A human title from the request, e.g. 'fleet-operations dashboard'."""
    text = (brief or "").strip()
    match = re.search(
        r"\b(?:for|of|called|named)\s+([A-Z][\w&'’.\- ]{2,40})", text)
    if match:
        return match.group(1).strip().rstrip(".")
    match = re.search(r"\b(?:a|an|the)\s+([a-z][\w\- ]{3,40})", text, re.I)
    if match:
        words = match.group(1).split()
        keep = [w for w in words if w.lower().strip(",") not in
                ("dashboard", "app", "application", "with", "and", "that",
                 "which", "small", "simple")]
        if keep:
            return " ".join(keep[:4]).title()
    return fallback


def slugify(text: str, fallback: str = "app") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug[:40] or fallback
