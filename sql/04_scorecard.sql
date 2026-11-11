-- 04_scorecard.sql : one row per payer, for contract and payer-relations conversations.
-- Mix-adjusted expected denial rate: what this payer's denial rate (by value) would be if it denied
-- each service line at the all-payer rate for that line, given its own service mix.
-- Actual / expected > 1 means the payer denies more than its mix explains.

CREATE OR REPLACE TABLE payer_scorecard AS
WITH line_rates AS (
    SELECT service_line, SUM(initial_denied_amount) / SUM(net) AS line_rate
    FROM fact_claim_line GROUP BY service_line
), expected AS (
    SELECT f.payer_id, SUM(f.net * r.line_rate) / SUM(f.net) AS expected_denial_rate_value
    FROM fact_claim_line f JOIN line_rates r USING (service_line)
    GROUP BY f.payer_id
)
SELECT
    p.payer_id, p.payer_name, p.payer_kind,
    k.claims, k.lines, k.net_billed_aed,
    k.initial_denial_rate_count,
    k.initial_denial_rate_value,
    e.expected_denial_rate_value,
    k.initial_denial_rate_value / e.expected_denial_rate_value      AS denial_rate_vs_expected,
    k.avoidable_denial_share,
    k.resubmission_overturn_rate,
    k.final_denial_rate_value,
    k.final_denied_aed,
    k.median_days_to_payment,
    t.pct_initial_within_45d,
    t.pct_resubmission_within_30d,
    t.late_payment_fee_due_aed,
    a.ar_days_last12_avg
FROM dim_payer p
JOIN kpi_cube k ON k.grain = 'payer' AND k.payer_id = p.payer_id
JOIN expected e ON e.payer_id = p.payer_id
LEFT JOIN kpi_timeliness t ON t.payer_id = p.payer_id
LEFT JOIN kpi_ar_summary a ON a.payer_id = p.payer_id
ORDER BY k.final_denied_aed DESC;
