-- 05_series.sql : weekly series for the payer-behaviour change detector (src/detect_change.py).
-- Week = the week the initial remittance advice was RECEIVED: a team only learns about denials when
-- the RA arrives, so detection time is measured in the same clock a real team would have.
-- Weeks after the end of the service period are cut: by then only slow-paid claims are still arriving,
-- which would bias both the denial mix and the days-to-payment median.

CREATE OR REPLACE TABLE series_denials_weekly AS
WITH grid AS (
    SELECT DISTINCT d.week_start, p.payer_id, s.service_line, c.category AS denial_category
    FROM dim_date d, dim_payer p, dim_service_line s,
         (SELECT DISTINCT category FROM dim_denial_code) c
    WHERE d.date BETWEEN (SELECT MIN(initial_ra_date) FROM fact_claim_line)
                     AND (SELECT period_end FROM ref_params)
), lines AS (
    SELECT CAST(date_trunc('week', initial_ra_date) AS DATE) AS week_start, payer_id, service_line,
           COUNT(*) AS adjudicated_lines
    FROM fact_claim_line WHERE initial_ra_date <= (SELECT period_end FROM ref_params) GROUP BY ALL
), denied AS (
    SELECT CAST(date_trunc('week', initial_ra_date) AS DATE) AS week_start, payer_id, service_line,
           initial_denial_category AS denial_category, COUNT(*) AS denied_lines
    FROM fact_claim_line WHERE initial_ra_date <= (SELECT period_end FROM ref_params) AND is_initial_denied GROUP BY ALL
)
SELECT g.week_start, g.payer_id, g.service_line, g.denial_category,
       COALESCE(l.adjudicated_lines, 0) AS adjudicated_lines,
       COALESCE(x.denied_lines, 0)      AS denied_lines
FROM grid g
LEFT JOIN lines l USING (week_start, payer_id, service_line)
LEFT JOIN denied x USING (week_start, payer_id, service_line, denial_category)
ORDER BY g.payer_id, g.service_line, g.denial_category, g.week_start;

CREATE OR REPLACE TABLE series_days_to_pay_weekly AS
SELECT CAST(date_trunc('week', initial_ra_date) AS DATE) AS week_start, payer_id,
       COUNT(*) AS claims_settled, MEDIAN(days_to_initial_ra) AS median_days_to_payment
FROM fact_claim_line
WHERE is_claim_anchor AND initial_ra_date <= (SELECT period_end FROM ref_params)
GROUP BY ALL
ORDER BY payer_id, week_start;
