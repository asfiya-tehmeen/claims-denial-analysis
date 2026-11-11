-- 02_marts.sql : star schema (also exported to Power BI).
--   fact_claim_line  grain: one activity line (initial + final outcome)
--   fact_remittance  grain: one activity line x one remittance round (0 = initial, 1 = first resubmission, 2 = reconciliation)
--   dim_payer, dim_service_line, dim_provider, dim_date, dim_denial_code
-- Parameters from PD-05-2025 live in ref_params (loaded by build_db.py).

-- dimensions ----------------------------------------------------------------------------------
CREATE OR REPLACE TABLE dim_date AS
WITH b AS (
    SELECT LEAST((SELECT MIN(service_date) FROM stg_claims), (SELECT MIN(submission_date) FROM stg_claims)) AS d0,
           GREATEST((SELECT MAX(settlement_date) FROM stg_remittances), (SELECT MAX(submission_date) FROM stg_claims)) AS d1
)
SELECT
    CAST(strftime(d, '%Y%m%d') AS INTEGER)               AS date_key,
    CAST(d AS DATE)                                      AS date,
    year(d)                                              AS year,
    quarter(d)                                           AS quarter,
    month(d)                                             AS month,
    strftime(d, '%b')                                    AS month_name,
    strftime(d, '%Y-%m')                                 AS year_month,
    CAST(date_trunc('month', d) AS DATE)                 AS month_start,
    CAST(date_trunc('week', d) AS DATE)                  AS week_start,      -- ISO week, Monday
    isodow(d)                                            AS iso_weekday,
    CAST(last_day(d) = CAST(d AS DATE) AS BOOLEAN)       AS is_month_end,
    CASE WHEN CAST(d AS DATE) BETWEEN p.period_start AND p.period_end
         THEN datediff('month', p.period_start, CAST(d AS DATE)) + 1 END AS sim_month
FROM b, ref_params p, generate_series(b.d0, b.d1, INTERVAL 1 DAY) AS t(d);

CREATE OR REPLACE TABLE dim_payer AS
SELECT row_number() OVER (ORDER BY payer_id) AS payer_key, payer_id, payer_name, payer_kind
FROM raw_payers;

CREATE OR REPLACE TABLE dim_service_line AS
SELECT row_number() OVER (ORDER BY sort_order) AS service_line_key, service_line, service_line_label
FROM ref_service_lines;

CREATE OR REPLACE TABLE dim_provider AS
SELECT row_number() OVER (ORDER BY c.clinician_id) AS provider_key,
       c.clinician_id, c.specialty, c.facility_id, f.facility_name
FROM raw_clinicians c JOIN raw_facilities f USING (facility_id);

CREATE OR REPLACE TABLE dim_denial_code AS
SELECT row_number() OVER (ORDER BY denial_code) AS denial_code_key,
       denial_code, left(denial_code, 4) AS eclaimlink_group, description, category, avoidable, source
FROM ref_denial_codes;

-- fact_claim_line ------------------------------------------------------------------------------
CREATE OR REPLACE TABLE fact_claim_line AS
WITH rem AS (
    SELECT activity_id,
           SUM(payment_amount) FILTER (WHERE round = 0)         AS initial_paid,
           MAX(settlement_date) FILTER (WHERE round = 0)        AS initial_ra_date,
           MAX(denial_code) FILTER (WHERE round = 0)            AS initial_denial_code,
           SUM(payment_amount) FILTER (WHERE round > 0)         AS resub_paid,
           SUM(payment_amount)                                  AS total_paid,
           MAX(round)                                           AS last_round,
           MAX(settlement_date)                                 AS last_settlement_date,
           arg_max(denial_code, round)                          AS last_denial_code
    FROM stg_remittances GROUP BY activity_id
), flags AS (
    SELECT activity_id, COUNT(*) AS scrubber_flag_count FROM stg_flags GROUP BY activity_id
), base AS (
    SELECT l.*,
           r.initial_ra_date, r.initial_denial_code, r.last_round, r.last_settlement_date, r.last_denial_code,
           COALESCE(r.initial_paid, 0)                                   AS initial_paid,
           COALESCE(r.resub_paid, 0)                                     AS recovered_on_resubmission,
           ROUND(l.net - COALESCE(r.initial_paid, 0), 2)                 AS initial_denied_amount,
           ROUND(l.net - COALESCE(r.total_paid, 0), 2)                   AS final_denied_amount,
           COALESCE(f.scrubber_flag_count, 0)                            AS scrubber_flag_count,
           -- PD-05-2025 4.2.4: services in a month must be submitted by the 15th of the following month
           CAST(date_trunc('month', l.service_date) + INTERVAL 1 MONTH + INTERVAL 14 DAY AS DATE) AS submission_deadline
    FROM stg_lines l
    LEFT JOIN rem r USING (activity_id)
    LEFT JOIN flags f USING (activity_id)
)
SELECT
    b.activity_id,
    b.claim_id,
    b.line_no,
    (row_number() OVER (PARTITION BY b.claim_id ORDER BY b.line_no) = 1)         AS is_claim_anchor,   -- one row per claim, for claim-level KPIs
    dp.payer_key,
    ds.service_line_key,
    pr.provider_key,
    CAST(strftime(b.service_date, '%Y%m%d') AS INTEGER)                           AS service_date_key,
    CAST(strftime(b.submission_date, '%Y%m%d') AS INTEGER)                        AS submission_date_key,
    CAST(strftime(b.initial_ra_date, '%Y%m%d') AS INTEGER)                        AS initial_ra_date_key,
    dd.denial_code_key                                                            AS initial_denial_code_key,
    b.payer_id, b.service_line, b.facility_id, b.clinician_id, b.plan_tier, b.member_id,
    b.service_date, b.submission_date, b.initial_ra_date, b.last_settlement_date,
    b.code, b.code_type, b.quantity, b.modifier, b.prior_auth_id IS NOT NULL                     AS has_prior_auth,
    b.gross, b.patient_share, b.net,
    b.initial_paid,
    b.initial_denied_amount,
    b.initial_denied_amount > 0.005                                               AS is_initial_denied,
    b.initial_denial_code,
    COALESCE(dd.category, 'Not denied')                                           AS initial_denial_category,
    COALESCE(dd.avoidable, FALSE) AND b.initial_denied_amount > 0.005             AS is_avoidable_denial,
    COALESCE(b.last_round, 0) >= 1                                                AS was_resubmitted,
    b.recovered_on_resubmission,
    b.recovered_on_resubmission > 0.005                                           AS was_overturned,
    b.final_denied_amount,
    b.final_denied_amount > 0.005                                                 AS is_final_denied,
    datediff('day', b.submission_date, b.initial_ra_date)                         AS days_to_initial_ra,
    datediff('day', b.service_date, b.submission_date)                            AS days_service_to_submission,
    b.submission_deadline,
    GREATEST(datediff('day', b.submission_deadline, b.submission_date), 0)        AS late_submission_days,
    b.scrubber_flag_count,
    -- lines with an invalid settlement date (DQ flag) are left out of A/R
    b.activity_id NOT IN (SELECT activity_id FROM stg_remittances WHERE settlement_date IS NULL) AS ar_eligible,
    (MAX(b.scrubber_flag_count) OVER (PARTITION BY b.claim_id) = 0)              AS claim_scrubber_clean,
    NOT bool_or(b.initial_denied_amount > 0.005) OVER (PARTITION BY b.claim_id)   AS claim_first_pass_paid
FROM base b
JOIN dim_payer dp USING (payer_id)
JOIN dim_service_line ds USING (service_line)
JOIN dim_provider pr USING (clinician_id)
LEFT JOIN dim_denial_code dd ON dd.denial_code = b.initial_denial_code;

-- fact_remittance ------------------------------------------------------------------------------
CREATE OR REPLACE TABLE fact_remittance AS
SELECT
    r.activity_id,
    r.claim_id,
    r.round,
    r.claim_id || '-' || CAST(r.round AS VARCHAR)                                 AS claim_round_id,
    f.ar_eligible,
    CASE r.round WHEN 0 THEN 'Initial' WHEN 1 THEN 'Resubmission' ELSE 'Reconciliation' END   AS round_label,
    f.payer_key, f.service_line_key, f.provider_key,
    CAST(strftime(r.settlement_date, '%Y%m%d') AS INTEGER)                        AS settlement_date_key,
    dd.denial_code_key,
    r.settlement_date,
    r.payment_amount,
    r.denial_code,
    r.denial_code IS NOT NULL                                                     AS is_denied,
    f.net                                                                         AS line_net,
    COALESCE(s.resubmission_date, f.submission_date)                              AS clock_start_date,
    datediff('day', COALESCE(s.resubmission_date, f.submission_date), r.settlement_date) AS days_to_settlement,
    CASE WHEN r.round = 0 THEN p.ra_days_initial ELSE p.ra_days_resubmission END  AS deadline_days,
    datediff('day', COALESCE(s.resubmission_date, f.submission_date), r.settlement_date)
        <= CASE WHEN r.round = 0 THEN p.ra_days_initial ELSE p.ra_days_resubmission END AS within_deadline,
    GREATEST(datediff('day', COALESCE(s.resubmission_date, f.submission_date), r.settlement_date)
        - CASE WHEN r.round = 0 THEN p.ra_days_initial ELSE p.ra_days_resubmission END, 0) AS late_payment_days,
    -- PD-05-2025 4.4.2 c: 0.03% of the Net Claimed Amount per calendar day of late payment
    ROUND(GREATEST(datediff('day', COALESCE(s.resubmission_date, f.submission_date), r.settlement_date)
        - CASE WHEN r.round = 0 THEN p.ra_days_initial ELSE p.ra_days_resubmission END, 0)
        * p.delay_fee_rate_per_day * f.net, 2)                                    AS late_payment_fee_aed
FROM stg_remittances r
JOIN fact_claim_line f USING (activity_id)
CROSS JOIN ref_params p
LEFT JOIN stg_resubmissions s ON s.claim_id = r.claim_id AND s.round = r.round
LEFT JOIN dim_denial_code dd ON dd.denial_code = r.denial_code;
