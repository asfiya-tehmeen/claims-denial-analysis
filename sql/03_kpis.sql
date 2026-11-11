-- 03_kpis.sql : RCM KPI layer. Definitions: sql/KPI_DEFINITIONS.md (the DAX in reports/powerbi/MEASURES.md matches them).
-- Month = service month. Claim-level KPIs use is_claim_anchor (one row per claim).

-- KPIs at several grains in one long table -------------------------------------------------------
CREATE OR REPLACE TABLE kpi_cube AS
SELECT
    CASE
        WHEN GROUPING(payer_id) = 0 AND GROUPING(service_line) = 0 THEN 'payer x service_line'
        WHEN GROUPING(payer_id) = 0 AND GROUPING(year_month) = 0 THEN 'payer x month'
        WHEN GROUPING(payer_id) = 0 THEN 'payer'
        WHEN GROUPING(service_line) = 0 THEN 'service_line'
        WHEN GROUPING(year_month) = 0 THEN 'month'
        WHEN GROUPING(facility_id) = 0 THEN 'facility'
        WHEN GROUPING(initial_denial_category) = 0 THEN 'denial_category'
        ELSE 'overall' END                                                                   AS grain,
    payer_id, service_line, year_month, facility_id, initial_denial_category,
    COUNT(*) FILTER (WHERE is_claim_anchor)                                                  AS claims,
    COUNT(*)                                                                                 AS lines,
    ROUND(SUM(net), 2)                                                                       AS net_billed_aed,
    ROUND(SUM(initial_denied_amount), 2)                                                     AS initial_denied_aed,
    ROUND(SUM(final_denied_amount), 2)                                                       AS final_denied_aed,
    ROUND(SUM(recovered_on_resubmission), 2)                                                 AS recovered_aed,
    COUNT(*) FILTER (WHERE is_claim_anchor AND claim_scrubber_clean)
        / NULLIF(COUNT(*) FILTER (WHERE is_claim_anchor), 0)                                 AS clean_claim_rate,
    COUNT(*) FILTER (WHERE is_claim_anchor AND claim_first_pass_paid)
        / NULLIF(COUNT(*) FILTER (WHERE is_claim_anchor), 0)                                 AS first_pass_yield,
    AVG(CAST(is_initial_denied AS DOUBLE))                                                   AS initial_denial_rate_count,
    SUM(initial_denied_amount) / NULLIF(SUM(net), 0)                                         AS initial_denial_rate_value,
    SUM(initial_denied_amount) FILTER (WHERE is_avoidable_denial)
        / NULLIF(SUM(initial_denied_amount), 0)                                              AS avoidable_denial_share,
    SUM(final_denied_amount) / NULLIF(SUM(net), 0)                                           AS final_denial_rate_value,
    COUNT(*) FILTER (WHERE was_overturned) / NULLIF(COUNT(*) FILTER (WHERE was_resubmitted), 0) AS resubmission_overturn_rate,
    MEDIAN(days_to_initial_ra) FILTER (WHERE is_claim_anchor)                                AS median_days_to_payment,
    ROUND(SUM(late_submission_days * net) * (SELECT delay_fee_rate_per_day FROM ref_params), 2) AS late_submission_fee_aed
FROM (SELECT *, strftime(service_date, '%Y-%m') AS year_month FROM fact_claim_line)
GROUP BY GROUPING SETS ((), (payer_id), (service_line), (year_month), (facility_id), (initial_denial_category),
                        (payer_id, service_line), (payer_id, year_month));

CREATE OR REPLACE VIEW kpi_overall AS SELECT * FROM kpi_cube WHERE grain = 'overall';
CREATE OR REPLACE VIEW kpi_monthly AS SELECT * FROM kpi_cube WHERE grain = 'month' ORDER BY year_month;

-- Where revenue leaks: initial and final denied AED by denial category and service line ------------
CREATE OR REPLACE VIEW kpi_leakage AS
SELECT initial_denial_category AS denial_category, service_line,
       COUNT(*)                                   AS denied_lines,
       ROUND(SUM(initial_denied_amount), 2)       AS initial_denied_aed,
       ROUND(SUM(final_denied_amount), 2)         AS final_denied_aed,
       ROUND(SUM(recovered_on_resubmission), 2)   AS recovered_aed
FROM fact_claim_line
WHERE is_initial_denied
GROUP BY ALL
ORDER BY final_denied_aed DESC;

-- Payment-timeline compliance (PD-05-2025 4.4.2), one row per claim x remittance round ---------------
CREATE OR REPLACE VIEW claim_settlements AS
SELECT claim_id, round, ANY_VALUE(payer_key) AS payer_key,
       MAX(days_to_settlement) AS days_to_settlement, MAX(deadline_days) AS deadline_days,
       BOOL_AND(within_deadline) AS within_deadline, SUM(late_payment_fee_aed) AS late_payment_fee_aed
FROM fact_remittance
WHERE settlement_date IS NOT NULL
GROUP BY claim_id, round;

CREATE OR REPLACE VIEW kpi_timeliness AS
SELECT p.payer_id,
       COUNT(*) FILTER (WHERE round = 0)                                                   AS initial_settlements,
       AVG(CAST(within_deadline AS DOUBLE)) FILTER (WHERE round = 0)                         AS pct_initial_within_45d,
       AVG(CAST(within_deadline AS DOUBLE)) FILTER (WHERE round > 0)                         AS pct_resubmission_within_30d,
       ROUND(SUM(late_payment_fee_aed), 2)                                                 AS late_payment_fee_due_aed
FROM claim_settlements s JOIN dim_payer p USING (payer_key)
GROUP BY GROUPING SETS ((p.payer_id), ());

-- A/R days at each month-end: A/R balance / average daily net charges (trailing 90 days) --------------
-- A/R balance(D) = net submitted <= D - payments settled <= D - final denials written off <= D
-- (a line's unpaid remainder is written off at its last settlement date). Lines with an invalid
-- settlement date (data-quality flag) are left out.
CREATE OR REPLACE TABLE kpi_ar_monthly AS
WITH lines AS (
    SELECT activity_id, payer_id, net, submission_date, last_settlement_date, final_denied_amount
    FROM fact_claim_line
    WHERE ar_eligible
), pays AS (
    SELECT r.activity_id, l.payer_id, r.settlement_date, r.payment_amount
    FROM fact_remittance r JOIN lines l USING (activity_id)
), ends AS (
    SELECT date AS month_end, year_month FROM dim_date WHERE is_month_end AND sim_month IS NOT NULL
), payers AS (
    SELECT payer_id FROM dim_payer UNION ALL SELECT 'ALL'
), charges AS (
    SELECT e.month_end, p.payer_id,
           SUM(l.net) FILTER (WHERE l.submission_date <= e.month_end)                                   AS charged,
           SUM(l.final_denied_amount) FILTER (WHERE l.last_settlement_date <= e.month_end)              AS written_off,
           SUM(l.net) FILTER (WHERE l.submission_date > e.month_end - INTERVAL 90 DAY
                                AND l.submission_date <= e.month_end) / 90.0                            AS avg_daily_charges
    FROM ends e CROSS JOIN payers p
    JOIN lines l ON (p.payer_id = 'ALL' OR l.payer_id = p.payer_id)
    GROUP BY ALL
), paid AS (
    SELECT e.month_end, p.payer_id, SUM(y.payment_amount) AS paid
    FROM ends e CROSS JOIN payers p
    JOIN pays y ON (p.payer_id = 'ALL' OR y.payer_id = p.payer_id) AND y.settlement_date <= e.month_end
    GROUP BY ALL
)
SELECT c.month_end, e.year_month, c.payer_id,
       ROUND(c.charged - COALESCE(y.paid, 0) - COALESCE(c.written_off, 0), 2)                         AS ar_balance_aed,
       ROUND(c.avg_daily_charges, 2)                                                                  AS avg_daily_charges_aed,
       (c.charged - COALESCE(y.paid, 0) - COALESCE(c.written_off, 0)) / NULLIF(c.avg_daily_charges, 0) AS ar_days
FROM charges c
JOIN ends e USING (month_end)
LEFT JOIN paid y USING (month_end, payer_id)
ORDER BY c.payer_id, c.month_end;

-- headline A/R days: mean of the last 12 month-ends (the first months are a ramp-up with no history)
CREATE OR REPLACE VIEW kpi_ar_summary AS
SELECT payer_id, AVG(ar_days) AS ar_days_last12_avg
FROM (SELECT *, row_number() OVER (PARTITION BY payer_id ORDER BY month_end DESC) AS rn FROM kpi_ar_monthly)
WHERE rn <= 12
GROUP BY payer_id;
