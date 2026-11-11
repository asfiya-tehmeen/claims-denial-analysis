# Power BI data model: step by step

> **Data honesty:** claims are SIMULATED using the published DHA eClaimLink field structure. Put this sentence in a text box on every page.

Files are in this folder (`reports/powerbi/`). Rebuild them with `python -m src.run_all` (or `python -m src.export_powerbi` after the pipeline has run). The CSVs are UTF-8, comma-separated, ISO dates, booleans as 1/0.

## 1. Load the tables (Power BI Desktop)

Do this for each file: **Home → Get data → Text/CSV → pick the file → Transform Data**. In Power Query, set the column types listed below (Transform → Data type), then **Close & Apply**. Load the dimensions first.

| Order | File | Table name in Power BI | Rows (this run) |
|---|---|---|---|
| 1 | `dim_date.csv` | dim_date | 1,062 |
| 2 | `dim_payer.csv` | dim_payer | 6 |
| 3 | `dim_service_line.csv` | dim_service_line | 7 |
| 4 | `dim_provider.csv` | dim_provider | 39 |
| 5 | `dim_denial_code.csv` | dim_denial_code | 21 |
| 6 | `fact_claim_line.csv` | fact_claim_line | 135,706 |
| 7 | `fact_remittance.csv` | fact_remittance | 143,795 |
| 8 | `fact_change_alert.csv` | fact_change_alert | 10 |

### Column types

Anything not listed should be **Text**.

| Table | Whole Number | Decimal Number | Date |
|---|---|---|---|
| dim_date | date_key, year, quarter, month, iso_weekday, is_month_end, sim_month | | date, month_start, week_start |
| dim_payer | payer_key | | |
| dim_service_line | service_line_key | | |
| dim_provider | provider_key | | |
| dim_denial_code | denial_code_key, avoidable | | |
| fact_claim_line | line_no, is_claim_anchor, payer_key, service_line_key, provider_key, service_date_key, submission_date_key, initial_ra_date_key, initial_denial_code_key, quantity, has_prior_auth, is_initial_denied, is_avoidable_denial, was_resubmitted, was_overturned, is_final_denied, days_to_initial_ra, days_service_to_submission, late_submission_days, scrubber_flag_count, claim_scrubber_clean, claim_first_pass_paid, ar_eligible | gross, patient_share, net, initial_paid, initial_denied_amount, recovered_on_resubmission, final_denied_amount | submission_date, last_settlement_date |
| fact_remittance | round, payer_key, service_line_key, provider_key, settlement_date_key, denial_code_key, is_denied, days_to_settlement, deadline_days, within_deadline, late_payment_days, ar_eligible | payment_amount, line_net, late_payment_fee_aed | settlement_date |
| fact_change_alert | payer_key, service_line_key | baseline_rate | alert_week |

Blank keys (for example `initial_denial_code_key` on paid lines) must stay blank. Do not replace them with 0.

## 2. Mark the date table

Select **dim_date** → **Table tools → Mark as date table** → date column: `date`.
Then select `dim_date[year_month]` → **Column tools → Sort by column** → `month_start`. Do the same for `month_name` → `month`.

## 3. Relationships (Model view)

Turn off **File → Options → Current file → Data load → Autodetect new relationships** first. Delete anything Power BI created automatically, then add exactly these:

| # | From (many side) | To (one side) | Cardinality | Cross-filter | Active |
|---|---|---|---|---|---|
| 1 | fact_claim_line[payer_key] | dim_payer[payer_key] | Many-to-one | Single | Yes |
| 2 | fact_claim_line[service_line_key] | dim_service_line[service_line_key] | Many-to-one | Single | Yes |
| 3 | fact_claim_line[provider_key] | dim_provider[provider_key] | Many-to-one | Single | Yes |
| 4 | fact_claim_line[initial_denial_code_key] | dim_denial_code[denial_code_key] | Many-to-one | Single | Yes |
| 5 | fact_claim_line[service_date_key] | dim_date[date_key] | Many-to-one | Single | **Yes** (service month drives page 1) |
| 6 | fact_claim_line[submission_date_key] | dim_date[date_key] | Many-to-one | Single | **No** |
| 7 | fact_claim_line[initial_ra_date_key] | dim_date[date_key] | Many-to-one | Single | **No** (used by `USERELATIONSHIP`) |
| 8 | fact_remittance[payer_key] | dim_payer[payer_key] | Many-to-one | Single | Yes |
| 9 | fact_remittance[service_line_key] | dim_service_line[service_line_key] | Many-to-one | Single | Yes |
| 10 | fact_remittance[provider_key] | dim_provider[provider_key] | Many-to-one | Single | Yes |
| 11 | fact_remittance[denial_code_key] | dim_denial_code[denial_code_key] | Many-to-one | Single | Yes |
| 12 | fact_remittance[settlement_date_key] | dim_date[date_key] | Many-to-one | Single | Yes |
| 13 | fact_change_alert[payer_key] | dim_payer[payer_key] | Many-to-one | Single | Yes |
| 14 | fact_change_alert[service_line_key] | dim_service_line[service_line_key] | Many-to-one | Single | Yes |

There is **no** relationship between the two fact tables. They meet only through the dimensions.

What the date relationships mean:
- `fact_claim_line` measures follow the **service date** by default.
- `fact_remittance` measures (timeliness, late-payment fees) follow the **settlement date**.
- The A/R measures ignore the date slicer's range and use only its **end date**. That is the standard "balance as at" definition.

## 4. Hide technical columns

In Report view, hide all `*_key` columns, `is_claim_anchor`, `ar_eligible` and `claim_round_id`. Users should drag fields from the dimension tables.

## 5. Add the measures

Create an empty table to hold them: **Home → Enter data**, name it `_Measures`, then **Load**. Add every measure in [`MEASURES.md`](MEASURES.md) to `_Measures`, then delete the dummy column.

## 6. Check the numbers

`expected_values.csv` holds the value SQL computed for each measure with no filter, for each payer, and for each service line, plus A/R days per month. Put a measure in a card, apply the filter from the `filter` column, and compare. Differences beyond rounding mean the DAX or the model differs from the SQL definition in `sql/KPI_DEFINITIONS.md`.

> **Checked (2026-11-11):** the model in `DenialGuard.pbix` was built from this spec, and every row of `expected_values.csv` was queried as DAX in Power BI Desktop. Result: **274 of 274 values match** (22 measures, unfiltered and by payer, service line and month). The results, with expected and actual values, are in [`measure_check.csv`](measure_check.csv). The measure expressions match `MEASURES.md` exactly.

## 7. Moving the files

The Power Query sources in `DenialGuard.pbix` / `pbip/` use **absolute paths** to this folder. If you move or clone the project, open **Transform data → Data source settings → Change Source** and point each CSV to its new location, or run `python -m src.run_all` first to regenerate the CSVs (they are gitignored).
