"""Rule-based pre-submission claim scrubber.

Uses only what the provider knows at submission: member coverage on file, the payers' published
prior-auth lists as held at the start of the period, plan benefits, contract prices, real CMS
NCCI PTP / MUE edits, ICD-10-CM validity and the clinical support table in config/catalog.yaml.
Output: one row per (activity, rule) hit in data/clean/scrubber_flags.parquet.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import reference
from src.common import CLEAN, catalog
from src.generator import Clinical

RULES = {
    # rule: (category, suggested fix)
    "ELIG_OUT_OF_COVERAGE": ("Eligibility", "Service date outside coverage on file: re-verify eligibility, bill correct payer or self-pay"),
    "AUTH_MISSING": ("Authorisation", "Payer requires prior approval for this service: obtain approval before submission"),
    "AUTH_EXPIRED": ("Authorisation", "Service performed after approval expired: request extension / new approval"),
    "CODE_INVALID_DX": ("Coding", "Principal diagnosis is a non-billable ICD-10-CM header code: code to the full billable code"),
    "CODE_MUE_UNITS": ("Coding", "Units exceed the CMS MUE value for this code: check units against documentation"),
    "CODE_NCCI_BUNDLED": ("Coding", "NCCI pair with modifier indicator 0: column-2 code is not separately payable, remove it"),
    "CODE_NCCI_MODIFIER": ("Coding", "NCCI pair allows a modifier: append 25/59 if documentation supports a distinct service"),
    "DUPL_SAME_SERVICE": ("Duplicate", "Same member, code and service date already billed on an earlier claim: do not resubmit as new"),
    "TIME_FILING_LIMIT": ("Timely filing", "Submitted more than 90 days after service: expect TIME-001"),
    "PRCE_ABOVE_CONTRACT": ("Price", "Billed unit price above contract price: re-price from current contract"),
    "NCOV_PLAN_EXCLUSION": ("Non-covered", "Service / diagnosis / drug excluded on this plan tier: inform patient, collect as self-pay"),
    "BENX_LIMIT_REACHED": ("Non-covered", "Annual physiotherapy session limit reached: collect from patient or seek exception"),
    "MNEC_DX_UNSUPPORTED": ("Medical necessity", "Diagnosis does not support this service: add supporting diagnosis / documentation"),
}
FILING_LIMIT_DAYS = 90


def load_clean() -> dict[str, pd.DataFrame]:
    names = ["claims", "activities", "members", "prior_auths", "payer_auth_rules", "plan_benefits", "contract_prices"]
    d = {n: pd.read_parquet(CLEAN / f"{n}.parquet") for n in names}
    d["activities"] = d["activities"][~d["activities"]["dq_quarantined"]]
    return d


def line_frame(d: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Activity lines joined to everything known pre-submission."""
    cat = catalog()
    a = d["activities"].merge(
        d["claims"][["claim_id", "member_id", "payer_id", "provider_id", "encounter_type", "principal_dx", "submission_date"]],
        on="claim_id")
    a = a.merge(d["members"][["member_id", "plan_tier", "coverage_start", "coverage_end", "birth_date", "gender"]], on="member_id")
    a = a.merge(d["prior_auths"][["prior_auth_id", "valid_to"]], on="prior_auth_id", how="left")
    a = a.merge(d["contract_prices"], on=["payer_id", "code"], how="left")
    a = a.rename(columns={"encounter_type": "service_line"})
    a["high_cost"] = a["code"].map(lambda c: bool(cat["codes"].get(c, {}).get("high_cost")))
    return a


def scrub(d: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    cat = catalog(); cl = Clinical(cat)
    a = line_frame(d)
    hits: list[pd.DataFrame] = []

    def add(mask, rule):
        sel = a.loc[mask, ["activity_id"]].copy()
        sel["rule"] = rule
        hits.append(sel)

    # eligibility (coverage on file)
    add((a["start"] < a["coverage_start"]) | (a["start"] > a["coverage_end"]), "ELIG_OUT_OF_COVERAGE")

    # authorisation, from the published lists held by the provider
    rules = d["payer_auth_rules"]
    all_lines = set(zip(rules.loc[rules.scope == "all", "payer_id"], rules.loc[rules.scope == "all", "service_line"]))
    hc = set(rules.loc[rules.scope == "high_cost", "payer_id"])
    needs = np.array([(p, s) in all_lines for p, s in zip(a["payer_id"], a["service_line"])])
    needs |= (a["service_line"].eq("radiology") & a["high_cost"] & a["payer_id"].isin(hc)).to_numpy()
    add(needs & a["prior_auth_id"].isna().to_numpy(), "AUTH_MISSING")
    add(a["prior_auth_id"].notna() & (a["start"] > a["valid_to"]), "AUTH_EXPIRED")

    # coding
    icd = reference.load("icd10cm"); billable = set(icd.loc[icd.billable == 1, "code"])
    add(~a["principal_dx"].isin(billable), "CODE_INVALID_DX")
    mue = dict(zip(*reference.load("mue")[["code", "mue_value"]].T.values))
    add(a["quantity"] > a["code"].map(mue).fillna(np.inf), "CODE_MUE_UNITS")
    ptp = reference.load("ncci_ptp")
    pair = a[["claim_id", "activity_id", "code", "modifier"]].merge(
        a[["claim_id", "code"]].rename(columns={"code": "col1"}), on="claim_id")
    pair = pair.merge(ptp, left_on=["col1", "code"], right_on=["col1", "col2"])
    b0 = set(pair.loc[pair.modifier_indicator == 0, "activity_id"])
    b1 = set(pair.loc[(pair.modifier_indicator == 1) & (pair.modifier.fillna("") == ""), "activity_id"])
    add(a["activity_id"].isin(b0), "CODE_NCCI_BUNDLED")
    add(a["activity_id"].isin(b1 - b0), "CODE_NCCI_MODIFIER")

    # duplicates: same member + code + service date billed on an EARLIER-submitted claim
    k = a.sort_values(["submission_date", "claim_id"])
    first_claim = k.groupby(["member_id", "code", "start"])["claim_id"].transform("first")
    add(a["activity_id"].isin(k.loc[k["claim_id"] != first_claim, "activity_id"]), "DUPL_SAME_SERVICE")

    # timely filing (assumption: 90 days, see SOURCES.md)
    add((a["submission_date"] - a["start"]).dt.days > FILING_LIMIT_DAYS, "TIME_FILING_LIMIT")

    # price vs contract
    add(a["gross"] / a["quantity"] > a["contract_price"] + 0.01, "PRCE_ABOVE_CONTRACT")

    # plan exclusions and benefit limits
    pb = d["plan_benefits"].set_index("plan_tier")
    split = lambda s: set(str(s).split("|")) if isinstance(s, str) and s else set()
    ex_code = {t: split(pb.at[t, "excluded_codes"]) for t in pb.index}
    ex_dx = {t: split(pb.at[t, "excluded_dx"]) for t in pb.index}
    ex_drug = {t: split(pb.at[t, "excluded_drug_classes"]) for t in pb.index}
    excl = [c in ex_code[t] or dx in ex_dx[t] or cl.drug_cls.get(c) in ex_drug[t]
            for c, dx, t in zip(a["code"], a["principal_dx"], a["plan_tier"])]
    add(np.array(excl), "NCOV_PLAN_EXCLUSION")
    phys = d["claims"][d["claims"].encounter_type == "physiotherapy"][["claim_id", "member_id", "encounter_start", "submission_date"]]
    phys = phys.assign(year=phys.encounter_start.dt.year).sort_values(["encounter_start", "submission_date", "claim_id"])
    # count each service day once (a duplicate claim is not a new session)
    phys["session_no"] = phys.groupby(["member_id", "year"])["encounter_start"].rank(method="dense")
    limits = pb["physio_sessions_per_year"]
    over = phys.merge(d["members"][["member_id", "plan_tier"]], on="member_id")
    limit = pd.to_numeric(over["plan_tier"].map(limits), errors="coerce").fillna(np.inf)
    over = over[pd.to_numeric(over["session_no"], errors="coerce").astype(float) > limit]
    add(a["claim_id"].isin(over["claim_id"]), "BENX_LIMIT_REACHED")

    # medical necessity: diagnosis gives no support at all for the service
    sup = [cl.support(c, dx) if dx in billable else "strong" for c, dx in zip(a["code"], a["principal_dx"])]
    add(np.array(sup) == "none", "MNEC_DX_UNSUPPORTED")

    flags = pd.concat(hits, ignore_index=True)
    flags["category"] = flags["rule"].map(lambda r: RULES[r][0])
    flags["suggested_fix"] = flags["rule"].map(lambda r: RULES[r][1])
    return flags, a


def main() -> pd.DataFrame:
    flags, a = scrub(load_clean())
    flags.to_parquet(CLEAN / "scrubber_flags.parquet", index=False)
    n_lines = len(a); n_flag = flags["activity_id"].nunique()
    print(f"scrubber: {len(flags):,} rule hits on {n_flag:,} of {n_lines:,} lines ({100 * n_flag / n_lines:.1f}%)")
    print(flags["rule"].value_counts().to_string())
    return flags


if __name__ == "__main__":
    main()
