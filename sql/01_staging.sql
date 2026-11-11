-- 01_staging.sql : typed staging views over the validated (clean) tables.
-- Input tables raw_* are loaded from data/clean/*.parquet by src/build_db.py.
-- Quarantined lines (see data/clean/data_quality.csv) are excluded here, once, for everything downstream.

CREATE OR REPLACE VIEW stg_claims AS
SELECT
    claim_id,
    member_id,
    payer_id,
    provider_id                       AS facility_id,
    encounter_type                    AS service_line,
    CAST(encounter_start AS DATE)     AS service_date,
    CAST(submission_date AS DATE)     AS submission_date,
    principal_dx,
    net                               AS claim_net,
    dq_invalid_dx
FROM raw_claims;

CREATE OR REPLACE VIEW stg_lines AS
SELECT
    a.activity_id,
    a.claim_id,
    a.line_no,
    CAST(a.start AS DATE)             AS service_date,
    a.type                            AS code_type,
    a.code,
    a.quantity,
    COALESCE(a.modifier, '')          AS modifier,
    a.gross,
    a.patient_share,
    a.net,
    a.clinician_id,
    a.prior_auth_id,
    c.payer_id,
    c.facility_id,
    c.service_line,
    c.submission_date,
    c.member_id,
    m.plan_tier
FROM raw_activities a
JOIN stg_claims c USING (claim_id)
JOIN raw_members m USING (member_id)
WHERE NOT a.dq_quarantined;

CREATE OR REPLACE VIEW stg_remittances AS
SELECT
    r.activity_id,
    r.claim_id,
    r.round,
    CAST(r.date_settlement AS DATE)   AS settlement_date,     -- NULL where the export date was invalid
    r.payment_amount,
    r.denial_code
FROM raw_remittances r
WHERE r.activity_id IN (SELECT activity_id FROM stg_lines);

CREATE OR REPLACE VIEW stg_resubmissions AS
SELECT claim_id, round, resubmission_type, CAST(resubmission_date AS DATE) AS resubmission_date
FROM raw_resubmissions;

CREATE OR REPLACE VIEW stg_flags AS
SELECT f.activity_id, f.rule, f.category, f.suggested_fix
FROM raw_scrubber_flags f
WHERE f.activity_id IN (SELECT activity_id FROM stg_lines);
