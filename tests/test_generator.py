"""Generator: reproducible, every denial mechanism fires, planted effects are present."""
import hashlib
import json

import pandas as pd

from src.generator import MECHANISMS, generate


def _digest(folder):
    h = hashlib.sha256()
    for name in sorted(p.name for p in folder.glob("*.csv")):
        h.update((folder / name).read_bytes())
    return h.hexdigest()


def test_same_seed_same_output(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(n_claims=1500, n_members=900, out_dir=a, sealed_dir=a / "sealed")
    generate(n_claims=1500, n_members=900, out_dir=b, sealed_dir=b / "sealed")
    assert _digest(a) == _digest(b)


def test_different_seed_different_output(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(n_claims=1500, n_members=900, out_dir=a, sealed_dir=a / "sealed")
    generate(n_claims=1500, n_members=900, out_dir=b, sealed_dir=b / "sealed", seed=99)
    assert _digest(a) != _digest(b)


def test_every_mechanism_produces_denials(small_world):
    d, _ = small_world
    t = pd.read_parquet(d / "raw" / "sealed" / "line_truth.parquet")
    seen = set(t.loc[t.denied_initial, "mechanism"])
    assert set(MECHANISMS) <= seen, set(MECHANISMS) - seen


def test_rates_and_money_are_sane(small_world):
    d, _ = small_world
    t = pd.read_parquet(d / "raw" / "sealed" / "line_truth.parquet")
    rate = t.denied_amount_initial.sum() / t.net.sum()
    assert 0.05 < rate < 0.25
    assert (t.final_denied_amount <= t.denied_amount_initial + 0.01).all()
    assert (t.recovered_amount >= 0).all()
    rem = pd.read_csv(d / "raw" / "remittances.csv").drop_duplicates()
    acts = pd.read_csv(d / "raw" / "activities.csv").set_index("activity_id")
    paid = rem.groupby("activity_id").payment_amount.sum()
    ok = acts.loc[paid.index, "net"]
    assert ((paid <= ok + 0.01) | (ok <= 0)).mean() > 0.995    # the rest are planted DQ rows


def test_planted_auth_change_raises_auth_breaches(small_world):
    d, _ = small_world
    key = json.loads((d / "raw" / "sealed" / "answer_key.json").read_text())
    pc = key["effects"]["auth_policy_change"]
    t = pd.read_parquet(d / "raw" / "sealed" / "line_truth.parquet")
    acts = pd.read_csv(d / "raw" / "activities.csv", parse_dates=["start"])[["activity_id", "start"]]
    t = t.merge(acts, on="activity_id")
    s = t[(t.payer_id == pc["payer_id"]) & (t.line == pc["service_line"])]
    before = (s[s.start < pc["change_date"]].p_AUTH > 0.5).mean()
    after = (s[s.start >= pc["change_date"]].p_AUTH > 0.5).mean()
    assert after > before + 0.02
