"""Final scoring step: the ONLY module that reads data/raw/sealed/ (enforced by tests/test_sealed.py).

Scores what the blind pipeline produced against the generator's truth:
  1. best-achievable AUC / AUC-PR / Brier (true denial probabilities) next to the models
  2. AED recovered per coder hour for each worklist policy (bootstrap CIs over days)
  3. change detection: weeks to detect the planted authorisation change, false alarms
  4. answer-key recovery table for all planted effects
  5. validator catch rate for planted data-quality problems, scrubber rule precision
"""
from __future__ import annotations

import json

import duckdb
import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from src.common import CLEAN, DB_PATH, FIGURES, GOLD, SEALED, catalog, review_config, update_metrics
from src.detect_change import BASELINE_WEEKS
from src.worklist import POLICIES, select

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

TOP_N = 3
RULE_MECH = {"ELIG_OUT_OF_COVERAGE": "ELIG", "AUTH_MISSING": "AUTH", "AUTH_EXPIRED": "AUTH", "CODE_INVALID_DX": "CODE_DX",
             "CODE_MUE_UNITS": "CODE_MUE", "CODE_NCCI_BUNDLED": "CODE_NCCI0", "CODE_NCCI_MODIFIER": "CODE_MOD",
             "DUPL_SAME_SERVICE": "DUPL", "TIME_FILING_LIMIT": "TIME", "PRCE_ABOVE_CONTRACT": "PRCE",
             "NCOV_PLAN_EXCLUSION": "NCOV", "BENX_LIMIT_REACHED": "BENX", "MNEC_DX_UNSUPPORTED": "MNEC"}


def unseal():
    key = json.loads((SEALED / "answer_key.json").read_text())
    truth = pd.read_parquet(SEALED / "line_truth.parquet")
    return key, truth


def ceiling(pred: pd.DataFrame, truth: pd.DataFrame) -> dict:
    d = pred.merge(truth[["activity_id", "p_total"]], on="activity_id")
    out = {"oracle": {"auc": float(roc_auc_score(d.y, d.p_total)), "auc_pr": float(average_precision_score(d.y, d.p_total)),
                      "brier": float(brier_score_loss(d.y, d.p_total))}}
    for m in ("baseline", "rules", "logreg", "lightgbm"):
        out[m] = {"auc": float(roc_auc_score(d.y, d[f"p_{m}"])), "auc_pr": float(average_precision_score(d.y, d[f"p_{m}"])),
                  "brier": float(brier_score_loss(d.y, d[f"p_{m}"]))}
    for m in ("logreg", "lightgbm"):
        out[m]["share_of_oracle_auc_pr"] = out[m]["auc_pr"] / out["oracle"]["auc_pr"]
    return out


def worklist_value(pred: pd.DataFrame, truth: pd.DataFrame, cfg: dict) -> tuple[dict, pd.DataFrame]:
    fix = cfg["fix_rate"]
    t = truth[["activity_id", "mechanism", "denied_amount_initial", "final_denied_amount"]].copy()
    t["fix"] = t["mechanism"].map(fix).fillna(0.0)
    t["recovered"] = t["fix"] * t["final_denied_amount"]          # write-off avoided
    t["prevented"] = t["fix"] * t["denied_amount_initial"]        # initial denial avoided
    sel = pd.read_parquet(GOLD / "worklist_selections.parquet").merge(t, on="activity_id")
    days = pd.Index(sorted(pred["submission_date"].unique()))
    hours_per_day = cfg["coders"] * cfg["review_hours_per_day"]
    # perfect-hindsight ceiling for the same capacity
    cap = int(cfg["coders"] * cfg["review_hours_per_day"] * 60 // cfg["minutes_per_line"])
    p = pred[["activity_id", "submission_date"]].merge(t, on="activity_id")
    hind = (p.sort_values(["submission_date", "recovered", "activity_id"], ascending=[True, False, True], kind="mergesort")
              .groupby("submission_date").head(cap))
    sel = pd.concat([sel, hind.assign(policy="perfect_hindsight")[sel.columns]], ignore_index=True)
    per_day = sel.groupby(["policy", "submission_date"])["recovered"].sum().unstack(0).reindex(days).fillna(0)
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(days), size=(cfg["bootstrap_reps"], len(days)))
    res = {}
    for pol in POLICIES + ["perfect_hindsight"]:
        v = per_day[pol].to_numpy()
        boot = v[idx].sum(axis=1) / (len(days) * hours_per_day)
        s = sel[sel.policy == pol]
        res[pol] = {"aed_recovered": float(v.sum()), "aed_per_coder_hour": float(v.sum() / (len(days) * hours_per_day)),
                    "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                    "initial_denials_prevented_aed": float(s["prevented"].sum()),
                    "lines_reviewed": int(len(s)), "reviewed_lines_denied_share": float((s["denied_amount_initial"] > 0).mean())}
    # paired difference rules_then_lgbm - rules (same resampled days)
    diff = (per_day["rules_then_lgbm"] - per_day["rules"]).to_numpy()
    boot = diff[idx].sum(axis=1) / (len(days) * hours_per_day)
    res["uplift_rules_then_lgbm_vs_rules"] = {"aed_per_coder_hour": float(diff.sum() / (len(days) * hours_per_day)),
                                              "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]}
    diff = (per_day["lightgbm"] - per_day["rules"]).to_numpy()
    boot = diff[idx].sum(axis=1) / (len(days) * hours_per_day)
    res["uplift_lightgbm_vs_rules"] = {"aed_per_coder_hour": float(diff.sum() / (len(days) * hours_per_day)),
                                       "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]}
    res["coder_hours"] = float(len(days) * hours_per_day)
    res["test_period_recoverable_aed_total"] = float(p["recovered"].sum())
    # per hour actually spent reviewing (rules alone leave capacity unused)
    for pol in POLICIES:
        worked = res[pol]["lines_reviewed"] * cfg["minutes_per_line"] / 60
        res[pol]["review_hours_used"] = float(worked)
        res[pol]["aed_per_review_hour_used"] = float(res[pol]["aed_recovered"] / worked)
    # what LightGBM adds on top of the rules, by true root cause
    by = sel[sel.policy.isin(["rules", "rules_then_lgbm"])].groupby(["policy", "mechanism"])["recovered"].sum().unstack(0).fillna(0)
    by["added_by_model"] = by["rules_then_lgbm"] - by["rules"]
    res["added_by_model_by_root_cause"] = {k: round(float(v), 2) for k, v in by["added_by_model"].sort_values(ascending=False).items() if abs(v) > 1}
    # capacity sensitivity: same blind ranking, tighter capacity
    sens = {}
    for c in (10, 20, 30, 45):
        sc = select(pred, c).merge(t, on="activity_id")
        sens[c] = {pol: float(sc.loc[sc.policy == pol, "recovered"].sum() / (len(days) * hours_per_day * c / cap))
                   for pol in POLICIES}
    res["capacity_sensitivity_aed_per_paid_hour"] = sens
    return res, per_day


def change_detection(key: dict, con) -> tuple[dict, dict]:
    pc = key["effects"]["auth_policy_change"]
    change = pd.Timestamp(pc["change_date"])
    change_week = change - pd.Timedelta(days=change.weekday())
    alerts = pd.read_parquet(GOLD / "change_alerts.parquet")
    weeks = con.execute("SELECT DISTINCT week_start FROM series_denials_weekly ORDER BY 1").df().week_start
    monitor_start = pd.Timestamp(weeks.iloc[BASELINE_WEEKS]); monitor_end = pd.Timestamp(weeks.iloc[-1])
    months = (monitor_end - monitor_start).days / 30.44
    first_affected_ra = con.execute("""
        SELECT MIN(initial_ra_date) FROM fact_claim_line
        WHERE payer_id = ? AND service_line = ? AND service_date >= ? AND initial_denial_category = 'Authorisation'""",
        [pc["payer_id"], pc["service_line"], change.date()]).fetchone()[0]
    out = {"true_change": {"payer_id": pc["payer_id"], "service_line": pc["service_line"], "change_date": pc["change_date"],
                           "first_denied_remittance": str(first_affected_ra)}}
    for method in ("cusum", "naive"):
        a = alerts[alerts.method == method].copy(); a["alert_week"] = pd.to_datetime(a.alert_week)
        on_true = (a.payer_id == pc["payer_id"]) & (a.service_line == pc["service_line"])
        hits = a[on_true & (a.alert_week >= change_week)].sort_values("alert_week")
        false = a[~on_true | (a.alert_week < change_week)]
        detected = len(hits) > 0
        out[method] = {
            "detected": bool(detected),
            "first_alert_week": str(hits.alert_week.iloc[0].date()) if detected else None,
            "weeks_to_detect_from_change": float((hits.alert_week.iloc[0] - change_week).days / 7) if detected else None,
            "weeks_from_first_denied_ra": float((hits.alert_week.iloc[0] - pd.Timestamp(first_affected_ra)).days / 7) if detected else None,
            "false_alarms": int(len(false)), "false_alarms_per_month": float(len(false) / months),
            "false_alarm_series": int(false.groupby(["payer_id", "service_line"]).ngroups) if len(false) else 0,
        }
    # what the change cost, and how much of it was submitted after the first CUSUM alert
    truth = pd.read_parquet(SEALED / "line_truth.parquet", columns=["activity_id", "mechanism", "denied_amount_initial", "final_denied_amount"])
    lines = con.execute("SELECT activity_id, payer_id, service_line, code, service_date, submission_date FROM fact_claim_line").df()
    rules = pd.read_parquet(CLEAN / "payer_auth_rules.parquet")
    already = rules[(rules.payer_id == pc["payer_id"]) & (rules.service_line == pc["service_line"])].scope.tolist()
    high_cost = {c for c, v in catalog()["codes"].items() if v.get("high_cost")}
    hit = lines.merge(truth, on="activity_id")
    hit = hit[(hit.payer_id == pc["payer_id"]) & (hit.service_line == pc["service_line"]) & (hit.mechanism == "AUTH")
              & (pd.to_datetime(hit.service_date) >= change)]
    if "high_cost" in already:            # those codes needed auth before the change: not caused by it
        hit = hit[~hit.code.isin(high_cost)]
    alert = pd.Timestamp(out["cusum"]["first_alert_week"]) if out["cusum"]["detected"] else None
    after = hit[pd.to_datetime(hit.submission_date) >= alert] if alert is not None else hit.iloc[0:0]
    out["cost_of_change"] = {"denied_lines": int(len(hit)), "initial_denied_aed": float(hit.denied_amount_initial.sum()),
                             "final_denied_aed": float(hit.final_denied_amount.sum()),
                             "denied_lines_submitted_after_alert": int(len(after)),
                             "initial_denied_aed_submitted_after_alert": float(after.denied_amount_initial.sum())}
    sp = key["effects"]["slow_payer"]
    pay = pd.read_parquet(GOLD / "payment_alerts.parquet")
    if len(pay):
        pay["alert_week"] = pd.to_datetime(pay.alert_week)
    sp_from = pd.Timestamp(sp["from_date"])
    hit = pay[(pay.payer_id == sp["payer_id"]) & (pay.alert_week >= sp_from)] if len(pay) else pay
    out["slow_payer"] = {"payer_id": sp["payer_id"], "from_date": sp["from_date"], "detected": bool(len(hit)),
                         "weeks_to_detect": float((hit.alert_week.min() - sp_from).days / 7) if len(hit) else None,
                         "false_alarms": int(len(pay) - len(hit)) if len(pay) else 0}
    return out, {"change_week": change_week, "alerts": alerts, "monitor_start": monitor_start}


def recovery_table(key: dict, det: dict) -> list[dict]:
    e = key["effects"]
    payer = pd.read_parquet(GOLD / "drivers_payer_cells.parquet")
    fac = pd.read_parquet(GOLD / "drivers_facility_cells.parquet")
    clin = pd.read_parquet(GOLD / "drivers_clinician_cells.parquet")
    pairs = pd.read_parquet(GOLD / "drivers_code_pairs.parquet")
    rows = []

    def rank_of(t, mask):
        r = t[mask & t.finding]
        return int(r["rank"].min()) if len(r) else None

    ps = e["payer_service_mnec"]
    r = rank_of(payer, (payer.payer_id == ps["payer_id"]) & (payer.service_line == ps["service_line"]) & (payer.category == "Medical necessity"))
    rows.append({"effect": f"{ps['payer_id']} stricter on medical necessity for {ps['service_line']}", "method": "payer x service-line driver ranking",
                 "rank": r, "recovered": r is not None and r <= TOP_N})
    fr = e["facility_radiology_auth"]
    r = rank_of(fac, (fac.facility_id == fr["facility_id"]) & (fac.service_line == "radiology") & (fac.category == "Authorisation"))
    rows.append({"effect": f"{fr['facility_id']} misses prior auth on high-cost radiology", "method": "facility driver ranking",
                 "rank": r, "recovered": r is not None and r <= TOP_N})
    nc = e["ncci_pair"]
    m = pairs[(pairs.denied_code == nc["col2"]) & (pairs.cobilled_code == nc["col1"])]
    r = int(m.index[0]) + 1 if len(m) else None
    rows.append({"effect": f"NCCI pair {nc['col1']}+{nc['col2']} billed by {nc['department']}", "method": "code-pair ranking (PRCE-002 denials)",
                 "rank": r, "recovered": r is not None and r <= TOP_N})
    pc = e["auth_policy_change"]
    c = det["cusum"]
    rows.append({"effect": f"{pc['payer_id']} starts requiring prior auth for {pc['service_line']} ({pc['change_date']})",
                 "method": "binomial CUSUM on weekly authorisation denials", "rank": None, "recovered": c["detected"],
                 "detail": f"{c['weeks_to_detect_from_change']} weeks after the change" if c["detected"] else "not detected"})
    sp = det["slow_payer"]
    rows.append({"effect": f"{sp['payer_id']} slows payment from {sp['from_date']}", "method": "CUSUM on weekly median days to payment",
                 "rank": None, "recovered": sp["detected"],
                 "detail": f"{sp['weeks_to_detect']} weeks after the change" if sp["detected"] else "not detected"})
    wd = e["weak_doctor"]
    r = rank_of(clin, clin.clinician_id == wd["clinician_id"])
    rows.append({"effect": f"{wd['clinician_id']} documents poorly (more medical-necessity denials)", "method": "clinician vs specialty peers ranking",
                 "rank": r, "recovered": r is not None and r <= TOP_N})
    return rows


def dq_and_rules(key: dict, truth: pd.DataFrame) -> dict:
    dq = pd.read_csv(CLEAN / "data_quality.csv").set_index("check")
    k = key["data_quality"]
    planted = {"remittance duplicate rows": (k["remittance_dup_rows"], int(dq.at["exact duplicate remittance rows", "rows_failed"])),
               "non-positive net amounts": (len(k["nonpositive_net_activity_ids"]), int(dq.at["activity net amount <= 0", "rows_failed"])),
               "gross != patient share + net": (len(k["gross_mismatch_activity_ids"]), int(dq.filter(like="gross != patient_share", axis=0)["rows_failed"].iloc[0])),
               "settlement before submission (claims)": (len(k["ra_before_submission_claim_ids"]),
                                                         int(pd.read_parquet(CLEAN / "remittances.parquet")
                                                             .query("dq_bad_settlement_date")["claim_id"].nunique()))}
    flags = pd.read_parquet(CLEAN / "scrubber_flags.parquet").merge(truth, on="activity_id")
    prec = {}
    for rule, mech in RULE_MECH.items():
        s = flags[flags.rule == rule]
        if mech == "MNEC":
            prec[rule] = {"flagged": int(len(s)), "share_denied_for_this_reason": float((s.mechanism == "MNEC").mean())}
        else:
            prec[rule] = {"flagged": int(len(s)), "share_with_true_breach": float((s[f"p_{mech}"] >= 0.9).mean())}
    undetectable = {
        "ELIG_retro_termination_denials": int(((truth.mechanism == "ELIG") & ~truth.activity_id.isin(flags.loc[flags.rule == "ELIG_OUT_OF_COVERAGE", "activity_id"])).sum()),
        "AUTH_denials_not_flagged": int(((truth.mechanism == "AUTH") & ~truth.activity_id.isin(flags.loc[flags.rule.str.startswith("AUTH"), "activity_id"])).sum()),
        "noise_denials": int((truth.mechanism == "noise").sum()),
    }
    return {"planted_vs_found": {k2: {"planted": v[0], "found": v[1]} for k2, v in planted.items()},
            "scrubber_rule_precision": prec, "denials_rules_cannot_see": undetectable}


def plot_worklist(res: dict) -> None:
    pols = POLICIES + ["perfect_hindsight"]
    labels = {"rules": "Rules only", "baseline": "Payer x line\nhistory", "logreg": "Logistic\nregression",
              "lightgbm": "LightGBM", "rules_then_lgbm": "Rules, then\nLightGBM", "perfect_hindsight": "Perfect\nhindsight"}
    v = [res[p]["aed_per_coder_hour"] for p in pols]
    lo = [res[p]["aed_per_coder_hour"] - res[p]["ci95"][0] for p in pols]
    hi = [res[p]["ci95"][1] - res[p]["aed_per_coder_hour"] for p in pols]
    fig, ax = plt.subplots(figsize=(8, 4))
    colors = ["#7a7a7a", "#b0b0b0", "#2a6fbb", "#d1495b", "#8e2c48", "#e0e0e0"]
    ax.bar([labels[p] for p in pols], v, yerr=[lo, hi], color=colors, capsize=3, edgecolor="#555", lw=0.5)
    for i, x in enumerate(v):
        ax.text(i, x + max(v) * 0.03, f"{x:,.0f}", ha="center", fontsize=8)
    ax.set_ylabel("AED write-off avoided per coder hour")
    ax.set_title("Pre-submission review value, test months (95% bootstrap CI)", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIGURES / "worklist_aed_per_hour.png", dpi=150); plt.close(fig)


def plot_change(key: dict, con, ctx: dict) -> None:
    pc = key["effects"]["auth_policy_change"]
    s = con.execute("""SELECT week_start, adjudicated_lines, denied_lines FROM series_denials_weekly
                       WHERE payer_id = ? AND service_line = ? AND denial_category = 'Authorisation' ORDER BY 1""",
                    [pc["payer_id"], pc["service_line"]]).df()
    s["rate"] = s.denied_lines / s.adjudicated_lines.replace(0, np.nan)
    a = ctx["alerts"]; a = a[(a.payer_id == pc["payer_id"]) & (a.service_line == pc["service_line"])]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(s.week_start, 100 * s.rate, c="#2a6fbb", lw=1.2)
    ax.axvline(ctx["change_week"], c="#555", ls="--", lw=1); ax.text(ctx["change_week"], ax.get_ylim()[1] * 0.92, " rule change", fontsize=8)
    ax.axvspan(s.week_start.iloc[0], ctx["monitor_start"], color="#eee", zorder=0)
    ax.text(s.week_start.iloc[1], ax.get_ylim()[1] * 0.92, "baseline (26 wk)", fontsize=8, color="#666")
    for w in pd.to_datetime(a[a.method == "cusum"].alert_week):
        ax.axvline(w, c="#d1495b", lw=1.5)
    ax.set_ylabel("Authorisation denials (% of lines)")
    ax.set_title(f"{pc['payer_id']} {pc['service_line']}: weekly authorisation denials by RA week (red = CUSUM alert)", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIGURES / "change_detection.png", dpi=150); plt.close(fig)


def main() -> dict:
    key, truth = unseal()
    cfg = review_config()
    pred = pd.read_parquet(GOLD / "predictions.parquet")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    ceil = ceiling(pred, truth)
    wl, _ = worklist_value(pred, truth, cfg)
    det, ctx = change_detection(key, con)
    rec = recovery_table(key, det)
    dq = dq_and_rules(key, truth)
    plot_worklist(wl); plot_change(key, con, ctx)
    con.close()
    score = {"ceiling": ceil, "worklist": wl, "change_detection": det, "answer_key_recovery": rec,
             "recovered_effects": f"{sum(r['recovered'] for r in rec)} of {len(rec)}",
             "data_quality_and_rules": dq, "answer_key_effects": key["effects"]}
    update_metrics("score", score)
    print(json.dumps({"ceiling": ceil, "worklist": {k: v for k, v in wl.items()}, "change": det, "recovery": rec}, indent=1, default=str))
    return score


if __name__ == "__main__":
    main()
