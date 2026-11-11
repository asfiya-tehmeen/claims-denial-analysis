"""Daily pre-submission review worklists under a fixed coder capacity (test months only).

Each policy ranks the lines submitted on a day and the coder reviews the top `capacity` lines.
This module only CHOOSES lines (it never sees outcomes). src/score.py values the choices against
the sealed truth (which denials were avoidable and at what fix rate).

Policies
  rules            scrubber-flagged lines, largest net amount first
  baseline         historical payer x service-line denial rate x net amount
  logreg           predicted denial probability x net amount
  lightgbm         predicted denial probability x net amount
  rules_then_lgbm  scrubber-flagged lines first (ranked by LightGBM expected loss), spare capacity to
                   unflagged lines by LightGBM expected loss
"""
from __future__ import annotations

import pandas as pd

from src.common import GOLD, review_config, update_metrics

POLICIES = ["rules", "baseline", "logreg", "lightgbm", "rules_then_lgbm"]


def capacity_per_day(cfg: dict | None = None) -> int:
    cfg = cfg or review_config()
    return int(cfg["coders"] * cfg["review_hours_per_day"] * 60 // cfg["minutes_per_line"])


def rank_key(df: pd.DataFrame, policy: str) -> pd.Series:
    flagged = (df["n_scrubber_flags"] > 0).astype(float)
    if policy == "rules":
        return flagged * 1e9 + flagged * df["net"]
    if policy == "rules_then_lgbm":
        return flagged * 1e9 + df["p_lightgbm"] * df["net"]
    return df[f"p_{policy}"] * df["net"]


def select(pred: pd.DataFrame, capacity: int) -> pd.DataFrame:
    rows = []
    for policy in POLICIES:
        d = pred.assign(score=rank_key(pred, policy))
        if policy == "rules":
            d = d[d["n_scrubber_flags"] > 0]          # rules alone only review what they flag
        top = (d.sort_values(["submission_date", "score", "activity_id"], ascending=[True, False, True], kind="mergesort")
                 .groupby("submission_date").head(capacity))
        rows.append(top[["activity_id", "submission_date"]].assign(policy=policy))
    return pd.concat(rows, ignore_index=True)


def main() -> pd.DataFrame:
    cfg = review_config()
    cap = capacity_per_day(cfg)
    pred = pd.read_parquet(GOLD / "predictions.parquet")
    sel = select(pred, cap)
    sel.to_parquet(GOLD / "worklist_selections.parquet", index=False)
    days = pred["submission_date"].nunique()
    summary = {"capacity_lines_per_day": cap, "submission_days": int(days),
               "coder_hours": float(days * cfg["coders"] * cfg["review_hours_per_day"]),
               "lines_reviewed": sel.groupby("policy").size().to_dict(),
               "test_lines": int(len(pred)), "assumptions": cfg}
    update_metrics("worklist_design", summary)
    print(summary)
    return sel


if __name__ == "__main__":
    main()
