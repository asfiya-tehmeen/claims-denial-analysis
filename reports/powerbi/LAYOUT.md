# Report layout: 2 pages, visual by visual

> **Data honesty:** claims are SIMULATED using the published DHA eClaimLink field structure. This sentence goes in a text box on both pages.

**Canvas:** View → Page view → Actual size; Format page → Canvas settings → 16:9, **1280 × 720**.
**Positions** are `x, y, width, height` in pixels. Set them in Format visual → General → Properties → Size and position.
**Theme:** View → Themes → *Classic*. Colours below are hex values. Titles are on, font 12 pt, and use the text given.
Apply the measure formats from MEASURES.md first, so every visual inherits them.

> **As built** (`DenialGuard.pbix`, `pbip/DenialGuard.pbip`, 2026-11-11), with these changes from the spec:
> - The default theme is used, because *Classic* was not in the installed theme picker.
> - The data-honesty text boxes are taller, so the full sentence fits.
> - The scorecard column headers are shorter.
> - Visual padding was reduced so the 98-pixel payment chart renders.
> - On the Payer Scorecard page, the payer and service-line slicers open on *Marina Health Partners TPA* and *Radiology*.

---

## Page 1: `RCM Overview`

| # | Visual | Position | Fields | Settings |
|---|---|---|---|---|
| 1 | Text box | 16, 8, 900, 36 | "RCM overview: where revenue leaks" | 20 pt bold |
| 2 | Text box | 16, 44, 1248, 24 | The data-honesty sentence | 9 pt, grey `#666666` |
| 3 | Slicer | 16, 76, 300, 56 | `dim_date[month_start]` | Style **Between** (date range) |
| 4 | Slicer | 332, 76, 220, 56 | `dim_payer[payer_name]` | Style **Dropdown**, multi-select, "Select all" on |
| 5 | Slicer | 568, 76, 220, 56 | `dim_service_line[service_line_label]` | Dropdown |
| 6 | Slicer | 804, 76, 220, 56 | `dim_provider[facility_name]` | Dropdown |
| 7–12 | Card (new card visual or classic card), 6 in one row | y = 144, height 92, width 200, x = 16, 224, 432, 640, 848, 1056 | 7 `Net Billed AED` · 8 `Initial Denial Rate (Value)` · 9 `Final Denial Rate (Value)` · 10 `Avoidable Denial Share` · 11 `Clean Claim Rate` · 12 `Median Days to Payment` | Category label on; titles: "Net billed (AED)", "Initial denial rate (value)", "Final denial rate (value)", "Avoidable share of denials", "Clean claim rate", "Median days to payment" |
| 13 | Line chart | 16, 248, 616, 228 | X-axis: `dim_date[year_month]` · Y-axis: `Initial Denied AED`, `Final Denied AED` | Title "Denied AED by service month". X-axis type Categorical. Colours: Initial `#7A7A7A`, Final `#D1495B`. Data labels off. Legend top. |
| 14 | Clustered bar chart | 648, 248, 616, 228 | Y-axis: `dim_denial_code[category]` · X-axis: `Final Denied AED` · Tooltips: `Initial Denied AED`, `Avoidable Denial Share` | Title "Revenue lost by denial category (after resubmission)". Sort by Final Denied AED, descending. Bars `#D1495B`. Data labels on, display units Thousands. |
| 15 | Matrix | 16, 488, 900, 220 | Rows: `dim_service_line[service_line_label]` · Columns: `dim_payer[payer_name]` · Values: `Initial Denial Rate (Value)` | Title "Initial denial rate (value): service line × payer". Conditional formatting → Background color → Gradient: lowest `#FFFFFF`, highest `#D1495B`. Row and column subtotals on. |
| 16 | Line chart | 932, 488, 332, 220 | X-axis: `dim_date[year_month]` · Y-axis: `A/R Days` | Title "A/R days at month-end". Line `#2A6FBB`. Y-axis starts at 0. |

**Interactions:** leave the defaults (every slicer filters every visual).

---

## Page 2: `Payer Scorecard`

| # | Visual | Position | Fields | Settings |
|---|---|---|---|---|
| 1 | Text box | 16, 8, 900, 36 | "Payer scorecard: who denies more than their mix explains, and who pays late" | 20 pt bold |
| 2 | Text box | 16, 44, 1248, 24 | The data-honesty sentence + " Deadlines: DHIC PD-05-2025 (45 days initial, 30 days resubmission)." | 9 pt, grey |
| 3 | Table | 16, 76, 1248, 250 | Columns in this order: `dim_payer[payer_name]`, `dim_payer[payer_kind]`, `Claims`, `Net Billed AED`, `Initial Denial Rate (Value)`, `Expected Denial Rate (Value)`, `Denial Rate vs Expected`, `Avoidable Denial Share`, `Resubmission Overturn Rate`, `Final Denial Rate (Value)`, `Median Days to Payment`, `% Initial RA Within 45 Days`, `Late Payment Fee Due AED`, `A/R Days (Avg Last 12 Month-Ends)` | Title "Payer scorecard (all service months)". Sort by `Final Denial Rate (Value)`, descending. Conditional formatting **Rules** on `Denial Rate vs Expected` (background): ≥ 1.10 → `#F4C7CF`; ≥ 0.95 and < 1.10 → `#FFF1C1`; < 0.95 → `#D7EBD5`. Rules on `% Initial RA Within 45 Days` (font colour): < 0.90 → `#B00020`. Totals row on. |
| 4 | Slicer | 16, 338, 260, 56 | `dim_payer[payer_name]` | Dropdown, **single select** on (Format → Selection), default to any payer |
| 5 | Slicer | 292, 338, 260, 56 | `dim_service_line[service_line_label]` | Dropdown, single select |
| 6 | Line chart | 16, 402, 820, 200 | X-axis: `dim_date[week_start]` · Y-axis: `Auth Denial Rate (by RA Week)` | Title "Weekly authorisation denials for the selected payer and service line (by remittance week)". X-axis type Continuous. Line `#2A6FBB`. |
| 7 | Table | 852, 338, 412, 264 | `dim_payer[payer_name]`, `dim_service_line[service_line_label]`, `fact_change_alert[alert_week]` (set to *Don't summarize*, not Date Hierarchy), `fact_change_alert[baseline_rate]` | Title "CUSUM alerts raised by the change detector". Sort by alert_week ascending. Format `baseline_rate` as `0.0%`. |
| 8 | Clustered column chart | 16, 614, 1248, 98 | X-axis: `dim_date[year_month]` · Y-axis: `Median Days to Payment` | Title "Median days to payment by service month, selected payer". Analytics pane → **Constant line** at 45, colour `#B00020`, label "PD-05-2025 limit". Columns `#7A7A7A`. |

**Interactions (Format → Edit interactions):** select slicer 4 (payer), then set visual 3 (scorecard table) to **None**, so the scorecard always shows all payers. Do the same for slicer 5. Slicers 4 and 5 should still filter visuals 6, 7 and 8.

**What to show in an interview:** on page 2, select the payer and service line where the alert table shows a run of alerts. Point to where the weekly authorisation-denial line steps up and where the first CUSUM alert sits. Then go to page 1 to show what that change cost in denied AED.
