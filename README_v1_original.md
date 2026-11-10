# Project E (optional): Healthcare Claims Denial Analysis

**Status:** Not started | **Data:** SIMULATED (Gulf-style structure); optional real US reference data | **Effort:** about 4 days
**Build this only if** you are targeting hospital revenue-cycle or insurer roles.
**Target roles:** hospital medical insurance and RCM, payers, healthcare analytics

> **Data honesty:** no public Saudi or UAE claims or denial data was found. Claims here are simulated using the field structure of published eClaimLink and NPHIES formats. State this in the first lines of every report.

## 1. Business question

Which claims are likely to be denied before submission, which insurers, services and codes drive denials, and where does revenue leak?

Context: Dubai's claims-management directive (effective 16 November 2025) sets requirements for denial codes, remittance advice and payment timelines. A Kuwait AFYA study reported an overall rejection rate of 3.85%, with uncovered services and insufficient clinical justification as common reasons. Use these as sanity references only.

## 2. Data

| Source | What | Notes |
|---|---|---|
| Simulated claims (you build the generator) | About 100K claims, 6 insurers, 10 service lines | Fields: insurer, service category, diagnosis and procedure codes, amount, authorisation status, denial code, submission and payment dates. |
| eClaimLink code sets (https://www.eclaimlink.ae) | Published code lists (for example denial codes) | Use to make field values realistic. |
| Optional: public US claims-denial reference data | Real denial rates by issuer | I have not verified the file location; check before relying on it. |

Plant known effects with an answer key: one insurer with a high denial rate for a service line, a missing-authorisation pattern, a code-pair that always fails, and a payment delay for one insurer.

## 3. Setup (PowerShell)

```powershell
cd projects\e-claims-denial-analysis
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4. Folder structure

```
data/raw/        generator output and answer key
data/clean/      validated claims table
notebooks/       01_generate, 02_clean, 03_eda, 04_stats, 05_model
src/             generator.py, validate.py, features.py, model.py
tests/           test_generator.py, test_validate.py
reports/         figures and REPORT.md
```

## 5. Tasks

### Phase 1: Generate (Day 1)
- [ ] Define the schema from eClaimLink and NPHIES-style fields.
- [ ] Write a seeded `src/generator.py` with the planted effects; save the answer key.
- [ ] Tests: reproducible output; planted effects present.

### Phase 2: Clean and validate (Day 1 to 2)
- [ ] Code validation (diagnosis and procedure codes in allowed lists).
- [ ] Duplicate claim detection; amount outliers; date logic (payment after submission).
- [ ] Build a data-quality table.

### Phase 3: Explore (Day 2)
- [ ] Denial rate by insurer, service, authorisation status and month.
- [ ] Revenue at risk (amount x denial) by driver.

### Phase 4: Statistics (Day 2 to 3)
- [ ] Chi-square and logistic regression of denial on insurer, service and authorisation; correct for multiple comparisons.
- [ ] Kaplan-Meier and Cox models for days-to-payment by insurer.
- [ ] Decomposition of the denial-rate change across insurers and services (Kitagawa, as in your Funnel Detective project).

### Phase 5: Model (Day 3 to 4)
- [ ] Baseline: denial rate by insurer and service.
- [ ] Logistic regression and LightGBM for pre-submission denial risk.
- [ ] Time-based train and test split (avoid leakage).
- [ ] Calibration curve; threshold chosen by cost (cost of review vs cost of denial).
- [ ] SHAP for denial drivers.
- [ ] Check whether the planted effects are recovered.

### Phase 6: Write up (Day 4)
- [ ] `reports/REPORT.md` with findings, recommended pre-submission checks, and limits.

## 6. Definition of done

- Generator is seeded and tested; answer key kept separately.
- Model beats the baseline on a time-based holdout, or the report says it did not.
- The first line says the data is simulated.

## 7. Limitations

- Results show how the method performs on simulated data, not real denial rates.
- Real denial reasons are more varied than any simulator.

## 8. Do not claim

- Real Saudi or UAE denial rates.
- That the data came from a hospital or insurer.

## 9. Resume line template

> Built a seeded claims simulator and denial-risk pipeline (logistic regression and LightGBM; AUC [x] on a time-based holdout); recovered [N] of [N] planted denial drivers; estimated days-to-payment by insurer with survival models.
