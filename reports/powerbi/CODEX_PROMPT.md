You are building a Power BI dashboard for a healthcare claims-denial analytics project. You have the Power BI Modeling MCP server and Power BI Desktop (Windows) available. Work in this folder:

C:\Users\exube\OneDrive\Desktop\resume-builder-main\projects\e-claims-denial-analysis\reports\powerbi

## Read these first (they are the spec; do not redesign)
- MODEL.md: tables, column types, date table, relationships, hidden columns
- MEASURES.md: 25 DAX measures with display folders. Use the exact names and DAX.
- LAYOUT.md: 2 report pages ("RCM Overview", "Payer Scorecard"), 1280x720, every visual with position, size, fields and formatting
- expected_values.csv: 274 check values (measure, filter, expected_value) produced by the SQL pipeline. This is the ground truth.
- DATA_HONESTY.txt: the banner text that must appear on both pages
- Data files: fact_claim_line.csv, fact_remittance.csv, fact_change_alert.csv, dim_date.csv, dim_payer.csv, dim_provider.csv, dim_service_line.csv, dim_denial_code.csv

## Before you start
1. List the tools the Power BI MCP server actually exposes and tell me in 5 lines what it can and cannot do (e.g. load data, create relationships/measures, run DAX queries, create visuals). Do not assume capabilities; plan around what is really there.
2. Confirm Power BI Desktop is open with a blank report and the MCP is connected to that instance. If not, stop and tell me exactly what to click.

## Phase 1: semantic model (via MCP)
- Load the 8 CSVs from the folder above with the column types in MODEL.md (Power Query M with absolute paths). If the MCP cannot import data, stop and give me a short manual Get Data checklist, then continue once I confirm.
- Mark dim_date as the date table; create every relationship in MODEL.md with the stated cardinality, direction and active/inactive flag; hide the technical columns listed.
- Create all measures from MEASURES.md verbatim, with display folders and format strings.

## Phase 2: verify every number (most important)
- For each row of expected_values.csv, run a DAX query (EVALUATE / SUMMARIZECOLUMNS or CALCULATE with the stated filter) and compare with expected_value. Tolerance: 0.1% relative or 0.0005 absolute for rates.
- Write the results to reports/powerbi/measure_check.csv (measure, filter, expected, actual, pass) and print a summary: N passed / N failed.
- If a measure fails, find the cause (relationship, filter direction, blank handling, data type). Fix genuine DAX/model bugs and list every change you made to the DAX versus MEASURES.md and why. NEVER hard-code values or tweak a measure just to hit the number. If you cannot explain a mismatch, leave it failing and report it.
- Do not edit the CSVs or anything outside reports/powerbi/.

## Phase 3: report pages
- Build the 2 pages exactly as LAYOUT.md describes. If the MCP cannot create visuals, save the file as a Power BI Project (.pbip, PBIR format enabled) to reports/powerbi/pbip/DenialGuard.pbip and create the visuals by writing the report definition files; reopen in Desktop to confirm they render. If that is not feasible, stop and give me a numbered click-by-click checklist per visual instead.
- Put the DATA_HONESTY.txt text as a visible text box on both pages. Simulated data must be obvious.
- Use only the measures from MEASURES.md on visuals (no implicit sums).

## Finish
- Save DenialGuard.pbix (and the .pbip if used) in reports/powerbi/.
- Export a PNG screenshot of each page to reports/figures/powerbi_page1.png and powerbi_page2.png (or tell me to take them if you cannot).
- Final message: what was built, the measure check result (N/274 passed), any DAX changes against MEASURES.md, anything you could not do and why. Report only numbers you actually queried.
- Do not commit or push to git.
