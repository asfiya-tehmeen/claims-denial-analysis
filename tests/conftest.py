"""Shared fixtures.

mini_clean: a hand-built 8-claim / 20-line clean dataset whose KPIs were calculated by hand
            (see tests/test_kpis.py for the arithmetic).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src import reference
from src.common import REFERENCE

D = pd.Timestamp


@pytest.fixture(scope="session", autouse=True)
def reference_tables():
    if not (REFERENCE / "ncci_ptp.csv").exists():
        reference.main()          # downloads CMS files on first run


# claim: (claim_id, payer, service line, service date, submission date, [line nets], RA0 date)
CLAIMS = [
    ("C1", "P01", "outpatient", "2025-01-10", "2025-01-12", [100, 100, 100], "2025-02-01"),
    ("C2", "P01", "outpatient", "2025-01-15", "2025-01-20", [100, 100], "2025-03-11"),
    ("C3", "P01", "radiology", "2025-02-03", "2025-03-20", [1000], "2025-04-04"),
    ("C4", "P02", "outpatient", "2025-02-10", "2025-02-11", [100, 100, 100, 100], "2025-03-01"),
    ("C5", "P02", "radiology", "2025-03-01", "2025-03-02", [500, 500], "2025-03-30"),
    ("C6", "P02", "outpatient", "2025-03-05", "2025-03-06", [100, 100, 100], "2025-04-30"),
    ("C7", "P01", "radiology", "2025-03-10", "2025-03-11", [200, 300], "2025-04-05"),
    ("C8", "P02", "outpatient", "2025-03-12", "2025-03-13", [100, 100, 100], "2025-04-02"),
]
# (claim, line_no) -> (initial paid, denial code)
INITIAL_DENIALS = {("C2", 2): (0, "AUTH-001"), ("C3", 1): (0, "MNEC-003"), ("C4", 1): (80, "PRCE-001"), ("C6", 3): (0, "ELIG-005")}
# resubmissions: claim -> (date, RA date, {line_no: paid})
RESUBS = {"C2": ("2025-03-20", "2025-04-10", {2: 100}), "C3": ("2025-04-10", "2025-05-20", {1: 0})}
FLAGS = [("C2", 2, "AUTH_MISSING", "Authorisation"), ("C4", 1, "PRCE_ABOVE_CONTRACT", "Price"),
         ("C7", 1, "MNEC_DX_UNSUPPORTED", "Medical necessity")]


def make_mini_clean(out: Path) -> dict[str, pd.DataFrame]:
    claims, acts, rem, resubs = [], [], [], []
    for cid, payer, line, svc, sub, nets, ra0 in CLAIMS:
        claims.append({"claim_id": cid, "member_id": f"M-{payer}", "payer_id": payer, "provider_id": "FAC-HH",
                       "encounter_type": line, "encounter_start": D(svc), "principal_dx": "I10", "gross": float(sum(nets)),
                       "patient_share": 0.0, "net": float(sum(nets)), "submission_date": D(sub), "dq_invalid_dx": False,
                       "dq_submission_before_service": False, "dq_total_mismatch": False})
        for i, n in enumerate(nets, start=1):
            aid = f"{cid}-L{i}"
            acts.append({"activity_id": aid, "claim_id": cid, "line_no": i, "start": D(svc), "type": "CPT",
                         "code": "99213" if line == "outpatient" else "71046", "quantity": 1, "modifier": "",
                         "gross": float(n), "patient_share": 0.0, "net": float(n), "clinician_id": "CLN-001",
                         "prior_auth_id": None, "dq_amount_mismatch": False, "dq_quarantined": False})
            paid, code = INITIAL_DENIALS.get((cid, i), (n, None))
            rem.append({"claim_id": cid, "activity_id": aid, "round": 0, "date_settlement": D(ra0),
                        "payment_amount": float(paid), "denial_code": code, "payment_reference": f"PAY-{cid}-0",
                        "dq_bad_settlement_date": False})
            if cid in RESUBS and i in RESUBS[cid][2]:
                p1 = RESUBS[cid][2][i]
                rem.append({"claim_id": cid, "activity_id": aid, "round": 1, "date_settlement": D(RESUBS[cid][1]),
                            "payment_amount": float(p1), "denial_code": None if p1 else code,
                            "payment_reference": f"PAY-{cid}-1", "dq_bad_settlement_date": False})
        if cid in RESUBS:
            resubs.append({"claim_id": cid, "round": 1, "resubmission_type": "correction", "resubmission_date": D(RESUBS[cid][0])})
    tables = {
        "claims": pd.DataFrame(claims), "activities": pd.DataFrame(acts), "remittances": pd.DataFrame(rem),
        "resubmissions": pd.DataFrame(resubs),
        "members": pd.DataFrame([{"member_id": f"M-{p}", "payer_id": p, "plan_tier": "Premium", "gender": "F",
                                  "birth_date": D("1980-01-01"), "coverage_start": D("2024-01-01"), "coverage_end": D("2026-12-31")}
                                 for p in ("P01", "P02")]),
        "payers": pd.DataFrame([{"payer_id": "P01", "payer_name": "Payer One", "payer_kind": "insurer"},
                                {"payer_id": "P02", "payer_name": "Payer Two", "payer_kind": "TPA"}]),
        "facilities": pd.DataFrame([{"facility_id": "FAC-HH", "facility_name": "Harbour Hospital"}]),
        "clinicians": pd.DataFrame([{"clinician_id": "CLN-001", "specialty": "family_medicine", "facility_id": "FAC-HH"}]),
        "prior_auths": pd.DataFrame([{"prior_auth_id": "PA-X", "claim_id": "C0", "member_id": "M-P01", "payer_id": "P01",
                                      "request_date": D("2025-01-01"), "status": "approved", "valid_from": D("2025-01-01"),
                                      "valid_to": D("2025-01-31")}]),
        "scrubber_flags": pd.DataFrame([{"activity_id": f"{c}-L{i}", "rule": r, "category": cat, "suggested_fix": "x"}
                                        for c, i, r, cat in FLAGS]),
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
    return tables


@pytest.fixture(scope="session")
def mini_db(tmp_path_factory):
    from src.build_db import build
    d = tmp_path_factory.mktemp("mini")
    make_mini_clean(d / "clean")
    con = build(db_path=d / "mini.duckdb", clean_dir=d / "clean")
    yield con
    con.close()


@pytest.fixture(scope="session")
def small_world(tmp_path_factory):
    """A small simulated dataset (raw + sealed) in a temp folder."""
    from src.generator import generate
    d = tmp_path_factory.mktemp("small")
    counts = generate(n_claims=8000, n_members=4000, out_dir=d / "raw", sealed_dir=d / "raw" / "sealed")
    return d, counts
