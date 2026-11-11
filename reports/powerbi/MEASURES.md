# DAX measures

> **Data honesty:** claims are SIMULATED using the published DHA eClaimLink field structure.

Every measure matches a definition in [`sql/KPI_DEFINITIONS.md`](../../sql/KPI_DEFINITIONS.md), and `expected_values.csv` gives the SQL result to check against.
Create them in the `_Measures` table (see MODEL.md step 5). Set the **display folder** and **format** shown for each (Measure tools → Format / Properties → Display folder).

**Formats:** `0.0%` = Percentage with 1 decimal. `#,0` = Whole number with thousands separator. `0.00` = Decimal with 2 places.

---

## Volume (display folder: `1 Volume`)

```DAX
Claims =
CALCULATE ( COUNTROWS ( fact_claim_line ), fact_claim_line[is_claim_anchor] = 1 )
```
Format `#,0`. One anchor row per claim, so this counts claims, not lines.

```DAX
Lines = COUNTROWS ( fact_claim_line )
```
Format `#,0`.

```DAX
Net Billed AED = SUM ( fact_claim_line[net] )
```
Format `#,0`. Net = gross − patient share (the amount claimed from the payer).

```DAX
Initial Denied AED = SUM ( fact_claim_line[initial_denied_amount] )
```
Format `#,0`. Denied on the first remittance advice. Includes partial (price) denials.

```DAX
Final Denied AED = SUM ( fact_claim_line[final_denied_amount] )
```
Format `#,0`. Still unpaid after all resubmission rounds: revenue lost.

```DAX
Recovered on Resubmission AED = SUM ( fact_claim_line[recovered_on_resubmission] )
```
Format `#,0`.

## Front end (display folder: `2 Front end`)

```DAX
Clean Claim Rate =
DIVIDE (
    CALCULATE ( [Claims], fact_claim_line[claim_scrubber_clean] = 1 ),
    [Claims]
)
```
Format `0.0%`. Claims with zero scrubber rule hits ÷ claims submitted (HFMA-style: passes edits with no manual intervention).

```DAX
First-Pass Yield =
DIVIDE (
    CALCULATE ( [Claims], fact_claim_line[claim_first_pass_paid] = 1 ),
    [Claims]
)
```
Format `0.0%`. Claims with no line denied (fully or partly) on the first remittance ÷ claims.

## Denials (display folder: `3 Denials`)

```DAX
Initial Denial Rate (Count) =
DIVIDE ( CALCULATE ( [Lines], fact_claim_line[is_initial_denied] = 1 ), [Lines] )
```
Format `0.0%`.

```DAX
Initial Denial Rate (Value) = DIVIDE ( [Initial Denied AED], [Net Billed AED] )
```
Format `0.0%`.

```DAX
Avoidable Denial Share =
DIVIDE (
    CALCULATE ( [Initial Denied AED], fact_claim_line[is_avoidable_denial] = 1 ),
    [Initial Denied AED]
)
```
Format `0.0%`. Avoidable is set per denial code in `dim_denial_code[avoidable]` (analyst judgement, documented in `config/denial_codes.yaml`).

```DAX
Final Denial Rate (Value) = DIVIDE ( [Final Denied AED], [Net Billed AED] )
```
Format `0.0%`.

```DAX
Resubmission Overturn Rate =
DIVIDE (
    CALCULATE ( [Lines], fact_claim_line[was_overturned] = 1 ),
    CALCULATE ( [Lines], fact_claim_line[was_resubmitted] = 1 )
)
```
Format `0.0%`. Resubmitted lines that were paid (fully or partly) in a later round ÷ resubmitted lines.

```DAX
Expected Denial Rate (Value) =
DIVIDE (
    SUMX (
        VALUES ( dim_service_line[service_line_key] ),
        CALCULATE ( [Net Billed AED] )
            * CALCULATE ( [Initial Denial Rate (Value)], REMOVEFILTERS ( dim_payer ) )
    ),
    [Net Billed AED]
)
```
Format `0.0%`. Mix-adjusted: the payer's own service mix, priced at the all-payer denial rate of each service line. Other slicers (for example dates) still apply.

```DAX
Denial Rate vs Expected = DIVIDE ( [Initial Denial Rate (Value)], [Expected Denial Rate (Value)] )
```
Format `0.00`. Above 1.00, the payer denies more than its service mix explains.

```DAX
Auth Denial Rate (by RA Week) =
CALCULATE (
    DIVIDE (
        CALCULATE ( [Lines], dim_denial_code[category] = "Authorisation" ),
        [Lines]
    ),
    USERELATIONSHIP ( fact_claim_line[initial_ra_date_key], dim_date[date_key] )
)
```
Format `0.0%`. Authorisation denials ÷ adjudicated lines, by the date the remittance arrived. This is the clock the change detector uses.

## Payment and timeliness (display folder: `4 Payment`)

```DAX
Median Days to Payment =
CALCULATE ( MEDIAN ( fact_claim_line[days_to_initial_ra] ), fact_claim_line[is_claim_anchor] = 1 )
```
Format `#,0`. Claim submission → first remittance advice, per claim.

```DAX
% Initial RA Within 45 Days =
VAR AllClaims =
    CALCULATETABLE (
        VALUES ( fact_remittance[claim_round_id] ),
        fact_remittance[round] = 0,
        NOT ISBLANK ( fact_remittance[settlement_date] )
    )
VAR LateClaims =
    CALCULATETABLE (
        VALUES ( fact_remittance[claim_round_id] ),
        fact_remittance[round] = 0,
        NOT ISBLANK ( fact_remittance[settlement_date] ),
        fact_remittance[within_deadline] = 0      -- blank = 0 in DAX, hence the ISBLANK guard
    )
RETURN
    1 - DIVIDE ( COUNTROWS ( LateClaims ), COUNTROWS ( AllClaims ) )
```
Format `0.0%`. PD-05-2025 §4.4.2(a): RA and payment within 45 calendar days of submission.

```DAX
% Resubmission RA Within 30 Days =
VAR AllRounds =
    CALCULATETABLE (
        VALUES ( fact_remittance[claim_round_id] ),
        fact_remittance[round] > 0,
        NOT ISBLANK ( fact_remittance[settlement_date] )
    )
VAR LateRounds =
    CALCULATETABLE (
        VALUES ( fact_remittance[claim_round_id] ),
        fact_remittance[round] > 0,
        NOT ISBLANK ( fact_remittance[settlement_date] ),
        fact_remittance[within_deadline] = 0      -- blank = 0 in DAX, hence the ISBLANK guard
    )
RETURN
    1 - DIVIDE ( COUNTROWS ( LateRounds ), COUNTROWS ( AllRounds ) )
```
Format `0.0%`. PD-05-2025 §4.4.2(b): within 30 calendar days of resubmission.

```DAX
Late Payment Fee Due AED = SUM ( fact_remittance[late_payment_fee_aed] )
```
Format `#,0`. PD-05-2025 §4.4.2(c): 0.03% of net claimed per calendar day beyond the deadline, owed by the payer.

```DAX
Late Submission Fee AED =
SUMX ( fact_claim_line, fact_claim_line[late_submission_days] * fact_claim_line[net] ) * 0.0003
```
Format `#,0`. PD-05-2025 §4.2.4–4.2.5: submissions after the 15th of the following month, owed by the provider.

## A/R (display folder: `5 AR`)

```DAX
AR Balance AED =
VAR D = MAX ( dim_date[date] )
VAR Charged =
    CALCULATE ( SUM ( fact_claim_line[net] ), REMOVEFILTERS ( dim_date ),
        fact_claim_line[ar_eligible] = 1, fact_claim_line[submission_date] <= D )
VAR Paid =
    CALCULATE ( SUM ( fact_remittance[payment_amount] ), REMOVEFILTERS ( dim_date ),
        fact_remittance[ar_eligible] = 1, fact_remittance[settlement_date] <= D )
VAR WrittenOff =
    CALCULATE ( SUM ( fact_claim_line[final_denied_amount] ), REMOVEFILTERS ( dim_date ),
        fact_claim_line[ar_eligible] = 1, fact_claim_line[last_settlement_date] <= D )
RETURN
    Charged - Paid - WrittenOff
```
Format `#,0`. Balance as at the last date in the current filter context.

```DAX
Avg Daily Charges AED =
VAR D = MAX ( dim_date[date] )
RETURN
    DIVIDE (
        CALCULATE ( SUM ( fact_claim_line[net] ), REMOVEFILTERS ( dim_date ),
            fact_claim_line[ar_eligible] = 1,
            fact_claim_line[submission_date] > D - 90,
            fact_claim_line[submission_date] <= D ),
        90
    )
```
Format `#,0`. Trailing 90 days.

```DAX
A/R Days = DIVIDE ( [AR Balance AED], [Avg Daily Charges AED] )
```
Format `#,0.0`. Put it on a chart with `dim_date[year_month]` on the axis to get month-end values.

```DAX
A/R Days (Avg Last 12 Month-Ends) =
VAR Months =
    TOPN (
        12,
        CALCULATETABLE ( VALUES ( dim_date[year_month] ), REMOVEFILTERS ( dim_date ), NOT ISBLANK ( dim_date[sim_month] ) ),
        dim_date[year_month], DESC
    )
RETURN
    AVERAGEX (
        Months,
        VAR ym = dim_date[year_month]
        RETURN CALCULATE ( [A/R Days], REMOVEFILTERS ( dim_date ), dim_date[year_month] = ym )
    )
```
Format `#,0.0`. The headline A/R figure. It ignores the date slicer on purpose: the first months of the simulation have no history.
