# KPI definitions

> Data honesty: claims are SIMULATED (DHA eClaimLink field structure). These definitions are what the SQL in `sql/03_kpis.sql` and `sql/04_scorecard.sql` computes, and what the DAX in `reports/powerbi/MEASURES.md` must reproduce. `tests/test_kpis.py` checks the SQL against a hand-calculated 20-line dataset.

Conventions
- **Line** = one eClaimLink activity. **Claim** = one encounter claim (one or more lines).
- **Net** = gross − patient share: the amount claimed from the payer.
- **Month** = service month, unless stated otherwise.
- **Initial** = first remittance advice (round 0). **Final** = after all resubmission rounds (max 2, PD-05-2025 §4.5c).
- Quarantined lines (see `data/clean/data_quality.csv`) are excluded everywhere.

| KPI | Numerator | Denominator | Grain | Date used | Notes |
|---|---|---|---|---|---|
| Clean claim rate | Claims with zero scrubber rule hits | Claims submitted | Claim | Service date | HFMA-style "passes edits with no manual intervention" |
| First-pass yield | Claims with no line denied (fully or partly) on the initial RA | Claims adjudicated | Claim | Service date | Partial (price) denials count as not first-pass |
| Initial denial rate (count) | Lines with initial denied amount > 0 | Lines adjudicated | Line | Service date | |
| Initial denial rate (value) | Σ initial denied AED | Σ net billed AED | Line | Service date | |
| Avoidable-denial share | Σ initial denied AED on codes marked `avoidable` in `dim_denial_code` | Σ initial denied AED | Line | Service date | Avoidable = a pre-submission check could normally have prevented it (analyst judgement per code, `config/denial_codes.yaml`) |
| Final denial rate (value) | Σ AED still unpaid after all rounds | Σ net billed AED | Line | Service date | Revenue actually lost |
| Resubmission overturn rate | Resubmitted lines paid (fully or partly) in a later round | Lines resubmitted at least once | Line | Service date | |
| Median days to payment | Median of (initial RA settlement date − claim submission date) | – | Claim | Service date | Claims with an invalid settlement date (DQ flag) excluded |
| % initial RA within 45 days | Claims whose initial RA came ≤ 45 calendar days after submission | Claims with a valid initial RA date | Claim × round | Settlement date | PD-05-2025 §4.4.2(a) |
| % resubmission RA within 30 days | Claim-rounds (1, 2) settled ≤ 30 days after resubmission | Claim-rounds (1, 2) with a valid date | Claim × round | Settlement date | PD-05-2025 §4.4.2(b) |
| Late-payment fee due (AED) | Σ max(0, days − deadline) × 0.03% × line net | – | Line × round | Settlement date | PD-05-2025 §4.4.2(c), owed by the payer |
| Late-submission fee (AED) | Σ days after the 15th of the following month × 0.03% × line net | – | Line | Service date | PD-05-2025 §4.2.4–4.2.5, owed by the provider |
| A/R balance at date D | Net submitted ≤ D − payments settled ≤ D − final denials written off ≤ D | – | Line | D | A line's unpaid remainder is written off at its last settlement date. Lines with an invalid settlement date are excluded. |
| A/R days at D | A/R balance at D | Average daily net submitted over (D − 90, D] | – | D = month-end | |
| A/R days (headline) | Mean of A/R days at the last 12 month-ends of the period | – | – | – | The first months are a ramp-up with no history |
| Expected denial rate (value), payer p | Σ over service lines s of net(p, s) × all-payer initial denial rate (value) of s | Σ net(p) | Line | Service date | Mix adjustment (indirect standardisation) |
| Denial rate vs expected | Initial denial rate (value) of p | Expected denial rate (value) of p | – | – | > 1 means the payer denies more than its service mix explains |

## Why the mix-adjusted rate matters

A payer whose members mostly use high-denial services, such as physiotherapy with its session limits and plan exclusions, will show a high raw denial rate even if it treats every service exactly like the other payers. Raising that raw rate in a contract meeting invites the reply "look at your own case mix". The expected rate prices the payer's own mix at market rates. The gap between actual and expected is the part the payer has to explain.
