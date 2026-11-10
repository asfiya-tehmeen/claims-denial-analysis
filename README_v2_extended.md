# Project E: DenialGuard — Stopping Claim Denials Before Submission

**Status:** Not started | **Data:** HYBRID (simulated claims; real public code sets, edit rules and benchmarks) | **Effort:** about 7 days core + 2 stretch
**Target roles:** hospital RCM / medical insurance / denial management analyst, payer claims analytics, TPA operations (NAS, Nextcare, MedNet, Daman, Bupa Arabia, Tawuniya), healthcare data analyst at hospital groups (SEHA, M42, Mediclinic, Aster, NMC)
**Original plan:** kept in [`README_v1_original.md`](README_v1_original.md)

> **Data honesty:** no public Saudi or UAE claim-level data exists. Claims are **simulated** using the field structure of the published DHA eClaimLink and Saudi NPHIES formats. Code sets, claim-edit rules and calibration benchmarks come from **real public sources** (listed in Section 4). This sentence goes in the first lines of every report, the app and the LinkedIn post.

## 1. Why this version is different

Most claims-denial portfolio projects take a Kaggle table, predict "denied yes/no", and report an AUC. An RCM manager does not need that. Every hospital already has a claim scrubber. The questions they ask are: *what does a model add on top of our scrubber, which claims should my coders look at today, which denials are worth resubmitting, and which payer is changing its behaviour?* This project answers those questions.

Five things set it apart:

1. **A realistic workflow, not one label.** It simulates the full eClaimLink/NPHIES cycle at the **activity (line) level**: submission → remittance advice (full, partial or no payment per line) → resubmission → final payment. Denial codes follow the published eClaimLink categories (eligibility, authorisation, coding, medical necessity, non-covered, duplicate, timely filing, price). Most projects model whole claims. Real payers deny individual lines.
2. **Rules vs ML vs both, measured in money.** It builds a rule-based scrubber from **real CMS NCCI procedure-to-procedure and MUE edits**, then tests whether a LightGBM model catches the denials the rules miss. The headline metric is **AED recovered per coder hour** under a fixed review capacity, not AUC.
3. **A ceiling you can trust.** Because the generator knows each claim's true denial probability, the report gives the **best AUC and Brier score any model could reach** and how close the real model gets. Some denials are pure noise on purpose, as in real adjudication. No other portfolio project can report this, and it heads off the usual "you only found what you planted" objection.
4. **A blind answer key, with decoys.** The generator draws the size and location of planted effects from a sealed seed. Analysis code never reads the answer key until a final scoring step. Decoy patterns (a Simpson's-paradox mix effect, a high-volume insurer that only *looks* bad) check that the method does not chase false drivers.
5. **Shaped like the job.** Standard RCM KPIs in SQL (clean claim rate, first-pass yield, denial rate by count and by value, avoidable-denial share, A/R days, resubmission overturn rate), a payer scorecard checked against the payment timelines in Dubai's claims-management directive, and a Streamlit **pre-submission checker** that shows risk, reasons and a suggested fix for each claim line.

## 2. Business questions

| # | Question | Who asks it |
|---|---|---|
| Q1 | Where does revenue leak? Which payers, service lines, doctors and denial categories account for the most denied value, and how much of it was avoidable? | RCM director, CFO |
| Q2 | Before submission, which claim lines will be denied, and what does an ML model catch that our rule scrubber misses? | Claims / coding manager |
| Q3 | With a fixed team of coders, which claims should be reviewed today to recover the most money? | Denial management lead |
| Q4 | After denial, which lines are worth resubmitting (likelihood of being overturned × amount)? | Denial management, billing |
| Q5 | Is a payer changing its behaviour (a new authorisation rule, slower payment), and how soon can we detect it? Are payers paying within the regulated timelines? | Managed-care contracting, payer relations |

Q2 and Q3 are the headline. Everything else feeds them.

## 3. Scope

- **Market:** Dubai-style (DHA eClaimLink) as the main format. Every field is mapped to its NPHIES (KSA) equivalent in the data dictionary, so the same project works for Saudi applications.
- **Volume:** about 150K claims / about 450K activity lines, 24 months, 1 hospital group with 3 facilities, 8 payers (insurers and TPAs, fictional names), 12 service lines (outpatient, inpatient, emergency, radiology, lab, pharmacy, dental, physiotherapy, maternity, day surgery, ophthalmology, dermatology).
- **Codes:** ICD-10-CM diagnoses, CPT/HCPCS activities (eClaimLink uses CPT; NPHIES uses ICD-10-AM and SBS/ACHI, documented as a mapping note, not simulated twice).

## 4. Data

### 4.1 Real public sources (used for rules and calibration, not as claims)

| Source | What it gives | Used for |
|---|---|---|
| CMS NCCI procedure-to-procedure (PTP) edits and Medically Unlikely Edits (MUE), quarterly files | Real code pairs that cannot be billed together; maximum units per code per day | Scrubber rules; the "code pair that always fails" effect becomes a *real* edit |
| CMS ICD-10-CM code files | Valid diagnosis codes, billable vs header codes | Code validation; diagnosis-procedure medical-necessity tables |
| HCPCS Level II files (CMS, free) | Valid HCPCS codes | Code validation |
| DHA eClaimLink published denial codes and claim/remittance XML schema (https://www.eclaimlink.ae) | Denial code list and categories, field names, resubmission types | Field structure and denial-code values (**verify the current list before use**) |
| NPHIES implementation guide (FHIR R4 based) | KSA claim and ClaimResponse structure | Field mapping; stretch FHIR export |
| CMS Transparency in Coverage public-use file (HealthCare.gov issuers) | Real claim denial counts by issuer, including denial-reason groups | Calibrating the spread of denial rates *across payers* (US, used for shape only) |
| CMS CERT improper-payment reports | Error mix: insufficient documentation, medical necessity, incorrect coding | Calibrating the *mix* of denial categories |
| Kuwait AFYA study (3.85% rejection) and Dubai claims-management directive (effective 16 Nov 2025) | Gulf sanity references; payment timeline requirements | Sanity bands; payment-timeline compliance in the payer scorecard |

CPT descriptors are AMA-licensed. Use codes only, with no copied descriptions, and say so in the data dictionary.

### 4.2 Simulator (`src/generator.py`)

Entities: `members` (policy, plan tier, eligibility periods), `providers` (facility, doctor, specialty), `encounters`, `claims`, `activities`, `prior_auths`, `remittances`, `resubmissions`. Configuration lives in `config/sim.yaml`. The default overall initial denial rate is about 10% by value. The whole analysis is re-run at 4% and 15% to show that the conclusions hold.

**Denial mechanisms.** Each one is a separate, documented process:

| Category (eClaimLink-style) | Mechanism | Pre-submission detectable? | Who catches it |
|---|---|---|---|
| ELIG | Service date outside the member's coverage period | Yes, fully | Rules |
| AUTH | Service needs prior approval for this payer and plan; none, expired, or wrong code | Yes, fully | Rules |
| CODE | NCCI PTP conflict, MUE unit breach, invalid or header ICD code | Yes, fully | Rules |
| DUPL | Same member, code and date already submitted | Yes, fully | Rules |
| TIME | Submitted after the payer's filing limit | Yes, fully | Rules |
| MNEC | Diagnosis does not support the procedure; strictness varies by payer and doctor | Partly (probabilistic) | **ML** |
| NCOV / BENX | Service excluded on some plan tiers; benefit limits exhausted | Partly | Rules + ML |
| PRCE | Billed above contracted price | Yes | Rules |
| Noise | Random adjudicator inconsistency | No | Nobody (sets the ceiling) |

**Planted effects (sealed answer key, `data/raw/answer_key.json`):**
1. One payer is much stricter on MNEC for one service line (e.g. physiotherapy).
2. A missing-authorisation pattern for high-cost radiology.
3. A real NCCI code pair billed often by one department.
4. **A policy change:** one payer starts requiring authorisation for a service from a set month (tests Q5 detection lag).
5. A payment delay for one payer that starts mid-period (survival analysis, timeline compliance).
6. One doctor with poor documentation (higher MNEC) inside an otherwise good department.
7. **Decoy:** a high-volume payer whose overall denial rate is high only because of its service mix (Kitagawa should show it is mix, not rate).
8. **Decoy:** a feature correlated with denial only through a confounder (SHAP should not rank it as a driver).

Effect sizes are drawn from ranges by the sealed seed, so the analyst does not know them in advance.

## 5. Method

### 5.1 Pipeline and KPI layer
```
bronze  generator output + real reference files, never edited     (data/raw)
silver  validated activities, claims, remittances; DQ flags         (data/clean)
gold    DuckDB marts: fact_activity, dim_payer, dim_service, KPI views (data/gold)
```
- Data-quality checks in `pytest`: codes in valid lists, payment date ≥ submission date, remittance totals reconcile to claim totals, no orphan activities, duplicate detection, amount outliers. Results feed a **data-quality table** in the report.
- KPIs in plain SQL views with written definitions (`sql/kpis.sql`), following HFMA MAP Keys where one applies: clean claim rate, first-pass yield, initial denial rate (count and value), final write-off rate, avoidable-denial share, resubmission overturn rate, days in A/R, days to payment.

### 5.2 Rule scrubber (`src/scrubber.py`)
Deterministic edits (ELIG, AUTH, CODE via NCCI/MUE, DUPL, TIME, PRCE, plan exclusions). Each fired rule returns a reason and a **suggested fix** ("add modifier / split claim", "obtain prior approval", "check eligibility"). Unit tests run on hand-written claims for every rule.

### 5.3 Denial-risk model (`src/model.py`)
- **Leakage control:** only fields known **before submission**. A test fails if any remittance-side column reaches the feature matrix. Time-based split (train months 1–16, validate 17–19, test 20–24); members grouped so the same patient never appears in both train and test.
- Models: (a) baseline = historical denial rate by payer × service; (b) regularised logistic regression; (c) LightGBM; (d) **scrubber + LightGBM on the lines the scrubber passes**.
- Evaluation: AUC-PR (denials are rare), Brier score, calibration curve (isotonic if needed), all **next to the best achievable value** from the generator's true probabilities.
- SHAP for drivers, compared against the answer key (recovered / missed / decoy falsely flagged).
- Robustness: performance after the planted policy change (does the model degrade? how fast does retraining recover it?).

### 5.4 Decision layer: the coder worklist (Q3)
- Expected loss per line = P(deny) × amount × (1 − P(recovered on resubmission)) − review cost.
- Capacity-constrained: e.g. 3 coders × 60 reviews/day. Rank by expected loss and fill the capacity.
- Compare four policies on the test months: no review, rules only, ML only, rules + ML. Report **AED protected per coder hour** and denied value avoided, with bootstrap confidence intervals.

### 5.5 Back-end: resubmission prioritisation (Q4)
Model P(overturn | denial code, payer, service, documentation available). Rank denied lines by expected recovered amount minus rework cost; compare with "resubmit everything above X AED".

### 5.6 Payer analytics (Q1, Q5)
- Logistic regression of denial on payer, service, authorisation and doctor (mixed effects: random intercept per doctor), with Benjamini-Hochberg correction.
- **Kitagawa decomposition** of the month-over-month denial-rate change into mix vs rate (should expose decoy 7).
- **CUSUM / control charts** per payer × denial category: how many weeks after the planted policy change does an alert fire, and how many false alerts per month does it raise?
- **Kaplan-Meier and Cox models** for days to payment by payer; share of claims paid inside the directive's timeline; payer **scorecard** (denial rate, overturn rate, days to pay, timeline compliance) as a one-page brief for contract negotiation.

### 5.7 Stretch
- Export a sample of claims as **FHIR R4 `Claim` / `ClaimResponse`** resources (the NPHIES standard), validated against the base FHIR schema.
- LLM classifier that maps free-text remittance comments to root-cause categories, compared with keyword rules on 300 hand-labelled comments (F1 and cost per 1,000), as in Project C.
- Power BI version of the RCM dashboard (many Gulf hospital teams use Power BI).

## 6. Deliverables

| Deliverable | Audience |
|---|---|
| `reports/REPORT.md`: data honesty and limitations first, then revenue leakage, rules vs ML, worklist value, payer findings, answer-key recovery table | Hiring manager, technical reviewer |
| `reports/denial_pack_YYYY-MM.md`: auto-generated monthly denial-management pack (top leakage drivers, payer alerts, recommended front-end fixes by owner: registration, authorisation team, coding, doctors) | Shows you know the monthly RCM meeting |
| `reports/payer_scorecard.md`: one page per payer | Managed-care contracting |
| Streamlit app: (1) RCM KPI dashboard, (2) pre-submission checker (pick or upload a claim → risk, scrubber hits, SHAP reasons, suggested fix), (3) today's coder worklist | 2-minute interview demo |
| Data dictionary with eClaimLink ↔ NPHIES field mapping | Shows domain fluency for UAE *and* KSA roles |
| 1-page case study: "The payer that changed its rules: how fast would we have noticed?" | LinkedIn post, interview story |

## 7. Folder structure

```
config/          sim.yaml (payers, plans, rates, effect ranges), scrubber_rules.yaml
data/raw/        bronze: generator output, sealed answer_key.json, NCCI/MUE/ICD/HCPCS reference files
data/clean/      silver: validated tables, DQ flags
data/gold/       denialguard.duckdb
sql/             marts.sql, kpis.sql
notebooks/       01_generate, 02_validate, 03_eda_kpis, 04_payer_stats, 05_model, 06_worklist, 07_case_study
src/             generator.py, reference.py, validate.py, scrubber.py, features.py, model.py, worklist.py, payer_stats.py, pack.py
app/             streamlit_app.py
tests/           test_generator.py, test_validate.py, test_scrubber.py, test_leakage.py, test_kpis.py
reports/         figures, REPORT.md, denial packs, payer scorecards
```

## 8. Plan

| Phase | Days | Output | Done when |
|---|---|---|---|
| 1. Reference data + schema | 0.5 | NCCI/MUE/ICD/HCPCS loaded; eClaimLink denial codes checked; field dictionary with NPHIES mapping | Every simulated field has a source or a stated assumption |
| 2. Simulator | 1.5 | Seeded generator, all mechanisms, resubmission cycle, sealed answer key | Tests: same seed → identical output; each mechanism produces denials; overall rates inside the config bands |
| 3. Validate + KPI layer | 1 | Silver tables, DQ table, DuckDB marts, KPI views | Remittances reconcile; KPI tests pass on a hand-computed mini dataset |
| 4. EDA + payer stats | 1 | Leakage breakdown, mixed-effects model, Kitagawa, CUSUM, survival, scorecard | Decoy 7 correctly shown as a mix effect |
| 5. Scrubber + model | 1.5 | Rule engine, 4 models, calibration, SHAP, best-achievable comparison | Leakage test passes; model compared with baseline *and* the ceiling |
| 6. Worklist + resubmission | 0.5 | Four-policy comparison, AED per coder hour, resubmission ranking | Bootstrap CIs reported |
| 7. Product + write-up | 1 | Streamlit app, monthly pack generator, REPORT.md, case study; answer key unsealed and scored | `make all` (or `python -m src.run_all`) rebuilds everything from the seed |
| 8. Stretch | 2 | FHIR export, LLM remittance-comment classifier, Power BI, GitHub Actions CI | |

## 9. Definition of done

- One command regenerates data and rebuilds every table, figure and report.
- The answer key is read only by the final scoring step (a test enforces this), and the report shows recovered, missed and falsely flagged effects, decoys included.
- The model is compared with the baseline, the rule scrubber **and** the best achievable score. If ML adds little over rules, the report says so and gives the AED figure anyway.
- Conclusions are checked at 4%, 10% and 15% base denial rates.
- The first line of every report says the claims are simulated.

## 10. Limitations (say these first)

- The claims are simulated. Results show how well the **method** works on data with known structure, not real Gulf denial rates.
- Real denial behaviour is messier: undocumented payer rules, adjudicator habits, contract terms that change mid-year. The noise mechanism only partly stands in for that.
- NCCI edits are US Medicare rules. Gulf payers run their own edit sets, which are not public; NCCI is used as a realistic stand-in.
- Calibration benchmarks (US Transparency in Coverage, CERT, AFYA) come from different systems with different definitions of "denial". They set ranges, not targets.

## 11. Do not claim

- Real UAE or Saudi denial rates, or that any named insurer or TPA behaves like a simulated payer (all payer names are fictional).
- That the data came from a hospital, insurer or TPA.
- That the scrubber reproduces DHA, NPHIES or any payer's actual edit engine.

## 12. Resume line templates

> Built a healthcare claims denial-prevention pipeline on [450K] simulated eClaimLink-format claim lines with real CMS NCCI/MUE edits; a rules + LightGBM worklist protected AED [x] per coder hour vs AED [y] for rules alone under a fixed review capacity (time-based holdout).

> Denial-risk model reached AUC-PR [x] vs [y] baseline and [z] best achievable; recovered [N/N] planted denial drivers, rejected [2/2] decoys, and detected a simulated payer policy change within [N] weeks via CUSUM.

> Built an RCM KPI layer in DuckDB/SQL (clean claim rate, first-pass yield, denial rate by value, A/R days) and a Streamlit pre-submission checker; modelled days to payment by payer with Kaplan-Meier/Cox against Dubai's claims-management timelines.

## 13. Interview story (why you built it this way)

At TUV Rheinland my job was checking products against GSO, SFDA and MoIAT requirements before submission, because a rejected file costs weeks. Claim scrubbing is the same problem in a hospital: check each claim against the payer's rules *before* it goes out. So I built it the way a compliance team would: hard rules for what can be checked for certain, a model only for the judgement calls, and an honest measure of how much the model adds in money and coder time, not just in AUC.
