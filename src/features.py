"""Pre-submission feature matrix: one row per claim line, only fields known BEFORE submission.

tests/test_leakage.py enforces that no remittance-side field reaches the features.
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from src.common import CLEAN, DB_PATH, catalog
from src.generator import Clinical
from src.scrubber import RULES

CATEGORICAL = ["payer_id", "service_line", "facility_id", "clinician_id", "specialty", "plan_tier", "code",
               "code_type", "gender", "principal_dx"]
NUMERIC = ["net", "log_net", "quantity", "age", "has_prior_auth", "has_modifier", "days_service_to_submission",
           "days_to_coverage_end", "days_since_coverage_start", "claim_lines", "claim_net", "dx_support",
           "dx_invalid", "physio_session_no", "n_scrubber_flags"] + [f"flag_{r}" for r in RULES]
FEATURES = CATEGORICAL + NUMERIC

# Anything that is only known after the payer responds. Never a feature.
FORBIDDEN = {"initial_paid", "initial_denied_amount", "is_initial_denied", "initial_denial_code", "initial_denial_category",
             "is_avoidable_denial", "was_resubmitted", "recovered_on_resubmission", "was_overturned",
             "final_denied_amount", "is_final_denied", "days_to_initial_ra", "initial_ra_date", "last_settlement_date",
             "claim_first_pass_paid", "initial_ra_date_key", "initial_denial_code_key", "payment_amount",
             "denial_code", "settlement_date"}

PRE_SUBMISSION_SQL = """
SELECT f.activity_id, f.claim_id, f.payer_id, f.service_line, f.facility_id, f.clinician_id, pr.specialty,
       f.plan_tier, f.code, f.code_type, f.quantity, f.modifier, f.has_prior_auth, f.net, f.member_id,
       f.service_date, f.submission_date, f.days_service_to_submission, c.principal_dx, c.dq_invalid_dx,
       m.gender, m.birth_date, m.coverage_start, m.coverage_end, d.sim_month
FROM fact_claim_line f
JOIN dim_provider pr USING (provider_key)
JOIN stg_claims c USING (claim_id)
JOIN raw_members m ON m.member_id = f.member_id
JOIN dim_date d ON d.date = f.service_date
ORDER BY f.activity_id
"""
LABEL_SQL = "SELECT activity_id, is_initial_denied, initial_denied_amount FROM fact_claim_line"


def build_features(con: duckdb.DuckDBPyConnection | None = None, flags: pd.DataFrame | None = None) -> pd.DataFrame:
    own = con is None
    con = con or duckdb.connect(str(DB_PATH), read_only=True)
    x = con.execute(PRE_SUBMISSION_SQL).df()
    if own:
        con.close()
    if flags is None:
        flags = pd.read_parquet(CLEAN / "scrubber_flags.parquet")
    cl = Clinical(catalog())
    for c in ["service_date", "submission_date", "birth_date", "coverage_start", "coverage_end"]:
        x[c] = pd.to_datetime(x[c])
    x["log_net"] = np.log1p(x["net"].clip(lower=0))
    x["age"] = (x["service_date"] - x["birth_date"]).dt.days / 365.25
    x["has_prior_auth"] = x["has_prior_auth"].astype(int)
    x["has_modifier"] = (x["modifier"].fillna("") != "").astype(int)
    x["days_to_coverage_end"] = (x["coverage_end"] - x["service_date"]).dt.days
    x["days_since_coverage_start"] = (x["service_date"] - x["coverage_start"]).dt.days
    x["claim_lines"] = x.groupby("claim_id")["activity_id"].transform("size")
    x["claim_net"] = x.groupby("claim_id")["net"].transform("sum")
    x["dx_invalid"] = x["dq_invalid_dx"].astype(int)
    x["dx_support"] = [{"strong": 0, "weak": 1, "none": 2}[cl.support(c, d)] if not inv else 0
                       for c, d, inv in zip(x["code"], x["principal_dx"], x["dx_invalid"])]
    phys = x[x.service_line == "physiotherapy"].drop_duplicates("claim_id")[["claim_id", "member_id", "service_date"]]
    phys["session"] = phys.groupby([phys.member_id, phys.service_date.dt.year])["service_date"].rank(method="dense")
    x["physio_session_no"] = x["claim_id"].map(phys.set_index("claim_id")["session"]).fillna(0)
    f = flags.assign(v=1).pivot_table(index="activity_id", columns="rule", values="v", aggfunc="max", fill_value=0)
    f = f.reindex(columns=list(RULES), fill_value=0).add_prefix("flag_")
    x = x.merge(f, left_on="activity_id", right_index=True, how="left")
    x[f.columns] = x[f.columns].fillna(0).astype(int)
    x["n_scrubber_flags"] = x[f.columns].sum(axis=1)
    x = x.sort_values("activity_id", kind="mergesort").reset_index(drop=True)   # row order drives bagging
    for c in CATEGORICAL:
        x[c] = pd.Categorical(x[c], categories=sorted(x[c].dropna().unique()))   # stable category codes
    return x


def labels(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    own = con is None
    con = con or duckdb.connect(str(DB_PATH), read_only=True)
    y = con.execute(LABEL_SQL).df()
    if own:
        con.close()
    return y
