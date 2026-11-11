"""Validate the raw exports and write clean tables + a data-quality table.

Rules: quarantine what cannot be trusted, flag what can be kept, never silently fix.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import reference
from src.common import CLEAN, RAW, catalog, ensure_dirs

DATES = {
    "claims": ["encounter_start", "submission_date"],
    "activities": ["start"],
    "remittances": ["date_settlement"],
    "resubmissions": ["resubmission_date"],
    "prior_auths": ["request_date", "valid_from", "valid_to"],
    "members": ["birth_date", "coverage_start", "coverage_end"],
}
TABLES = ["payers", "facilities", "clinicians", "members", "contract_prices", "payer_auth_rules",
          "plan_benefits", "claims", "activities", "prior_auths", "remittances", "resubmissions"]


def read_raw(raw_dir: Path = RAW) -> dict[str, pd.DataFrame]:
    out = {}
    for t in TABLES:
        df = pd.read_csv(raw_dir / f"{t}.csv", dtype={"code": str, "principal_dx": str, "modifier": str,
                                                     "excluded_codes": str, "excluded_dx": str, "excluded_drug_classes": str})
        for c in DATES.get(t, []):
            df[c] = pd.to_datetime(df[c])
        out[t] = df
    out["activities"]["modifier"] = out["activities"]["modifier"].fillna("")
    return out


def validate(d: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    claims, acts, rem = d["claims"].copy(), d["activities"].copy(), d["remittances"].copy()
    dq = []

    def log(check, table, n_checked, n_failed, action):
        dq.append({"check": check, "table": table, "rows_checked": int(n_checked),
                   "rows_failed": int(n_failed), "pct_failed": round(100 * n_failed / max(n_checked, 1), 3),
                   "action": action})

    # 1. primary keys
    log("claim_id unique", "claims", len(claims), claims["claim_id"].duplicated().sum(), "fail pipeline if > 0")
    log("activity_id unique", "activities", len(acts), acts["activity_id"].duplicated().sum(), "fail pipeline if > 0")
    if claims["claim_id"].duplicated().any() or acts["activity_id"].duplicated().any():
        raise ValueError("duplicate primary keys in raw exports")

    # 2. exact duplicate remittance rows (export glitch)
    dup = rem.duplicated()
    log("exact duplicate remittance rows", "remittances", len(rem), dup.sum(), "dropped")
    rem = rem[~dup]
    log("remittance key (activity, round) unique", "remittances", len(rem),
        rem.duplicated(["activity_id", "round"]).sum(), "fail pipeline if > 0")

    # 3. orphans
    orphan_a = ~acts["claim_id"].isin(claims["claim_id"])
    log("activity without claim", "activities", len(acts), orphan_a.sum(), "dropped")
    acts = acts[~orphan_a]
    orphan_r = ~rem["activity_id"].isin(acts["activity_id"])
    log("remittance without activity", "remittances", len(rem), orphan_r.sum(), "dropped")
    rem = rem[~orphan_r]

    # 4. amounts
    nonpos = acts["net"] <= 0
    log("activity net amount <= 0", "activities", len(acts), nonpos.sum(), "quarantined (line + its remittances)")
    quarantined = set(acts.loc[nonpos, "activity_id"])
    acts["dq_amount_mismatch"] = ~nonpos & ((acts["gross"] - acts["patient_share"] - acts["net"]).abs() > 0.011)
    log("gross != patient_share + net (net > 0)", "activities", int((~nonpos).sum()), acts["dq_amount_mismatch"].sum(), "flagged, net kept")

    # 5. codes
    icd = reference.load("icd10cm")
    billable = set(icd.loc[icd["billable"] == 1, "code"])
    claims["dq_invalid_dx"] = ~claims["principal_dx"].isin(billable)
    log("principal diagnosis not a billable ICD-10-CM code", "claims", len(claims), claims["dq_invalid_dx"].sum(),
        "flagged, kept (a real claim error the scrubber must catch)")
    known = set(catalog()["codes"]) | set(catalog()["drugs"])
    unk = ~acts["code"].isin(known)
    log("activity code not in code catalogue", "activities", len(acts), unk.sum(), "quarantined")
    quarantined |= set(acts.loc[unk, "activity_id"])

    # 6. dates
    bad_sub = claims["submission_date"] < claims["encounter_start"]
    log("submission before service date", "claims", len(claims), bad_sub.sum(), "flagged")
    claims["dq_submission_before_service"] = bad_sub
    rem = rem.merge(acts[["activity_id", "claim_id"]], on=["activity_id", "claim_id"], how="left")
    sub = claims.set_index("claim_id")["submission_date"]
    r0 = rem["round"] == 0
    bad_ra = r0 & (rem["date_settlement"] < rem["claim_id"].map(sub))
    log("remittance settlement before claim submission", "remittances", int(r0.sum()), bad_ra.sum(),
        "date set to null (excluded from days-to-payment); amount kept")
    rem["dq_bad_settlement_date"] = bad_ra
    rem.loc[bad_ra, "date_settlement"] = pd.NaT

    # 7. reconciliation: paid over all rounds cannot exceed billed net
    paid = rem.groupby("activity_id")["payment_amount"].sum()
    over = acts.set_index("activity_id")["net"].reindex(paid.index) + 0.01 < paid
    log("total paid across rounds > billed net", "remittances", len(paid), over.sum(), "quarantined")
    quarantined |= set(paid.index[over])
    no_ra = ~acts["activity_id"].isin(rem["activity_id"])
    log("activity with no initial remittance", "activities", len(acts), no_ra.sum(), "flagged (unadjudicated)")

    # 8. claim totals = sum of lines
    tot = acts.groupby("claim_id")["net"].sum().round(2)
    mism = (claims.set_index("claim_id")["net"] - tot.reindex(claims["claim_id"]).values).abs() > 0.05
    log("claim net != sum of line net", "claims", len(claims), mism.sum(), "flagged")
    claims["dq_total_mismatch"] = claims["claim_id"].map(mism).fillna(False).astype(bool)

    # apply quarantine
    log("TOTAL activity lines quarantined", "activities", len(acts), len(quarantined), "excluded from all analysis")
    acts["dq_quarantined"] = acts["activity_id"].isin(quarantined)
    out = dict(d)
    out["claims"], out["activities"], out["remittances"] = claims, acts, rem
    return out, pd.DataFrame(dq)


def main(raw_dir: Path = RAW, clean_dir: Path = CLEAN) -> pd.DataFrame:
    ensure_dirs()
    clean, dq = validate(read_raw(raw_dir))
    for name, df in clean.items():
        df.to_parquet(clean_dir / f"{name}.parquet", index=False)
    dq.to_csv(clean_dir / "data_quality.csv", index=False)
    print(dq.to_string(index=False))
    return dq


if __name__ == "__main__":
    main()
