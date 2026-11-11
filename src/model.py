"""Denial-risk models on a time-based split: baseline, rules, logistic regression, LightGBM.

Train months 1-15, validation 16-18, test 19-24 (service month). Writes test predictions to
data/gold/predictions.parquet and metrics to reports/metrics.json["model"].
The best-achievable (oracle) scores need the sealed truth, so they are computed in src/score.py.
"""
from __future__ import annotations

import lightgbm as lgb
import matplotlib
import numpy as np
import pandas as pd
import shap
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.common import FIGURES, GOLD, TEST_MONTHS, TRAIN_MONTHS, VALID_MONTHS, update_metrics
from src.features import CATEGORICAL, FEATURES, NUMERIC, build_features, labels

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SEED = 42


def split(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {"train": df[df.sim_month.isin(TRAIN_MONTHS)], "valid": df[df.sim_month.isin(VALID_MONTHS)],
            "test": df[df.sim_month.isin(TEST_MONTHS)]}


def scores(y, p) -> dict:
    return {"auc": float(roc_auc_score(y, p)), "auc_pr": float(average_precision_score(y, p)),
            "brier": float(brier_score_loss(y, np.clip(p, 0, 1)))}


def baseline_model(train: pd.DataFrame):
    """Historical denial rate by payer x service line (smoothed towards the overall rate)."""
    prior, k = train.y.mean(), 50
    g = train.groupby(["payer_id", "service_line"], observed=True)["y"].agg(["sum", "count"])
    rate = ((g["sum"] + k * prior) / (g["count"] + k)).rename("p")
    return lambda d: d.join(rate, on=["payer_id", "service_line"])["p"].fillna(prior).to_numpy()


def fit_lr(train, valid):
    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=20), CATEGORICAL),
        ("num", StandardScaler(), NUMERIC)])
    best = None
    for C in (0.03, 0.1, 0.3, 1.0):
        m = make_pipeline(pre, LogisticRegression(C=C, max_iter=2000))
        m.fit(train[FEATURES], train.y)
        s = average_precision_score(valid.y, m.predict_proba(valid[FEATURES])[:, 1])
        if best is None or s > best[0]:
            best = (s, C, m)
    return best[2], best[1]


def fit_lgbm(train, valid):
    m = lgb.LGBMClassifier(n_estimators=2000, learning_rate=0.03, num_leaves=31, min_child_samples=40,
                           subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                           max_cat_to_onehot=8, cat_smooth=20, random_state=SEED, verbose=-1,
                           deterministic=True, force_col_wise=True, n_jobs=1)
    m.fit(train[FEATURES], train.y, eval_set=[(valid[FEATURES], valid.y)], eval_metric="average_precision",
          callbacks=[lgb.early_stopping(100, verbose=False)])
    return m


def main() -> dict:
    x = build_features()
    y = labels()
    df = x.merge(y, on="activity_id").sort_values("activity_id", kind="mergesort").reset_index(drop=True)
    df["y"] = df["is_initial_denied"].astype(int)
    s = split(df)
    tr, va, te = s["train"], s["valid"], s["test"]

    base = baseline_model(tr)
    lr, C = fit_lr(tr, va)
    gbm = fit_lgbm(tr, va)
    preds = {
        "baseline": base(te),
        "rules": te["n_scrubber_flags"].clip(upper=1).to_numpy().astype(float),
        "logreg": lr.predict_proba(te[FEATURES])[:, 1],
        "lightgbm": gbm.predict_proba(te[FEATURES])[:, 1],
    }
    res = {k: scores(te.y, v) for k, v in preds.items()}
    # rules as a classifier: precision / recall of "any flag"
    flagged = preds["rules"] == 1
    res["rules"].update({"precision": float(te.y[flagged].mean()), "recall": float(flagged[te.y == 1].mean()),
                         "share_flagged": float(flagged.mean())})
    # where the scrubber is silent, how much signal is left?
    clean = ~flagged
    res["on_scrubber_clean_lines"] = {
        "lines": int(clean.sum()), "denial_rate": float(te.y[clean].mean()),
        **{k: scores(te.y[clean], preds[k][clean]) for k in ("baseline", "logreg", "lightgbm")}}

    out = te[["activity_id", "claim_id", "submission_date", "service_date", "payer_id", "service_line", "net",
              "n_scrubber_flags", "y", "initial_denied_amount"]].copy()
    for k, v in preds.items():
        out[f"p_{k}"] = v
    out.to_parquet(GOLD / "predictions.parquet", index=False)

    # calibration curves (test)
    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.plot([0, 1], [0, 1], ls=":", c="grey", lw=1)
    for k, c in (("logreg", "#2a6fbb"), ("lightgbm", "#d1495b"), ("baseline", "#999999")):
        fr, mp = calibration_curve(te.y, preds[k], n_bins=10, strategy="quantile")
        ax.plot(mp, fr, marker="o", ms=3, c=c, label=k)
    ax.set_xlabel("Predicted denial probability"); ax.set_ylabel("Observed denial rate (test months)")
    ax.set_title("Calibration on the time-based holdout", fontsize=10); ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(FIGURES / "calibration.png", dpi=150); plt.close(fig)

    # SHAP drivers for LightGBM (sample of test lines)
    samp = te.sample(min(5000, len(te)), random_state=SEED)
    sv = shap.TreeExplainer(gbm).shap_values(samp[FEATURES])
    sv = sv[1] if isinstance(sv, list) else sv
    imp = pd.Series(np.abs(sv).mean(axis=0), index=FEATURES).sort_values(ascending=False)
    shap.summary_plot(sv, samp[FEATURES], max_display=15, show=False, plot_size=(8, 6))
    plt.tight_layout(); plt.savefig(FIGURES / "shap_summary.png", dpi=150); plt.close("all")

    metrics = {
        "split": {"train_months": [min(TRAIN_MONTHS), max(TRAIN_MONTHS)], "valid_months": [min(VALID_MONTHS), max(VALID_MONTHS)],
                  "test_months": [min(TEST_MONTHS), max(TEST_MONTHS)],
                  "train_lines": int(len(tr)), "valid_lines": int(len(va)), "test_lines": int(len(te)),
                  "test_denial_rate": float(te.y.mean())},
        "test": res, "logreg_C": C, "lightgbm_trees": int(gbm.best_iteration_ or gbm.n_estimators),
        "shap_top_features": {k: float(v) for k, v in imp.head(15).items()},
    }
    update_metrics("model", metrics)
    print(pd.DataFrame({k: v for k, v in res.items() if k != "on_scrubber_clean_lines"}).T.round(4).to_string())
    print("scrubber-clean lines:", {k: (round(v["auc"], 4) if isinstance(v, dict) else v) for k, v in res["on_scrubber_clean_lines"].items()})
    print(imp.head(15).round(4).to_string())
    return metrics


if __name__ == "__main__":
    main()
