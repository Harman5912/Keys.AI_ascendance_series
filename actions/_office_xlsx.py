"""actions/_office_xlsx.py — styled, dataset-aware Excel workbooks.

The workbook adapts to the request: a revenue review gets monthly revenue/cost
and margin; a programme budget gets workstream budget vs actual; an inventory
forecast gets SKU cover and reorder points. All three share the same visual
shell (KPI cards, a data table with formulas, two native charts, assumptions)
but the columns, formulas and chart series are the real ones for that subject.
"""

from __future__ import annotations

import re
from pathlib import Path

from ._office_builder import DATE_LONG, YEAR, DocPlan, _numbers, document_plan


def _dataset(plan: DocPlan, title: str, instruction: str):
    text = f"{title} {instruction}".lower()
    n = _numbers(plan.subject)

    if re.search(r"\b(budget|spend|cost plan|forecast to complete|workstream)\b", text):
        mode = "budget"
        headers = ["Workstream", "Budget", "Actual", "Variance", "Used %", "Hours", "Owner"]
        workstreams = [
            ("Discovery and design", 0.14, 0.96, 320, "M. Lindqvist"),
            ("Platform build", 0.31, 1.04, 1180, "O. Price"),
            ("Data migration", 0.18, 0.88, 640, "D. Osei"),
            ("Integration", 0.12, 1.12, 410, "S. Alvarez"),
            ("Testing and QA", 0.09, 0.92, 290, "P. Raman"),
            ("Training", 0.05, 0.74, 160, "M. Lindqvist"),
            ("Rollout", 0.06, 1.08, 210, "O. Price"),
            ("Contingency", 0.05, 0.20, 0, "Finance"),
        ] + [("Reserve " + str(i), 0.0, 0.0, 0, "Finance") for i in range(4)]
        budget = int(n["budget"] * 1.35)
        rows = []
        for name, share, ratio, hours, owner in workstreams:
            b = int(budget * share) if share else 0
            actual = int(b * ratio) if b else 0
            rows.append((name, b, actual, hours, owner))
        kpis = [
            ("Total budget", "=SUM(Data!C4:C15)", f"${budget:,}", "Approved envelope"),
            ("Actual spend", "=SUM(Data!D4:D15)", "$#,##0", "Committed to date"),
            ("Variance", "=SUM(Data!C4:C15)-SUM(Data!D4:D15)", "$#,##0", "Positive is under budget"),
            ("Used", "=IFERROR(SUM(Data!D4:D15)/SUM(Data!C4:C15),0)", "0.0%", "Of approved envelope"),
        ]
        chart_title = "Budget vs actual by workstream"
        chart_series = (3, 4)
        trend_title = "Budget used by workstream"
        trend_col = "F"
        trend_fmt = "0.0%"
        table_title = "Workstream budget and actuals"
        data_desc = "Edit Budget and Actual; the dashboard and variance recalculate."
        notes = ["Planned", "In flight", "Under review", "Change request", "Planned",
                 "Complete", "Planned", "Held", "Held", "Held", "Held", "Held"]
        assumptions = [
            ("Contingency held", 0.10, "0.0%"),
            ("Forecast uplift", 0.08, "0.0%"),
            ("Cost inflation", 0.04, "0.0%"),
            ("Working days / month", 21, "0"),
            ("Approval threshold", 25000, "$#,##0"),
        ]
    elif re.search(r"\b(inventory|stock|sku|reorder|warehouse|forecast)\b", text):
        mode = "inventory"
        headers = ["SKU", "On hand", "Monthly demand", "Cover (months)", "Reorder point",
                   "Lead time (days)", "Supplier"]
        products = [
            ("FF-BIRD-14", 148, 46, 21, "Glasshouse"),
            ("FF-POTH-17", 96, 38, 18, "Glasshouse"),
            ("FF-ZZ-14", 64, 21, 28, "North Growers"),
            ("FF-HEART-12", 210, 74, 14, "Cuttings Co."),
            ("FF-HART-17", 88, 26, 24, "Glasshouse"),
            ("FF-RUBBER-21", 42, 18, 30, "North Growers"),
            ("FF-FERN-14", 132, 52, 16, "Cuttings Co."),
            ("FF-OLIVE-24", 37, 12, 35, "North Growers"),
            ("FF-PILEA-12", 176, 61, 15, "Cuttings Co."),
            ("FF-CACTUS-9", 120, 33, 19, "Desert House"),
            ("FF-MOSS-6", 240, 80, 10, "Cuttings Co."),
            ("FF-POT-14", 310, 95, 7, "Clay Works"),
        ]
        rows = products
        kpis = [
            ("SKUs", "=COUNTA(Data!B4:B15)", "0", "Active product lines"),
            ("Units on hand", "=SUM(Data!C4:C15)", "#,##0", "Physical stock"),
            ("Months cover", "=IFERROR(SUM(Data!C4:C15)/SUM(Data!D4:D15),0)", "0.0", "Aggregate cover"),
            ("Reorder alerts", "=SUMPRODUCT(--(Data!C4:C15<Data!F4:F15))", "0", "Below reorder point"),
        ]
        chart_title = "On hand vs reorder point"
        chart_series = (3, 6)
        trend_title = "Cover by SKU (months)"
        trend_col = "E"
        trend_fmt = "0.0"
        table_title = "Stock cover and reorder points"
        data_desc = "Edit on-hand and monthly demand; cover and reorder flags recalculate."
        notes = ["Core", "Core", "Slow", "Core", "Seasonal", "Statement",
                 "Seasonal", "Statement", "Core", "Gift", "Seasonal", "Pot"]
        assumptions = [
            ("Safety stock", 0.20, "0.0%"),
            ("Seasonal uplift", 0.15, "0.0%"),
            ("Shrinkage", 0.03, "0.0%"),
            ("Reorder multiple", 24, "0"),
            ("Lead time buffer (days)", 5, "0"),
        ]
    else:
        mode = "revenue"
        headers = ["Month", "Revenue", "Cost", "Margin", "Margin %", "Units", "Region"]
        regions = ["North", "South", "East", "West"]
        base = n["revenue"] // 12
        rows = []
        for m in range(12):
            rev = int(base * (0.82 + 0.035 * m) + (m % 4) * 900)
            cost = int(rev * (0.42 + (m % 5) * 0.012))
            units = int(rev / (38 + (m % 6)))
            rows.append((f"{YEAR}-{m + 1:02d}", rev, cost, units, regions[m % 4]))
        kpis = [
            ("Revenue", "=SUM(Data!C4:C15)", "$#,##0", "Total recognised revenue"),
            ("Gross margin", "=IFERROR((SUM(Data!C4:C15)-SUM(Data!D4:D15))/SUM(Data!C4:C15),0)",
             "0.0%", "Revenue less direct cost"),
            ("Units", "=SUM(Data!G4:G15)", "#,##0", "Units delivered"),
            ("Growth", "=IFERROR(Data!C15/Data!C4-1,0)", "0.0%", "First to last month"),
        ]
        chart_title = "Revenue and cost by month"
        chart_series = (3, 4)
        trend_title = "Margin % by month"
        trend_col = "F"
        trend_fmt = "0.0%"
        table_title = "Monthly performance"
        data_desc = "Edit Revenue and Cost; every dashboard formula recalculates."
        notes = ["Baseline", "New listing", "Price test", "Campaign", "Baseline", "Campaign",
                 "New region", "Baseline", "Price test", "Campaign", "Baseline", "Year end"]
        assumptions = [
            ("Tax rate", 0.08, "0.0%"),
            ("Growth assumption", 0.12, "0.0%"),
            ("Cost inflation", 0.04, "0.0%"),
            ("Units per day (plan)", n["units"] // 300, "#,##0"),
            ("Contingency", 0.10, "0.0%"),
        ]
    return {
        "mode": mode, "headers": headers, "rows": rows, "kpis": kpis,
        "chart_title": chart_title, "chart_series": chart_series,
        "trend_title": trend_title, "trend_col": trend_col, "trend_fmt": trend_fmt,
        "table_title": table_title, "data_desc": data_desc, "notes": notes,
        "assumptions": assumptions,
    }


def build_xlsx(path: Path, title: str, instruction: str = "") -> DocPlan:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.formatting.rule import DataBarRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    plan = document_plan(title, instruction)
    ds = _dataset(plan, title, instruction)
    headers = ds["headers"]
    rows = ds["rows"]
    mode = ds["mode"]

    NAVY = "1F3A5F"
    GOLD = "C9A227"
    PALE = "F6F3EA"
    CREAM = "FBFAF6"
    GREY = "6B7280"
    RED = "C8102E"
    thin = Side(style="thin", color="D8D2C4")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    wb = Workbook()
    ws = wb.active
    ws.title = "Dashboard"
    ws.sheet_view.showGridLines = False
    for i in range(1, 13):
        ws.column_dimensions[get_column_letter(i)].width = 14

    # header band
    ws.merge_cells("B2:H2")
    c = ws["B2"]
    c.value = title
    c.font = Font(name="Calibri", size=20, bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor=NAVY)
    c.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    ws.row_dimensions[2].height = 40

    ws.merge_cells("B3:H3")
    ws["B3"] = f"{plan.subject}  ·  prepared {DATE_LONG}  ·  USD"
    ws["B3"].font = Font(name="Calibri", size=9, color=GREY)
    ws["B3"].alignment = Alignment(horizontal="left", indent=1)

    # KPI cards
    for i, (label, formula, fmt, note) in enumerate(ds["kpis"]):
        col = 2 + i * 2
        ws.merge_cells(start_row=5, start_column=col, end_row=5, end_column=col + 1)
        ws.merge_cells(start_row=6, start_column=col, end_row=6, end_column=col + 1)
        ws.merge_cells(start_row=7, start_column=col, end_row=7, end_column=col + 1)
        cell = ws.cell(row=5, column=col, value=label)
        cell.font = Font(name="Calibri", size=9, bold=True, color=GREY)
        cell.alignment = Alignment(horizontal="left")
        val = ws.cell(row=6, column=col, value=formula)
        val.font = Font(name="Calibri", size=18, bold=True, color=NAVY)
        val.alignment = Alignment(horizontal="left")
        val.number_format = fmt
        note_cell = ws.cell(row=7, column=col, value=note)
        note_cell.font = Font(name="Calibri", size=8, color=GREY)
        note_cell.alignment = Alignment(horizontal="left")
        for r in (5, 6, 7):
            for cc in (col, col + 1):
                ws.cell(row=r, column=cc).fill = PatternFill("solid", fgColor=PALE)
                if r == 7:
                    ws.cell(row=r, column=cc).border = Border(bottom=thin)
    ws.row_dimensions[6].height = 30

    # table
    ws["B10"] = ds["table_title"]
    ws["B10"].font = Font(name="Calibri", size=12, bold=True, color=NAVY)
    for j, h in enumerate(headers, 2):
        cell = ws.cell(row=11, column=j, value=h)
        cell.font = Font(name="Calibri", size=9, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(horizontal="center")
        cell.border = border

    for r0, row in enumerate(rows):
        r = 12 + r0
        if mode == "revenue":
            month, rev, cost, units, region = row
            vals = [month, rev, cost, f"=C{r}-D{r}", f"=IFERROR(E{r}/C{r},0)", units, region]
        elif mode == "budget":
            name, budget, actual, hours, owner = row
            vals = [name, budget, actual, f"=C{r}-D{r}", f"=IFERROR(D{r}/C{r},0)", hours, owner]
        else:
            sku, on_hand, demand, lead, supplier = row
            vals = [sku, on_hand, demand, f"=IFERROR(C{r}/D{r},0)", f"=ROUND(D{r}*2,0)", lead, supplier]
        for j, v in enumerate(vals, 2):
            cell = ws.cell(row=r, column=j, value=v)
            cell.border = border
            cell.font = Font(name="Calibri", size=9)
            if mode == "inventory":
                if j == 3:
                    cell.number_format = "#,##0"
                elif j == 4:
                    cell.number_format = "#,##0"
                elif j == 5:
                    cell.number_format = "0.0"
                elif j == 6:
                    cell.number_format = "#,##0"
                elif j == 7:
                    cell.number_format = "0"
            elif mode == "budget":
                if j in (3, 4, 5):
                    cell.number_format = "$#,##0"
                elif j == 6:
                    cell.number_format = "0.0%"
                elif j == 7:
                    cell.number_format = "#,##0"
            else:
                if j in (3, 4):
                    cell.number_format = "$#,##0"
                elif j == 5:
                    cell.number_format = "$#,##0"
                elif j == 6:
                    cell.number_format = "0.0%"
                elif j == 7:
                    cell.number_format = "#,##0"
            if r % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=CREAM)

    # totals
    ws.cell(row=24, column=2, value="Total").font = Font(bold=True, color=NAVY)
    ws.cell(row=24, column=3, value="=SUM(C12:C23)").number_format = (
        "0" if mode == "inventory" else "$#,##0")
    ws.cell(row=24, column=4, value="=SUM(D12:D23)").number_format = (
        "#,##0" if mode != "budget" else "$#,##0")
    if mode == "inventory":
        ws.cell(row=24, column=5, value="=IFERROR(C24/(D24/12),0)").number_format = "0.0"
        ws.cell(row=24, column=6, value="=SUM(F12:F23)").number_format = "#,##0"
        ws.cell(row=24, column=7, value="=AVERAGE(G12:G23)").number_format = "0.0"
    else:
        ws.cell(row=24, column=5, value="=C24-D24").number_format = "$#,##0"
        ws.cell(row=24, column=6, value=("=IFERROR(D24/C24,0)" if mode == "budget"
                                          else "=IFERROR(E24/C24,0)")).number_format = "0.0%"
        ws.cell(row=24, column=7, value=("=SUM(G12:G23)" if mode == "revenue" else "=SUM(G12:G23)")
                ).number_format = "#,##0"
    for j in range(2, 9):
        ws.cell(row=24, column=j).border = Border(top=Side(style="medium", color=NAVY))

    # bar chart
    chart = BarChart()
    chart.type = "col"
    chart.style = 10
    chart.title = ds["chart_title"]
    chart.y_axis.title = "USD" if mode != "inventory" else "Units"
    chart.height = 7.2
    chart.width = 16
    if mode == "inventory":
        # On-hand (column C) and reorder point (column F) are not adjacent on
        # the dashboard. Bind them as two explicit series so the chart never
        # plots demand/cover on a different scale than the stock level.
        chart.add_data(Reference(ws, min_col=3, min_row=11, max_row=23), titles_from_data=True)
        chart.add_data(Reference(ws, min_col=6, min_row=11, max_row=23), titles_from_data=True)
    else:
        c1, c2 = ds["chart_series"]
        chart.add_data(Reference(ws, min_col=c1, max_col=c2, min_row=11, max_row=23), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=2, min_row=12, max_row=23))
    chart.series[0].graphicalProperties.solidFill = NAVY
    chart.series[1].graphicalProperties.solidFill = GOLD
    ws.add_chart(chart, "B26")

    # trend sheet
    md = wb.create_sheet("Trend")
    md.sheet_view.showGridLines = False
    md.column_dimensions["A"].width = 20
    md.column_dimensions["B"].width = 14
    md["A1"] = ds["trend_title"]
    md["A1"].font = Font(name="Calibri", size=14, bold=True, color=NAVY)
    md["A3"] = headers[0]
    md["B3"] = ds["trend_title"].split(" by ")[0]
    for cell in (md["A3"], md["B3"]):
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.border = border
    for i, row in enumerate(rows, 4):
        md.cell(row=i, column=1, value=row[0]).border = border
        pct = md.cell(row=i, column=2, value=f"='Dashboard'!{ds['trend_col']}{i + 8}")
        pct.number_format = ds["trend_fmt"]
        pct.border = border
    line = LineChart()
    line.title = ds["trend_title"]
    line.height = 7
    line.width = 15
    line.add_data(Reference(md, min_col=2, min_row=3, max_row=15), titles_from_data=True)
    line.set_categories(Reference(md, min_col=1, min_row=4, max_row=15))
    line.series[0].graphicalProperties.line.solidFill = RED
    line.series[0].graphicalProperties.line.width = 28000
    md.add_chart(line, "D3")

    # data sheet — formulas live here so edits propagate
    data_ws = wb.create_sheet("Data")
    data_ws.sheet_view.showGridLines = False
    data_ws["A1"] = ds["table_title"]
    data_ws["A1"].font = Font(name="Calibri", size=14, bold=True, color=NAVY)
    data_ws["A2"] = ds["data_desc"]
    data_ws["A2"].font = Font(size=9, color=GREY)
    dheaders = headers + ["Notes"]
    # Column A is a margin; the table is B-anchored so every formula in this
    # builder (per-row cover/reorder, dashboard KPI cards, chart series,
    # trend links) resolves to the column it names. Writing at A made the
    # "Units on hand" KPI silently sum monthly demand instead.
    for j, h in enumerate(dheaders, 2):
        cell = data_ws.cell(row=3, column=j, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.border = border
    for i, row in enumerate(rows, 4):
        if mode == "revenue":
            month, rev, cost, units, region = row
            vals = [month, rev, cost, f"=C{i}-D{i}", f"=IFERROR(E{i}/C{i},0)", units, region]
        elif mode == "budget":
            name, budget, actual, hours, owner = row
            vals = [name, budget, actual, f"=C{i}-D{i}", f"=IFERROR(D{i}/C{i},0)", hours, owner]
        else:
            sku, on_hand, demand, lead, supplier = row
            vals = [sku, on_hand, demand, f"=IFERROR(C{i}/D{i},0)", f"=ROUND(D{i}*2,0)", lead, supplier]
        vals.append(ds["notes"][i - 4])
        for j, v in enumerate(vals, 2):
            cell = data_ws.cell(row=i, column=j, value=v)
            cell.border = border
            if mode == "inventory":
                if j in (3, 4, 6, 7):
                    cell.number_format = "#,##0"
                elif j == 5:
                    cell.number_format = "0.0"
            elif mode == "budget":
                if j in (4, 5, 6):
                    cell.number_format = "$#,##0"
                elif j == 7:
                    cell.number_format = "0.0%"
                elif j == 8:
                    cell.number_format = "#,##0"
            else:
                if j in (4, 5):
                    cell.number_format = "$#,##0"
                elif j == 6:
                    cell.number_format = "$#,##0"
                elif j == 7:
                    cell.number_format = "0.0%"
                elif j == 8:
                    cell.number_format = "#,##0"
    tab = Table(displayName="DataTable", ref="B3:I15")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    data_ws.add_table(tab)
    data_ws.column_dimensions["A"].width = 3
    for j, width in enumerate([20, 14, 14, 14, 12, 12, 16, 18], 2):
        data_ws.column_dimensions[get_column_letter(j)].width = width
    data_ws.freeze_panes = "C4"
    data_ws.conditional_formatting.add(
        "E4:E15", DataBarRule(start_type="min", end_type="max", color=GOLD))
    data_ws.auto_filter.ref = "B3:I15"

    # assumptions
    a = wb.create_sheet("Assumptions")
    a.sheet_view.showGridLines = False
    a.column_dimensions["A"].width = 30
    a.column_dimensions["B"].width = 18
    a["A1"] = "Assumptions and controls"
    a["A1"].font = Font(name="Calibri", size=14, bold=True, color=NAVY)
    for i, (label, value, fmt) in enumerate(ds["assumptions"], 3):
        a.cell(row=i, column=1, value=label).font = Font(bold=True)
        cell = a.cell(row=i, column=2, value=value)
        cell.number_format = fmt
        cell.fill = PatternFill("solid", fgColor=PALE)
        cell.border = border
    a["A10"] = "Notes"
    a["A10"].font = Font(bold=True, color=NAVY)
    notes = [
        "All values are fictional and internally consistent for demonstration.",
        "Dashboard totals use live formulas; edits in Data recalculate the view.",
        "No external links, macros or cached secrets are present in this workbook.",
        f"Workbook mode: {mode}; chart series are bound to the table above.",
    ]
    for i, note in enumerate(notes, 11):
        a.cell(row=i, column=1, value=note).font = Font(size=9, color=GREY)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return plan
