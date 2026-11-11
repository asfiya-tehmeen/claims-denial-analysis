# Data dictionary

> **Data honesty:** claims are SIMULATED using the published DHA eClaimLink field structure. Code sets and edit rules come from real public sources (`data/reference/SOURCES.md`). Payer names are fictional. No result describes real UAE or Saudi denial rates.

Raw exports (`data/raw/*.csv`) mimic what a hospital billing system would pull from eClaimLink. Clean tables (`data/clean/*.parquet`) carry the same columns plus `dq_*` flags. Star-schema columns are documented in `reports/powerbi/MODEL.md`.

**Field status:**
- **DOH✓**: field name verified in the DOH Abu Dhabi Shafafiya dictionary. Assumed identical in DHA eClaimLink (the schema needs registration).
- **sim**: simulator field with no published equivalent.

## claims (one row per claim)

| Column | eClaimLink element | Status | NPHIES (FHIR R4) equivalent* | Notes |
|---|---|---|---|---|
| claim_id | Claim.ID | DOH✓ | Claim.identifier | Provider's claim ID |
| member_id | Claim.MemberID | assumed | Claim.patient → Patient.identifier | |
| payer_id | Claim.PayerID | assumed | Claim.insurer | Fictional payers P01–P06 |
| provider_id | Claim.ProviderID | assumed | Claim.provider | Facility (FAC-HH, FAC-CM) |
| encounter_type | Encounter.Type | assumed | Claim.subType / Encounter.class | Here: the service line |
| encounter_start | Encounter.Start | assumed | Claim.billablePeriod.start | Service date |
| principal_dx | Diagnosis.Code (Type = Principal) | assumed | Claim.diagnosis (type principal) | ICD-10-CM without the dot. NPHIES uses ICD-10-AM. |
| gross, patient_share, net | Claim.Gross / PatientShare / Net | assumed | Claim.total, patient share via Claim.item | AED |
| submission_date | Header.TransactionDate | assumed | Claim.created | |

## activities (one row per claim line)

| Column | eClaimLink element | Status | NPHIES (FHIR R4) equivalent* | Notes |
|---|---|---|---|---|
| activity_id | Activity.ID | DOH✓ | Claim.item.sequence | |
| start | Activity.Start | assumed | Claim.item.servicedDate | |
| type | Activity.Type | assumed | Claim.item.productOrService.coding.system | `CPT` or `DRUG`. eClaimLink uses numeric type codes, not reproduced here. |
| code | Activity.Code | assumed | Claim.item.productOrService | CPT/HCPCS (codes only, AMA-licensed descriptors not copied). Drugs use a simulated `SIM-` format. NPHIES uses SBS/ACHI codes. |
| quantity | Activity.Quantity | assumed | Claim.item.quantity | |
| modifier | Observation (type Modifier) | assumed | Claim.item.modifier | 25 / 59 |
| gross, patient_share, net | Activity.Gross / PatientShare / Net | assumed | Claim.item.net | |
| clinician_id | Activity.Clinician | assumed | Claim.careTeam.provider | Fictional IDs |
| prior_auth_id | Activity.PriorAuthorizationID | DOH✓ | Claim.preAuthRef / Claim.insurance.preAuthRef | |

## remittances (one row per line per remittance round)

| Column | eClaimLink element | Status | NPHIES (FHIR R4) equivalent* | Notes |
|---|---|---|---|---|
| claim_id, activity_id | Claim.ID, Activity.ID | DOH✓ | ClaimResponse.request, ClaimResponse.item.itemSequence | |
| round | (resubmission count) | sim | – | 0 initial, 1 first resubmission, 2 reconciliation (PD-05-2025 §4.5–4.6) |
| date_settlement | Claim.DateSettlement | DOH✓ (definition) | ClaimResponse.payment.date | "Date of payment or date of decision to reject (PaymentAmount = 0)" |
| payment_amount | Activity.PaymentAmount | DOH✓ | ClaimResponse.item.adjudication (category benefit) | |
| denial_code | Activity.DenialCode | DOH✓ | ClaimResponse.item.adjudication.reason | Codes in `config/denial_codes.yaml` |
| payment_reference | Claim.PaymentReference | assumed | ClaimResponse.payment.identifier | Required in the RA by PD-05-2025 §4.4.1(a) |

## resubmissions

| Column | eClaimLink element | Status | Notes |
|---|---|---|---|
| resubmission_type | Resubmission.Type | partly verified | `reconciliation` verified (PD-05-2025 §4.6.4). `correction` / `internal complaint` from secondary sources. |
| resubmission_date | Header.TransactionDate | assumed | |

## Other tables

`members` (plan tier, coverage dates as held by the provider), `prior_auths`, `payers`, `facilities`, `clinicians`, `contract_prices` (simulated AED prices), `payer_auth_rules` (each payer's published prior-auth list as the provider held it at the start of the period) and `plan_benefits` (copay, physiotherapy session limit, exclusions).

\* **NPHIES mapping note:** NPHIES (Saudi Arabia) exchanges claims as HL7 FHIR R4 `Claim` / `ClaimResponse` resources. The element names in this column are base FHIR R4 elements. The NPHIES-specific profiles, extensions and code systems (ICD-10-AM, SBS/ACHI, NPHIES adjudication reason codes) were **not verified** for this project.
