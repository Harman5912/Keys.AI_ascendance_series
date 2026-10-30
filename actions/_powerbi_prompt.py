"""actions/_powerbi_prompt.py — Power BI design prompt builder.

Kept in a separate module so the multi-line JSON schema in the prompt does not
make actions/file_processor.py harder to keep syntactically valid.
"""

from __future__ import annotations


def _powerbi_prompt(title: str, instruction: str) -> str:
    """Return the Gemini prompt used to design a Power BI report artefact set."""
    return (
        "You are a senior Power BI report designer. Design a complete, professional"
        "\nPower BI report for the following subject."
        "\n\nSubject: "
        + (instruction or title)
        + "\n\nReturn ONLY a single JSON object with exactly these top-level keys:"
        "\n{"
        '\n  "report_title": "...",'
        '\n  "subject_overview": "1-2 sentence business context",'
        '\n  "theme": {'
        '\n    "name": "...",'
        '\n    "primary": "#1F497D",'
        '\n    "accent": "#4472C4",'
        '\n    "background": "#FFFFFF",'
        '\n    "text": "#262626",'
        '\n    "good": "#107C10",'
        '\n    "neutral": "#767676",'
        '\n    "bad": "#C00000"'
        "\n  },"
        '\n  "pages": ['
        "\n    {"
        '\n      "name": "Executive Summary",'
        '\n      "description": "...",'
        '\n      "filters": ["..."],'
        '\n      "visuals": ['
        "\n        {"
        '\n          "type": "card",'
        '\n          "title": "...",'
        '\n          "measure": "...",'
        '\n          "format": "...",'
        '\n          "category": "KPI"'
        "\n        },"
        "\n        {"
        '\n          "type": "barchart",'
        '\n          "title": "...",'
        '\n          "axis": "...",'
        '\n          "values": ["..."],'
        '\n          "sort_by": "...",'
        '\n          "category": "Analysis"'
        "\n        },"
        "\n        {"
        '\n          "type": "linechart",'
        '\n          "title": "...",'
        '\n          "axis": "...",'
        '\n          "values": ["..."],'
        '\n          "category": "Trend"'
        "\n        },"
        "\n        {"
        '\n          "type": "matrixtable",'
        '\n          "title": "...",'
        '\n          "rows": ["..."],'
        '\n          "values": ["..."],'
        '\n          "category": "Detail"'
        "\n        },"
        "\n        {"
        '\n          "type": "slicer",'
        '\n          "title": "...",'
        '\n          "field": "...",'
        '\n          "category": "Filter"'
        "\n        }"
        "\n      ],"
        '\n      "interactions": {'
        '\n        "cross_filtering": true,'
        '\n        "highlighting": true'
        "\n      }"
        "\n    }"
        "\n  ],"
        '\n  "semantic_model": {'
        '\n    "tables": ['
        "\n      {"
        '\n        "name": "...",'
        '\n        "description": "...",'
        '\n        "columns": ['
        "\n          {"
        '\n            "name": "...",'
        '\n            "data_type": "Decimal Number"|"Whole Number"|"Text"|"Date"|"Boolean",'
        '\n            "is_key": true|false,'
        '\n            "is_measure": false'
        "\n          }"
        "\n        ],"
        '\n        "measures": ['
        "\n          {"
        '\n            "name": "...",'
        '\n            "expression": "... DAX ...",'
        '\n            "format_string": "Currency"|"0.00"|"0%"|"mmm dd yyyy"'
        "\n          }"
        "\n        ],"
        '\n        "key_columns": ["..."]'
        "\n      }"
        "\n    ],"
        '\n    "relationships": ['
        "\n      {"
        '\n        "from_table": "...",'
        '\n        "from_column": "...",'
        '\n        "to_table": "...",'
        '\n        "to_column": "...",'
        '\n        "cross_filter": "single"|"both"'
        "\n      }"
        "\n    ],"
        '\n    "calculation_groups": ['
        "\n      {"
        '\n        "name": "Time:"|"Currency:",'
        '\n        "expressions": {'
        '\n          "YTD": "... DAX ...",'
        '\n          "MTD": "... DAX ...",'
        '\n          "PY": "... DAX ...",'
        '\n          "YoY %": "... DAX ..."'
        "\n        }"
        "\n      }"
        "\n    ],"
        '\n    "roles": ['
        "\n      {"
        '\n        "name": "...",'
        '\n        "description": "...",'
        '\n        "filters": ["... DAX filter expression ..."]'
        "\n      }"
        "\n    ]"
        "\n  },"
        '\n  "dax_module": {'
        '\n    "measures": ['
        "\n      {"
        '\n        "name": "...",'
        '\n        "definition": "... DAX ...",'
        '\n        "comment": "..."'
        "\n      }"
        "\n    ],"
        '\n    "calculation_group_members": ['
        "\n      {"
        '\n        "name": "...",'
        '\n        "expression": "... DAX ...",'
        '\n        "format_string": "..."'
        "\n      }"
        "\n    ],"
        '\n    "time_intelligence_helpers": ['
        "\n      {"
        '\n        "name": "...",'
        '\n        "definition": "... DAX ..."'
        "\n      }"
        "\n    ]"
        "\n  },"
        '\n  "qa_checklist": ["..."]'
        "\n}"
        "\n\nDesign rules:"
        "\n- One cohesive subject/sector only; do not mix unrelated topics."
        "\n- Every component must be concrete and specific to the subject - no generic placeholders."
        "\n- Include 1 executive-summary page with KPI cards + a bar chart + a line chart."
        "\n- Include 1 detail page with a matrix/table + a supporting card or slicer."
        "\n- Include 1 analytical page with trend/accumulation visuals and a filter."
        "\n- Provide a realistic, well-structured semantic model: recognisable tables, keys, measures."
        "\n- Measures must be real, working DAX with format strings."
        "\n- Include at least one time-intelligence calculation group (YTD/MTD/PY/YoY)."
        "\n- Include at least one role (for RLS) with a concrete filter expression."
        "\n- QA checklist: list 6-10 concrete verification items for the report."
        "\n- Use a professional colour palette consistent with the theme."
        "\n- Maximum length is not a concern; completeness and correctness are."
        "\n- NEVER emit markdown fences, preamble text, or any text outside the JSON object."
        "\n- If you cannot derive a concrete piece from the subject, invent a realistic professional example."
        "\n"
    )
