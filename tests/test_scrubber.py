"""Every scrubber rule, on hand-written claims. A clean base claim must raise no flag."""
import pandas as pd
import pytest

from src.scrubber import scrub

D = pd.Timestamp


def world(claims: list[dict], auths: list[dict] | None = None, tier="Premium"):
    """claims: dicts with claim_id, line, svc, sub, dx, lines=[(code, qty, gross, modifier)], auth."""
    c_rows, a_rows = [], []
    for c in claims:
        c_rows.append({"claim_id": c["claim_id"], "member_id": "M1", "payer_id": "P01", "provider_id": "FAC-HH",
                       "encounter_type": c.get("line", "outpatient"), "encounter_start": D(c.get("svc", "2025-06-01")),
                       "principal_dx": c.get("dx", "I10"), "submission_date": D(c.get("sub", "2025-06-05"))})
        for i, (code, qty, gross, mod) in enumerate(c["lines"], start=1):
            a_rows.append({"activity_id": f"{c['claim_id']}-{i}", "claim_id": c["claim_id"], "line_no": i,
                           "start": D(c.get("svc", "2025-06-01")), "code": code, "quantity": qty, "gross": gross,
                           "net": gross, "modifier": mod, "prior_auth_id": c.get("auth"), "dq_quarantined": False})
    prices = {"99213": 250, "96372": 60, "72148": 1800, "43239": 3800, "43235": 3000, "97035": 80, "97110": 120}
    return {
        "claims": pd.DataFrame(c_rows), "activities": pd.DataFrame(a_rows),
        "members": pd.DataFrame([{"member_id": "M1", "payer_id": "P01", "plan_tier": tier, "gender": "F",
                                  "birth_date": D("1980-01-01"), "coverage_start": D("2025-01-01"), "coverage_end": D("2026-12-31")}]),
        "prior_auths": pd.DataFrame(auths or [{"prior_auth_id": "PA-OK", "valid_to": D("2025-12-31")}]),
        "payer_auth_rules": pd.DataFrame([{"payer_id": "P01", "service_line": "day_surgery", "scope": "all"},
                                          {"payer_id": "P01", "service_line": "radiology", "scope": "high_cost"}]),
        "plan_benefits": pd.DataFrame([{"plan_tier": "Premium", "copay": 0.0, "physio_sessions_per_year": None,
                                        "excluded_codes": "", "excluded_dx": "", "excluded_drug_classes": ""},
                                       {"plan_tier": "Basic", "copay": 0.0, "physio_sessions_per_year": 12,
                                        "excluded_codes": "97035", "excluded_dx": "Z0000", "excluded_drug_classes": "vitamin"}]),
        "contract_prices": pd.DataFrame([{"payer_id": "P01", "code": k, "contract_price": v} for k, v in prices.items()]),
    }


def rules_hit(w) -> dict[str, set[str]]:
    flags, _ = scrub(w)
    return flags.groupby("activity_id")["rule"].apply(set).to_dict()


BASE = {"claim_id": "C1", "lines": [("99213", 1, 250.0, "")]}


def test_clean_claim_has_no_flags():
    assert rules_hit(world([BASE])) == {}


@pytest.mark.parametrize("change, expected", [
    ({"svc": "2027-01-05", "sub": "2027-01-06"}, "ELIG_OUT_OF_COVERAGE"),
    ({"dx": "M545"}, "CODE_INVALID_DX"),
    ({"lines": [("99213", 3, 750.0, "")]}, "CODE_MUE_UNITS"),
    ({"sub": "2025-09-15"}, "TIME_FILING_LIMIT"),
    ({"lines": [("99213", 1, 300.0, "")]}, "PRCE_ABOVE_CONTRACT"),
])
def test_single_rule(change, expected):
    assert rules_hit(world([{**BASE, **change}])) == {"C1-1": {expected}}


def test_auth_missing_and_expired_on_high_cost_radiology():
    mri = {"claim_id": "C1", "line": "radiology", "dx": "M5416", "lines": [("72148", 1, 1800.0, "")]}
    assert rules_hit(world([mri])) == {"C1-1": {"AUTH_MISSING"}}
    expired = world([{**mri, "auth": "PA-OLD"}], auths=[{"prior_auth_id": "PA-OLD", "valid_to": D("2025-05-01")}])
    assert rules_hit(expired) == {"C1-1": {"AUTH_EXPIRED"}}
    assert rules_hit(world([{**mri, "auth": "PA-OK"}])) == {}


def test_ncci_bundled_and_modifier():
    egd = {"claim_id": "C1", "line": "day_surgery", "dx": "K219", "auth": "PA-OK",
           "lines": [("43239", 1, 3800.0, ""), ("43235", 1, 3000.0, "")]}
    assert rules_hit(world([egd])) == {"C1-2": {"CODE_NCCI_BUNDLED"}}          # indicator 0
    inj = {"claim_id": "C1", "lines": [("99213", 1, 250.0, ""), ("96372", 1, 60.0, "")]}
    assert rules_hit(world([inj])) == {"C1-1": {"CODE_NCCI_MODIFIER"}}         # 96372 / E&M, indicator 1
    inj_mod = {"claim_id": "C1", "lines": [("99213", 1, 250.0, "25"), ("96372", 1, 60.0, "")]}
    assert rules_hit(world([inj_mod])) == {}


def test_duplicate_flags_only_the_later_claim():
    first = {**BASE, "claim_id": "C1", "sub": "2025-06-05"}
    again = {**BASE, "claim_id": "C2", "sub": "2025-06-25"}
    assert rules_hit(world([first, again])) == {"C2-1": {"DUPL_SAME_SERVICE"}}


def test_plan_exclusion_and_benefit_limit():
    ultra = {"claim_id": "C1", "line": "physiotherapy", "dx": "M5416", "lines": [("97035", 1, 80.0, "")]}
    assert rules_hit(world([ultra], tier="Basic")) == {"C1-1": {"NCOV_PLAN_EXCLUSION"}}
    sessions = [{"claim_id": f"P{i:02d}", "line": "physiotherapy", "dx": "M5416", "svc": f"2025-06-{i:02d}",
                 "sub": f"2025-06-{i:02d}", "lines": [("97110", 1, 120.0, "")]} for i in range(1, 14)]
    hits = rules_hit(world(sessions, tier="Basic"))
    assert hits == {"P13-1": {"BENX_LIMIT_REACHED"}}                          # 13th session, limit 12


def test_unsupported_diagnosis():
    mri = {"claim_id": "C1", "line": "radiology", "dx": "J069", "auth": "PA-OK", "lines": [("72148", 1, 1800.0, "")]}
    assert rules_hit(world([mri])) == {"C1-1": {"MNEC_DX_UNSUPPORTED"}}
