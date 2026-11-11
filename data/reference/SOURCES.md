# Sources and verification log

Checked 2026-11-11. Status: **verified** = read in the primary/official document; **secondary** = only in a third-party summary; **unverified** = not confirmed; **not found**.
Downloaded files live in `data/reference/downloads/` (gitignored; `python -m src.reference` re-downloads the CMS files).

| # | Source | What it is used for | Status | Evidence |
|---|---|---|---|---|
| 1 | **DHIC Policy Directive PD-05-2025, "Health Insurance Claims Management Policy Directive"** (doc ID DHIC/HIR-002/2024, issued 27/10/2025, effective 16/11/2025). Archived official PDF: `https://web.archive.org/web/20251108151413/https://www.isahd.ae/content/docs/PD-05-2025%20Dubai%20Health%20Insurance%20Claims%20Management.pdf` | Payment / resubmission timelines and delay fee in the payer scorecard | **Verified (text)**, **status unconfirmed**. The live ISAHD link returned 404 on 2026-11-11. The Avior Advisory tracker (2 Sep 2026) reports the same 404 and says no repealing circular has been published. | `PD-05-2025_archived_20251108.pdf`, sha256 `9ebc2e75…babf5`, 23 pages |
| 2 | **DHA eClaimLink General Circular GC 06/2018 "Denial Code Updates"** (`https://www.isahd.ae/content/docs/eClaimLink%20General%20Circular%20GC06%202018%20-%20Denial%20Code%20Updates.pdf`) | 20 denial codes and descriptions (e.g. CODE-001, CODE-006, MNEC-007, NCOV-019, NCOV-027, AUTH-002) | **Verified** (official DHA circular) | `GC06-2018_denial_code_updates.pdf`, sha256 `9c13b457…c886a` |
| 3 | DHA GC 05-2025 "DHIC Issuance of Updated Regulations Superseding Previous regulatory documents" (07/10/2025) | Context only: confirms DHIC issued new Policy Directives that replace older circulars | **Verified** (read; does not list PD-05-2025 in its table) | Fetched from isahd.ae |
| 4 | Core denial codes (ELIG-001/005/006, AUTH-001/003/004, DUPL-001, TIME-001, PRCE-001/002/010, NCOV-003, BENX-002, MNEC-003/004) | `dim_denial_code` | **Secondary.** Text taken from an HL7 FHIR value set (Swasth HCX, India) that reproduces the Shafafiya/eClaimLink list, and matches the Zavis decoder that quotes the DOH Shafafiya list. The official eClaimLink list needs registration. | `dim_denial_code.source` column marks each code |
| 5 | DOH Abu Dhabi Shafafiya data dictionary (`https://shafafiyaportal.doh.gov.ae/dictionary/`) | Field names `Claim.ID`, `Activity.ID`, `Activity.PaymentAmount`, `Activity.DenialCode`, `Activity.PriorAuthorizationID` | **Verified for Abu Dhabi (DOH).** Assumed identical in DHA eClaimLink, but that is **unverified** (eClaimLink schema needs registration). | docs/data_dictionary.md |
| 6 | eClaimLink resubmission types "correction / internal complaint / reconciliation" | `resubmission_type` | "Reconciliation" is **verified** (PD-05-2025 §4.6.4). The other two are **secondary** (Zavis, citing SN 03-2019). | |
| 7 | **CMS Medicaid NCCI PTP edits, practitioner services, effective 2026-10-01** (`https://www.cms.gov/files/zip/medicaid-ncci-2026-q4-ptp-edits-practitioner-services.zip`) | Coding rules in the scrubber and the planted code-pair effect (92 active pairs within the catalogue) | **Verified** (downloaded; parsed). Note: Medicaid edits, used because the Medicare full PTP files sit behind an AMA licence click-through. | sha256 `a6226524…0d661` |
| 8 | **CMS Medicare NCCI MUE table, practitioner services, Q4 2026** (`https://www.cms.gov/files/zip/medicare-ncci-2026-q4-practitioner-services-mue-table.zip`) | Unit edits | **Verified** (downloaded; parsed) | sha256 `45743367…80d00` |
| 9 | **CMS ICD-10-CM FY2027 code descriptions** (`https://www.cms.gov/files/zip/2027-code-descriptions-tabular-order.zip`) | Diagnosis validation; billable vs header codes | **Verified** (downloaded; parsed, 98,403 codes) | sha256 `91c6c9d1…94965` |
| 10 | Alibrahim, Kelendar & Alhenaidi (2025), *Frontiers in Public Health*, doi:10.3389/fpubh.2025.1606980, Kuwait AFYA claims 2016–2023 | Sanity reference only: overall rejection rate 3.85% | **Verified** (abstract) | Not used as a target |
| 11 | NPHIES (KSA) implementation guide | Mapping note only | **Unverified.** HL7 FHIR R4 `Claim` / `ClaimResponse` element names are standard FHIR. NPHIES-specific profiles were not read. | docs/data_dictionary.md |
| 12 | DHA mandatory price list / tariff | Not used. Prices are simulated round numbers. | n/a | |

## Rules encoded from PD-05-2025 (verified text, section numbers from the PDF)

| Rule | Value | Section |
|---|---|---|
| Submission deadline | Services in a calendar month: submit by the **15th of the following month** | 4.2.4 |
| Late submission | Payer may charge **0.03% of Net Claimed Amount per calendar day** overdue | 4.2.5 a |
| Remittance advice + payment, initial claims | **45 calendar days** from claim submission | 4.4.2 a |
| Remittance advice + payment, resubmissions | **30 calendar days** from resubmission | 4.4.2 b, 4.5 e |
| Late payment | Provider entitled to **0.03% per calendar day** of the original Net Claimed Amount | 4.4.2 c |
| Resubmission window | **21 calendar days** from receipt of payment / RA with the denial reason | 4.5 b |
| Maximum resubmissions | **2** (first resubmission + one reconciliation) | 4.5 c |
| Overall cycle | Claims processed within the **141-day** submission and settlement cycle | 4.3.1 a |
| Denial codes | Must follow the official eClaimLink list and appear in the RA | 4.4.1 b |

## Simulator assumptions that are NOT from a source

- TIME-001 denial when a claim is submitted more than 90 days after service. PD-05-2025 treats late submission as a delay fee. The 90-day denial cut-off is an assumption, chosen to stay well inside the 141-day cycle.
- All denial rates, payer behaviour, prices, provider error rates and review capacity (see `config/*.yaml`).
- PD-05-2025 timelines are applied to the whole simulated period (Oct 2024 – Sep 2026), including the months before its 16 Nov 2025 effective date. This keeps the scorecard simple.
