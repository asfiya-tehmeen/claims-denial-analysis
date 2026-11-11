"""Validator finds every planted export problem and quarantines bad lines."""
import json

import pandas as pd

from src.validate import read_raw, validate


def test_validator_finds_planted_problems(small_world):
    d, _ = small_world
    key = json.loads((d / "raw" / "sealed" / "answer_key.json").read_text())["data_quality"]
    clean, dq = validate(read_raw(d / "raw"))
    dq = dq.set_index("check")
    assert dq.at["exact duplicate remittance rows", "rows_failed"] == key["remittance_dup_rows"]
    assert dq.at["activity net amount <= 0", "rows_failed"] == len(key["nonpositive_net_activity_ids"])
    assert set(clean["activities"].loc[clean["activities"].dq_amount_mismatch, "activity_id"]) == set(key["gross_mismatch_activity_ids"])
    bad = set(clean["remittances"].loc[clean["remittances"].dq_bad_settlement_date, "claim_id"])
    assert bad == set(key["ra_before_submission_claim_ids"])
    assert set(key["nonpositive_net_activity_ids"]) <= set(clean["activities"].loc[clean["activities"].dq_quarantined, "activity_id"])


def test_duplicate_primary_key_fails_loudly(small_world):
    d, _ = small_world
    raw = read_raw(d / "raw")
    raw["claims"] = pd.concat([raw["claims"], raw["claims"].head(1)])
    try:
        validate(raw)
    except ValueError:
        return
    raise AssertionError("duplicate claim_id was not rejected")
