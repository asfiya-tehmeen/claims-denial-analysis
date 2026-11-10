# Project E: DenialGuard — Claims Denial Analytics for UAE Medical Insurance

**Status:** Not started | **Data:** HYBRID (simulated claims; real public code sets and edit rules) | **Effort:** 6 days (core)
**Target roles:** medical insurance / claims / RCM / denial-management analyst at UAE insurers, TPAs and hospital groups
**Earlier plans:** [`README_v1_original.md`](README_v1_original.md) (4-day first draft), [`README_v2_extended.md`](README_v2_extended.md) (7 to 9 day version; parked items listed in Section 12)

> **Data honesty (first lines of every output: REPORT.md, Power BI pages, data dictionary):** Claims are **simulated** using the published DHA eClaimLink field structure (a NPHIES mapping note is in the data dictionary). Code sets and edit rules come from real public sources listed in `data/reference/SOURCES.md`, each marked verified or unverified. No result here describes real UAE or Saudi denial rates.

## 1. The pitch

Every hospital already runs a claim scrubber. The questions an RCM director asks are: *where is revenue leaking, what does a model add on top of the scrubber, which claims should my coders review today, and which payer changed its behaviour?* This project answers those questions with the tools their job descriptions name: **SQL, Power BI, claims data and denial management.**

1. **Line-level claims with remittance advice.** Each claim has activity lines. Payers pay, partly pay or deny each line, and denied lines can be resubmitted. Denial codes follow the eClaimLink denial-code groups.
2. **The KPI layer is SQL.** The standard RCM KPIs and a payer scorecard are built as DuckDB SQL views in `sql/`, then exported as a star schema for Power BI.
3. **Rules vs ML, measured in AED.** A rule scrubber (with real CMS NCCI/MUE edits where they apply to CPT codes) is compared with logistic regression and LightGBM. The headline metric is **AED recovered per coder hour** under a fixed review capacity, reported next to AUC.
4. **An honest ceiling.** The generator knows each line's true denial probability, so the report shows the **best achievable AUC and Brier score** next to the model's.
5. **A hidden answer key.** Planted effects, including one payer that changes its authorisation behaviour mid-period, are scored only at the end, by one script.

## 2. Business questions

| # | Question | Answered by |
|---|---|---|
| Q1 | Where does revenue leak: which payers, service lines, providers and denial categories, by count and by AED value? How much was avoidable? | SQL KPI layer, Power BI page 1 |
| Q2 | With a fixed coder team, which lines should be reviewed before submission, and how much AED does that recover per coder hour: rules, ML, or both? | Scrubber + models + worklist simulation |
| Q3 | Which payer changed its behaviour, when did it change, and how many weeks did it take to detect? | Change detector, Power BI page 2 |
| Q4 | How do payers compare on denials, overturn rate and days to payment, and do they pay within the Dubai directive's timelines? | Payer scorecard (SQL), Power BI page 2 |

## 3. Scope

| Item | Core version |
|---|---|
| Claims | ~50K claims, ~150K activity lines |
| Period | 24 months (time-based model split needs the length) |
| Provider | 1 hospital group, 2 facilities, ~40 doctors |
| Payers | 6, fictional names (no real insurer or TPA is modelled) |
| Service lines | 7: outpatient consultation, emergency, day surgery, radiology, laboratory, physiotherapy, pharmacy |
| Codes | ICD-10-CM diagnoses; CPT/HCPCS activities. Pharmacy uses simulated drug codes in a DHA-style format (NCCI does not apply). Dental is excluded, because it uses separately licensed codes and adds little. |

## 4. Sources and verification

Every source goes into `data/reference/SOURCES.md` with its URL, download date, file hash and a **status: verified / unverified / not found**. Nothing marked unverified is encoded as a rule; it becomes a stated assumption in `config/`.

| Source | Used for | Status now |
|---|---|---|
| DHA eClaimLink claim and remittance schema (field names, activity types, resubmission types) | Table structure, data dictionary | **Unverified** (check Day 1) |
| DHA eClaimLink denial-code list and groups | `dim_denial_code`, denial categories | **Unverified** (check Day 1) |
| Dubai claims-management directive (effective 16 Nov 2025 per the earlier README) | Payment-timeline rule in the scorecard | **Unverified.** The title, issuing body and timelines must be read from the published text before being encoded. If the text can't be found, the scorecard shows days to payment with no compliance column and says why. |
| CMS NCCI procedure-to-procedure (PTP) edits and MUE tables (quarterly files) | Coding rules in the scrubber; one planted code-pair effect | **Unverified** (download Day 1) |
| CMS ICD-10-CM and HCPCS Level II code files | Code validation, diagnosis-procedure tables | **Unverified** (download Day 1) |
| NPHIES implementation guide | Field mapping note only | **Unverified** |
| Kuwait AFYA study (3.85% rejection) | Sanity reference only, never a target | **Unverified** (citation not yet checked) |

CPT descriptors are AMA-licensed: codes only, no copied descriptions.

## 5. Simulator (`src/generator.py`)

Seeded and driven by `config/sim.yaml`.

**Tables produced:** `members` (plan, eligibility periods), `providers`, `payers` (filing limit, authorisation rules, strictness), `claims`, `activities`, `prior_auths`, `remittances` (one row per line per remittance round, with paid amount and denial code), `resubmissions`.

**Denial mechanisms** (one function each, so each is testable):

| Group | Mechanism | Avoidable before submission? |
|---|---|---|
| Eligibility | Service date outside coverage | Yes, rule-checkable |
| Authorisation | Prior approval required, missing or expired | Yes, rule-checkable |
| Coding | NCCI PTP conflict, MUE unit breach, invalid ICD code | Yes, rule-checkable |
| Duplicate | Same member, code and date already billed | Yes, rule-checkable |
| Timely filing | Submitted after the payer's filing limit | Yes, rule-checkable |
| Price | Billed above contract price → partial payment | Yes, rule-checkable |
| Medical necessity | Diagnosis weakly supports the procedure; strictness varies by payer and doctor | Partly: probabilistic, the ML's job |
| Non-covered | Service excluded on the member's plan tier | Partly |
| Noise | Random adjudication inconsistency | No. This sets the ceiling. |

**Planted effects.** Sizes and the change month are drawn from ranges by a sealed seed:
1. One payer is much stricter on medical necessity for physiotherapy.
2. Missing prior authorisation for high-cost radiology at one facility.
3. One real NCCI code pair billed often by one department.
4. **Payer behaviour change:** one payer starts requiring prior authorisation for one service line from a hidden month.
5. One payer pays slowly from a hidden month.
6. One doctor with weak documentation (more medical-necessity denials).

**Sealing.** The answer key and the per-line true denial probabilities are written to `data/raw/sealed/`. Only `src/score.py` may read that folder, and `tests/test_sealed.py` fails if any other file in `src/` or `sql/` refers to it.

**Why mix-adjusted denial rates matter (one paragraph in REPORT.md):** a payer that covers mostly high-denial services (e.g. physiotherapy) will show a high raw denial rate even if it treats each service exactly like other payers. The scorecard therefore shows each payer's **expected denial rate given its service mix** next to its actual rate. The gap, not the raw rate, is what to raise in contract talks.

## 6. Method

### 6.1 Validate and load (`src/validate.py`, `src/build_db.py`)
Checks: codes in valid lists, payment date ≥ submission date, remittance totals reconcile to claim totals, no orphan lines, duplicates and amount outliers flagged. Output: a data-quality table in the report, and clean tables loaded into `data/gold/denialguard.duckdb`.

### 6.2 SQL KPI layer (`sql/`), the core
| File | Content |
|---|---|
| `01_staging.sql` | Typed staging views over the clean tables |
| `02_marts.sql` | Star schema: `fact_claim_line`, `fact_remittance`, `dim_payer`, `dim_service_line`, `dim_provider`, `dim_date`, `dim_denial_code` |
| `03_kpis.sql` | Clean claim rate, first-pass yield, initial denial rate by count and by AED value, avoidable-denial share, A/R days, resubmission overturn rate, median days to payment, monthly and by every dimension |
| `04_scorecard.sql` | Payer scorecard: volume, denial rate (count, value), mix-adjusted expected rate, overturn rate, median days to pay, share paid within the directive timeline (only if verified) |

Every KPI has a written definition (numerator, denominator, grain, date used) in `sql/KPI_DEFINITIONS.md`. The same definitions are used for the DAX. `tests/test_kpis.py` checks each KPI against a hand-calculated 20-line mini dataset.

### 6.3 Rules vs ML (`src/scrubber.py`, `src/model.py`)
- **Scrubber:** deterministic edits for eligibility, authorisation, NCCI/MUE, duplicate, timely filing, price and plan exclusions. Each flag carries a reason code. Unit tests cover every rule.
- **Models:** baseline (historical denial rate by payer × service line), logistic regression, LightGBM.
- **Leakage control:** only fields known before submission. Time split: train months 1–15, validation 16–18, test 19–24. `tests/test_leakage.py` fails if any remittance-side column reaches the features.
- **Evaluation:** AUC, AUC-PR, Brier score and a calibration curve per model, next to the **best achievable** values from the true probabilities (computed in `score.py`). SHAP summary for LightGBM.

### 6.4 Worklist: AED recovered per coder hour (`src/worklist.py`)
- Capacity and effort are fixed in `config/review.yaml`: number of coders, hours per day, minutes per reviewed line, and the share of avoidable denials a coder fixes once flagged. These are assumptions, stated as such in the report.
- Every test-period day, each policy fills the capacity with its top-ranked lines: **rules only, LR, LightGBM, rules first then LightGBM.**
- Recovered AED = denied amount on reviewed lines whose denial was avoidable × fix rate. "Avoidable" is known from the generator, so this is scored in `score.py`.
- Reported: AED recovered per coder hour and total AED recovered, with bootstrap 95% CIs (resampling days). If ML adds little over rules, that is the finding.

### 6.5 Payer-behaviour change detector (`src/detect_change.py`)
- Series: weekly authorisation-denial rate per payer × service line.
- Method: one-sided CUSUM on the weekly rate, with the baseline estimated from the first 26 weeks. The threshold is chosen before scoring. Compared with a naive rule: rate above 2× its trailing 8-week mean.
- Scored in `score.py` against the hidden change: **weeks to detect** (alert week minus true change week), and **false alarms** (alerts on series with no planted change, plus alerts on the changed series before the change).

### 6.6 Power BI handoff (`src/export_powerbi.py` → `reports/powerbi/`)
| File | Content |
|---|---|
| `fact_claim_line.csv`, `fact_remittance.csv`, `dim_*.csv` | Star schema exported from the DuckDB marts (CSV, UTF-8, ISO dates, integer surrogate keys) |
| `MODEL.md` | Step-by-step import: load order, data types per column, every relationship (from/to column, cardinality, single direction), marking `dim_date` as a date table, inactive relationships for submission and payment dates (activated with `USERELATIONSHIP`) |
| `MEASURES.md` | DAX for every KPI in 6.2, with a display folder, format string and a one-line definition matching `KPI_DEFINITIONS.md` |
| `LAYOUT.md` | Two pages, specified visual by visual: type, fields per well, sort, filters, conditional formatting, canvas position. **Page 1, RCM overview:** KPI cards, monthly denial value trend, denied AED by denial group, matrix of service line × payer, slicers. **Page 2, payer scorecard:** scorecard table with conditional formatting, weekly authorisation-denial rate for the selected payer with the detected change marked, days to payment by payer. |
| `expected_values.csv` | KPI values computed in SQL for given filter combinations, so you can check your DAX gives the same numbers |

### 6.7 Report (`reports/REPORT.md`)
A memo to an RCM director. In order: the data-honesty note; three headline findings; where revenue leaks (AED); what to review first and what it is worth per coder hour; which payer changed and when we would have known; the payer scorecard; the answer-key scoring table; limitations. Every number comes from a run, and is copied from `reports/metrics.json`, which the pipeline writes.

## 7. Folder structure

```
config/          sim.yaml, review.yaml
data/reference/  downloaded public files + SOURCES.md (URL, date, hash, verified status)
data/raw/        generator output; sealed/ (answer key, true probabilities — score.py only)
data/clean/      validated tables + data-quality table
data/gold/       denialguard.duckdb
docs/            data_dictionary.md (eClaimLink fields, NPHIES mapping note)
sql/             01_staging.sql … 04_scorecard.sql, KPI_DEFINITIONS.md
src/             reference.py, generator.py, validate.py, build_db.py, scrubber.py, features.py,
                 model.py, worklist.py, detect_change.py, export_powerbi.py, score.py, run_all.py
tests/           test_generator.py, test_validate.py, test_kpis.py, test_scrubber.py,
                 test_leakage.py, test_sealed.py
reports/         REPORT.md, metrics.json, figures/, powerbi/
```

`python -m src.run_all` rebuilds everything from the seed. There are no notebooks in the core version; figures are made by scripts.

## 8. Six-day plan

| Day | Work | Done when |
|---|---|---|
| 1 | Verify and download sources; fill `SOURCES.md`; schema + data dictionary; read the Dubai directive | Every source marked verified / unverified / not found; every field has a source or a stated assumption |
| 2 | Generator with all mechanisms, remittance and resubmission rounds, planted effects, sealing | Same seed → identical output; each mechanism produces denials; sealed-folder test passes |
| 3 | Validation, DuckDB load, SQL marts, KPIs, scorecard, `KPI_DEFINITIONS.md` | Remittances reconcile; KPI tests pass on the mini dataset |
| 4 | Scrubber, baseline, LR, LightGBM, calibration, SHAP | Leakage test passes; models compared with baseline and ceiling |
| 5 | Worklist simulation, change detector, Power BI export + `MODEL.md`, `MEASURES.md`, `LAYOUT.md`, `expected_values.csv` | AED per coder hour with CIs; detection lag and false alarms computed |
| 6 | `score.py` unseals the key; REPORT.md memo; full rerun; tests; resume bullets from `metrics.json` | One command rebuilds everything; all tests green |

## 9. Definition of done

- `python -m src.run_all` and `pytest` both run cleanly from an empty `data/` folder.
- Only `score.py` reads the sealed folder, and a test enforces it.
- Models are reported next to the baseline, the rule scrubber and the best achievable score.
- AED per coder hour is reported for all four policies, with CIs, whichever policy wins.
- Every number in REPORT.md and the resume bullets traces to `reports/metrics.json`.
- The Power BI files are complete enough to build both pages without guessing, and `expected_values.csv` lets you check the DAX.

## 10. Limitations (said first in the report)

- The claims are simulated. Results show how well the **method** works on data with known structure, not real denial rates or real payer behaviour.
- NCCI/MUE are US Medicare edits. UAE payers' own edit sets are not public; NCCI is a realistic stand-in, not their rules.
- Review capacity, coder minutes per line and fix rate are assumptions. The AED figures scale with them.
- Real adjudication is messier than any simulator: undocumented payer rules, contract changes, adjudicator habits.

## 11. Do not claim

- Real UAE or Saudi denial rates, or that any real insurer or TPA behaves like a simulated payer.
- That the data came from a hospital, insurer or TPA.
- That the scrubber reproduces DHA's, NPHIES's or any payer's actual edit engine.

## 12. Future work (parked from the 7 to 9 day plan)

- Decoy patterns and a Simpson's-paradox trap in the answer key (the mix-adjusted rate in the scorecard keeps the core idea).
- Kaplan-Meier / Cox time-to-payment models (replaced by median days to payment in SQL).
- Kitagawa decomposition of denial-rate changes into mix vs rate; mixed-effects payer model.
- Resubmission prioritisation model (probability of overturn × amount).
- Sensitivity runs at different base denial rates.
- Streamlit pre-submission checker and worklist app.
- Auto-generated monthly denial-management pack.
- FHIR R4 `Claim` / `ClaimResponse` export (NPHIES standard).
- LLM classifier for free-text remittance comments.
- GitHub Actions CI.

## 13. Resume bullets

Written only at the end of Day 6, from `reports/metrics.json`: one SQL/KPI bullet, one ML bullet in AED terms, and one Power BI bullet. No placeholders get filled with numbers that weren't run.

## 14. Interview story

At TUV Rheinland I checked products against GSO, SFDA and MoIAT requirements before submission, because a rejected file costs weeks. Claim scrubbing is the same problem in a hospital. I built it the way a compliance team would: hard rules for what can be checked for certain, a model only for the judgement calls, and an honest measure of what the model adds in AED and coder time.
