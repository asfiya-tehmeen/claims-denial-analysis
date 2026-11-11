# Project E: DenialGuard — Claims Denial Analytics for UAE Medical Insurance

**Status:** Core build and Power BI dashboard done (2026-11-11). | **Data:** HYBRID (simulated claims; real public code sets and edit rules)
**Target roles:** medical insurance / claims / RCM / denial-management analyst at UAE insurers, TPAs and hospital groups
**Earlier plans:** [`README_v1_original.md`](README_v1_original.md) (4-day first draft), [`README_v2_extended.md`](README_v2_extended.md) (7 to 9 day version; parked items listed under Future work)

> **Data honesty:** claims are **simulated** using the published DHA eClaimLink field structure (NPHIES mapping note in [`docs/data_dictionary.md`](docs/data_dictionary.md)). Code sets and edit rules come from real public sources listed in [`data/reference/SOURCES.md`](data/reference/SOURCES.md), each marked verified or unverified. No result here describes real UAE or Saudi denial rates.

## The pitch

Every hospital already runs a claim scrubber. The questions an RCM director asks are: *where is revenue leaking, what does a model add on top of the scrubber, which claims should my coders review today, and which payer changed its behaviour?* This project answers them with the tools these job descriptions name: **SQL, Power BI, claims data and denial management.**

**Read the memo first:** [`reports/REPORT.md`](reports/REPORT.md). **Open the dashboard:** [`reports/powerbi/DenialGuard.pbix`](reports/powerbi/DenialGuard.pbix).

## Dashboard (Power BI)

Two pages built on a star schema (3 fact tables, 5 dimensions, 25 DAX measures):

- **RCM Overview:** KPI cards for net billed, initial and final denial rates, avoidable share, clean claim rate and median days to payment, plus denied AED by month, revenue lost by denial category, a service line × payer denial-rate matrix and A/R days at month-end. Slicers for date, payer, service line and facility.
- **Payer Scorecard:** each payer's actual vs mix-adjusted expected denial rate, PD-05-2025 payment timeliness and late-payment fees; the weekly authorisation-denial trend with the change-detector alerts; median days to payment by month. It opens on the payer and service line whose authorisation rule changed.

Every number on the dashboard was checked against the SQL layer: **274 of 274 values match** ([`measure_check.csv`](reports/powerbi/measure_check.csv)).

| RCM Overview | Payer Scorecard |
|---|---|
| ![RCM Overview](reports/figures/powerbi_page1.png) | ![Payer Scorecard](reports/figures/powerbi_page2.png) |

## Results (from `reports/metrics.json`; simulated data)

| What | Result |
|---|---|
| Data | 55,309 claims / 135,706 claim lines / 143,795 remittance rows, 6 fictional payers, 7 service lines, 24 months |
| Revenue leakage | 13.1% of net billed denied initially, 10.1% still lost after resubmission (AED 4.14M of AED 41.1M). 86% of initially denied AED is in avoidable categories. |
| Rules vs ML (time-based holdout, months 19–24) | Scrubber AUC 0.846 / AUC-PR 0.496 · LightGBM 0.902 / 0.794 · **best achievable 0.916 / 0.818** |
| **AED recovered per coder hour** (1 coder, 45 lines/day) | Rules **AED 375** (95% CI 311–447) · LightGBM **AED 393** (330–465) · uplift **+AED 19 (CI +11 to +28)**, about 5%, at every capacity tested. **ML adds little over a good rule set, and that is the finding.** |
| Payer change detection | Planted authorisation change caught 10 weeks after it took effect (3 weeks after the first denied remittance arrived), at 0.35 false alarms a month. The naive "rate doubled" rule raised 2.1 a month. |
| Payer scorecard | One payer settles only 37% of claims within PD-05-2025's 45 days (median 55 days, AED 30K late-payment fees due). The mix-adjusted denial rate ranges from 0.88× to 1.19× expected. |
| Answer key (unsealed last) | **5 of 6** planted effects recovered. The miss, a poorly documenting doctor at rank 4, was masked by a facility effect; this is explained in the memo, not tuned away. |
| Data quality | 16 validation checks. Every planted export problem was found (288/288 duplicate rows, 136/136 bad amounts, 136/136 amount mismatches, 28/28 bad dates). |
| Power BI | 2-page dashboard on an 8-table star schema (3 facts, 5 dimensions) with 25 DAX measures. **274 of 274** DAX check values match the SQL results. |
| Reproducibility | `python -m src.run_all` rebuilds everything in ~75 s. Two full runs agree on all 713 metrics. 39 tests pass. |

## How to run (PowerShell)

```powershell
cd projects\e-claims-denial-analysis
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.run_all        # downloads CMS reference files on first run (~70 MB), then rebuilds everything
pytest                       # 39 tests
```

## What's in it

| Step | Code | Output |
|---|---|---|
| Real reference data | `src/reference.py` | CMS ICD-10-CM FY2027, Medicaid NCCI PTP practitioner edits (2026-10-01), Medicare MUE table (Q4 2026). Gitignored, because CPT codes are AMA-licensed. |
| Simulator | `src/generator.py`, `config/sim.yaml`, `config/catalog.yaml` | Line-level claims, prior auths, remittance rounds (initial / resubmission / reconciliation), partial payments, planted effects, sealed answer key, planted export problems |
| Validation | `src/validate.py` | `data/clean/*.parquet`, `data/clean/data_quality.csv` |
| Rule scrubber | `src/scrubber.py` | 13 rules with a suggested fix each: eligibility, auth, NCCI/MUE, invalid ICD, duplicate, timely filing, price, plan exclusion, benefit limit, medical necessity |
| **SQL KPI layer** | `sql/01_staging.sql` … `sql/05_series.sql`, `sql/KPI_DEFINITIONS.md`, `src/build_db.py` | DuckDB star schema, KPI cube, leakage, timeliness (PD-05-2025), A/R days, mix-adjusted payer scorecard, weekly series |
| Models | `src/features.py`, `src/model.py` | Baseline, logistic regression, LightGBM; calibration and SHAP figures |
| Worklist | `src/worklist.py` | Daily review lists under fixed capacity (blind to outcomes) |
| Change detection | `src/detect_change.py` | Binomial CUSUM on weekly auth denials; Gaussian CUSUM on days to payment; naive baseline |
| Drivers | `src/drivers.py` | Payer / facility / clinician cells vs peers with Benjamini-Hochberg; code-pair ranking |
| **Power BI** | `src/export_powerbi.py`, `reports/powerbi/` | Star-schema CSVs, [`MODEL.md`](reports/powerbi/MODEL.md), [`MEASURES.md`](reports/powerbi/MEASURES.md) (25 DAX measures), [`LAYOUT.md`](reports/powerbi/LAYOUT.md) (2 pages, with as-built notes), `expected_values.csv` (274 check values), **`DenialGuard.pbix`** and the Power BI Project source (`pbip/`, TMDL model plus PBIR report), `measure_check.csv` (DAX vs SQL: 274/274) |
| Scoring | `src/score.py` | The **only** reader of `data/raw/sealed/`: ceiling, AED per coder hour with bootstrap CIs, detection lag, answer-key table |
| Memo | `src/report.py` | [`reports/REPORT.md`](reports/REPORT.md), with every number taken from `reports/metrics.json` |

Tests: `test_kpis` (SQL vs a hand-calculated 20-line dataset), `test_scrubber` (every rule on hand-written claims), `test_generator` (same seed gives the same output, every mechanism fires, planted change present), `test_validate` (all planted export problems found), `test_leakage` (features unchanged when outcomes are flipped), `test_sealed` (only `score.py` reads the answer key), `test_detect`, `test_reference`.

## Source verification (summary; details in `data/reference/SOURCES.md`)

| Source | Status |
|---|---|
| DHIC PD-05-2025 claims-management directive | **Verified text** (archived official PDF). Current status unconfirmed: the live ISAHD link returns 404. |
| DHA GC 06/2018 denial-code updates | **Verified** (official circular) |
| Other eClaimLink denial-code descriptions | Secondary (HCX/Shafafiya-derived lists) |
| Shafafiya field names (DOH Abu Dhabi) | Verified for DOH. Assumed identical for DHA eClaimLink. |
| CMS NCCI PTP / MUE / ICD-10-CM files | **Verified** (downloaded, hashed, parsed) |
| Kuwait AFYA study (3.85% rejection rate) | Verified (sanity reference only) |
| NPHIES profiles | Unverified (mapping note only) |

## Limitations

- The claims are simulated. Results show how well the **method** works on data with known structure, not real denial rates or payer behaviour.
- The answer key is blind to the code, not to me: I wrote the generator, so I knew the effect *types*, though not their sizes, targets or dates. The detectors are generic, and thresholds were fixed before scoring.
- NCCI/MUE are US Medicare/Medicaid edits, used as a realistic stand-in for UAE payers' private edit sets.
- The AED figures scale with the review assumptions in `config/review.yaml` (capacity, minutes per line, fix rates).
- The Power BI file reads the CSVs from absolute paths. After cloning, run `python -m src.run_all`, then repoint the sources (see `reports/powerbi/MODEL.md` §7).

## Do not claim

- Real UAE or Saudi denial rates, or that any real insurer or TPA behaves like a simulated payer.
- That the data came from a hospital, insurer or TPA.
- That the scrubber reproduces DHA's, NPHIES's or any payer's actual edit engine.

## Future work (parked)

- Decoy patterns and a Simpson's-paradox trap in the answer key (the mix-adjusted scorecard keeps the core idea).
- Kaplan-Meier / Cox time-to-payment models (median days to payment in SQL instead).
- Kitagawa decomposition, a mixed-effects payer model, and within-facility clinician comparison (the fix for the one missed effect).
- Resubmission prioritisation model; sensitivity runs at other base denial rates.
- Streamlit pre-submission checker, monthly denial pack, FHIR R4 `Claim`/`ClaimResponse` export, LLM remittance-comment classifier, GitHub Actions CI.

## Interview story

At TUV Rheinland I checked products against GSO, SFDA and MoIAT requirements before submission, because a rejected file costs weeks. Claim scrubbing is the same problem in a hospital. I built it the way a compliance team would: hard rules for what can be checked for certain, a model only for the judgement calls, and an honest measure of what the model adds in AED and coder time. The answer was "about 5%", and I can show why.
