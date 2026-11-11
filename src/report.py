"""Write reports/REPORT.md, a memo to an RCM director. Every number is read from reports/metrics.json."""
from __future__ import annotations

from src.common import HONESTY_NOTE, REPORTS, read_metrics

LINE_LABEL = {"day_surgery": "Day surgery", "radiology": "Radiology", "physiotherapy": "Physiotherapy",
              "outpatient": "Outpatient", "laboratory": "Laboratory", "emergency": "Emergency", "pharmacy": "Pharmacy"}


ROOT_LABEL = {"MNEC": "medical necessity", "ELIG": "eligibility", "NCOV": "non-covered", "AUTH": "authorisation",
              "CODE_DX": "invalid diagnosis code", "CODE_MOD": "missing NCCI modifier", "CODE_MUE": "unit errors",
              "BENX": "benefit limits", "PRCE": "price", "DUPL": "duplicates", "TIME": "timely filing", "noise": "random"}


def aed(x: float) -> str:
    return f"AED {x:,.0f}"


def _when(diff_weeks: float) -> str:
    return f"{abs(diff_weeks):.0f} weeks {'earlier' if diff_weeks < 0 else 'later'}" if diff_weeks else "in the same week"


def pct(x: float, d: int = 1) -> str:
    return f"{100 * x:.{d}f}%"


def build(m: dict) -> str:
    d, k, sc, s = m["data"], m["kpis"], m["scorecard"], m["score"]
    wl, ce, cd = s["worklist"], s["ceiling"], s["change_detection"]
    mdl = m["model"]
    payer_name = {r["payer_id"]: r["payer_name"] for r in sc}
    leak = m["leakage_by_category"]; leak_sl = m["leakage_by_service_line"]
    total_final = sum(r["final_denied_aed"] for r in leak)
    top3 = leak[:3]; top3_share = sum(r["final_denied_aed"] for r in top3) / total_final
    rules, lgbm, combo = wl["rules"], wl["lightgbm"], wl["rules_then_lgbm"]
    up = wl["uplift_lightgbm_vs_rules"]
    rel_up = up["aed_per_coder_hour"] / rules["aed_per_coder_hour"]
    sens = wl["capacity_sensitivity_aed_per_paid_hour"]
    hind = wl["perfect_hindsight"]
    tc = cd["true_change"]; cu, nv, sp = cd["cusum"], cd["naive"], cd["slow_payer"]
    cost = cd["cost_of_change"]
    slow = next(r for r in sc if r["payer_id"] == sp["payer_id"])
    worst_ratio = max(sc, key=lambda r: r["denial_rate_vs_expected"])
    best_ratio = min(sc, key=lambda r: r["denial_rate_vs_expected"])
    highest_raw = max(sc, key=lambda r: r["initial_denial_rate_value"])
    drv = m["drivers"]
    fac_top = drv["facility_cells"]["top"][0]
    pay_top = drv["payer_cells"]["top"][0]
    pair = drv["code_pairs_top"][0]
    rec = s["answer_key_recovery"]
    dqr = s["data_quality_and_rules"]
    mnec_rule = dqr["scrubber_rule_precision"]["MNEC_DX_UNSUPPORTED"]
    added = wl["added_by_model_by_root_cause"]
    cap = m["worklist_design"]["capacity_lines_per_day"]
    a = m["worklist_design"]["assumptions"]
    idle = 1 - rules["review_hours_used"] / wl["coder_hours"]

    L = []
    w = L.append
    w("# Memo: claims denial review, simulated hospital group\n")
    w(f"> **{HONESTY_NOTE}**\n")
    w(f"**To:** RCM Director · **Re:** where revenue leaks, what to review first, which payer changed · "
      f"**Data:** {d['claims']:,} claims / {d['lines']:,} claim lines, 6 payers, 7 service lines, "
      f"service dates {d['period'][0]} to {d['period'][1]} ({d['service_months']} months)\n")

    w("## Three things to know\n")
    w(f"1. **We lose {pct(k['final_denial_rate_value'])} of net billed revenue to denials after resubmission** "
      f"({aed(k['final_denied_aed'])} of {aed(k['net_billed_aed'])}). The initial denial rate is {pct(k['initial_denial_rate_value'])} by value. "
      f"{pct(k['avoidable_denial_share'], 0)} of initially denied AED sits in categories a pre-submission check can normally prevent. "
      f"Three categories, {top3[0]['denial_category'].lower()}, {top3[1]['denial_category'].lower()} and {top3[2]['denial_category'].lower()}, "
      f"make up {pct(top3_share, 0)} of the loss.")
    w(f"2. **The rule scrubber already does most of the work. The model adds a little, and the gain is real.** With one coder reviewing "
      f"{cap} lines a day, reviewing what the scrubber flags avoids {aed(rules['aed_per_coder_hour'])} of write-off per paid coder hour. "
      f"Adding a LightGBM risk score raises that to {aed(lgbm['aed_per_coder_hour'])} "
      f"(+{aed(up['aed_per_coder_hour'])}, 95% CI {up['ci95'][0]:,.0f} to {up['ci95'][1]:,.0f}, +{pct(rel_up, 0)}). "
      f"The gain holds at every capacity tested, but it is small. Fix the rule gaps first. The model's main job is to rank the {mnec_rule['flagged']:,} "
      f"medical-necessity flags, of which only {pct(mnec_rule['share_denied_for_this_reason'], 0)} are actually denied for that reason.")
    w(f"3. **{payer_name[tc['payer_id']]} changed its prior-authorisation rules for {tc['service_line']}, and "
      f"{payer_name[sp['payer_id']]} has been paying late.** The change detector raised its alert {cu['weeks_from_first_denied_ra']:.0f} weeks "
      f"after the first denial of the new kind reached us ({cu['weeks_to_detect_from_change']:.0f} weeks after the change itself), "
      f"at {cu['false_alarms_per_month']:.2f} false alarms a month. "
      f"{payer_name[sp['payer_id']]} settles only {pct(slow['pct_initial_within_45d'], 0)} of claims within the 45 days PD-05-2025 requires "
      f"(median {slow['median_days_to_payment']:.0f} days) and owes us {aed(slow['late_payment_fee_due_aed'])} in late-payment fees.\n")

    w("## 1. Where revenue leaks\n")
    w("| Denial category | Initially denied | Still lost after resubmission |\n|---|---|---|")
    for r in leak:
        w(f"| {r['denial_category']} | {aed(r['initial_denied_aed'])} | {aed(r['final_denied_aed'])} |")
    w("")
    w("By service line, the largest losses after resubmission are "
      + ", ".join(f"{LINE_LABEL[r['service_line']].lower()} ({aed(r['final_denied_aed'])})" for r in leak_sl[:3])
      + ". Day surgery and radiology lose the most because each denied line is expensive.\n")
    w("Specific leaks found by the driver analysis (each cell tested against its peers, Benjamini-Hochberg q < 0.05, ranked by excess denied AED):\n")
    w(f"- **{fac_top['facility_id']} radiology, authorisation:** {pct(fac_top['rate'])} of lines denied for authorisation vs "
      f"{pct(fac_top['peer_rate'])} at the other facility, an excess of {aed(fac_top['excess_aed'])}. The prior-approval step for high-cost imaging "
      f"at this site is failing. Fix the process, not the claims.")
    w(f"- **Code pair {pair['cobilled_code']} + {pair['denied_code']}:** {pair['denied_lines']} lines denied as bundled "
      f"({pair['denial_code']}), {aed(pair['denied_aed'])}. This is a real CMS NCCI edit with modifier indicator 0, so the second code is never "
      f"separately payable. It needs a coding rule and a word with the department, not resubmission.")
    w(f"- **{payer_name[pay_top['payer_id']]}, {pay_top['service_line']}, {pay_top['category'].lower()}:** {pct(pay_top['rate'])} vs "
      f"{pct(pay_top['peer_rate'])} at other payers for the same service line, an excess of {aed(pay_top['excess_aed'])}. "
      f"Take this to the payer with documentation examples.\n")

    w("## 2. What to review first, and what it is worth\n")
    w(f"Test months {mdl['split']['test_months'][0]}–{mdl['split']['test_months'][1]} of the simulation "
      f"({mdl['split']['test_lines']:,} lines). Models were trained on months {mdl['split']['train_months'][0]}–{mdl['split']['train_months'][1]} "
      f"and tuned on {mdl['split']['valid_months'][0]}–{mdl['split']['valid_months'][1]} (time-based split). The coder reviews "
      f"{cap} lines per submission day ({a['coders']} coder, {a['review_hours_per_day']} h/day, {a['minutes_per_line']} min/line). "
      "'Recovered' means write-off avoided: denied AED that would still have been lost after resubmission, multiplied by an assumed fix rate per root cause "
      "(`config/review.yaml`).\n")
    w("| Review policy | AED recovered per paid coder hour (95% CI) | Total recovered | Lines reviewed | Share of reviewed lines that were denied |\n|---|---|---|---|---|")
    names = {"rules": "Scrubber flags, largest first", "baseline": "Payer × service-line history", "logreg": "Logistic regression",
             "lightgbm": "LightGBM", "rules_then_lgbm": "Scrubber flags first, then LightGBM", "perfect_hindsight": "Perfect hindsight (ceiling)"}
    for p in ["rules", "baseline", "logreg", "lightgbm", "rules_then_lgbm", "perfect_hindsight"]:
        r = wl[p]
        w(f"| {names[p]} | {r['aed_per_coder_hour']:,.0f} ({r['ci95'][0]:,.0f}–{r['ci95'][1]:,.0f}) | {aed(r['aed_recovered'])} | "
          f"{r['lines_reviewed']:,} | {pct(r['reviewed_lines_denied_share'], 0)} |")
    w("")
    w(f"![AED per coder hour](figures/worklist_aed_per_hour.png)\n")
    w(f"- **Rules alone leave the coder idle {pct(idle, 0)} of the review time.** They flag fewer lines than capacity allows. Per hour actually "
      f"spent reviewing, rules recover {aed(rules['aed_per_review_hour_used'])}. That is the best yield per hour, but it leaves hours unused.")
    w(f"- **What the model adds over the rules, by true root cause:** "
      + ", ".join(f"{ROOT_LABEL.get(k_, k_)} {aed(v)}" for k_, v in added.items() if v > 0)
      + ". Most of it is better ranking of medical-necessity flags, plus members whose coverage the payer ended without telling us (retro-termination), "
      "which no rule can see.")
    w("- **Capacity sensitivity** (AED per paid coder hour):\n")
    w("| Lines/day | Rules | LightGBM | Uplift |\n|---|---|---|---|")
    for c, v in sens.items():
        w(f"| {c} | {v['rules']:,.0f} | {v['lightgbm']:,.0f} | {pct(v['lightgbm'] / v['rules'] - 1, 1)} |")
    w("")
    w(f"- **Ceiling:** at this capacity, perfect hindsight recovers {aed(hind['aed_per_coder_hour'])} per hour. LightGBM reaches "
      f"{pct(lgbm['aed_per_coder_hour'] / hind['aed_per_coder_hour'], 0)} of that, and rules alone {pct(rules['aed_per_coder_hour'] / hind['aed_per_coder_hour'], 0)}.\n")
    w("**Model quality on the test months vs the best any model could do** (the generator knows each line's true denial probability):\n")
    w("| Scorer | AUC | AUC-PR | Brier |\n|---|---|---|---|")
    for p, lab in (("baseline", "Payer × service-line history"), ("rules", "Scrubber (any flag)"), ("logreg", "Logistic regression"),
                   ("lightgbm", "LightGBM"), ("oracle", "**Best achievable (true probabilities)**")):
        r = ce[p]
        w(f"| {lab} | {r['auc']:.3f} | {r['auc_pr']:.3f} | {r['brier']:.4f} |")
    w("")
    w(f"LightGBM reaches {pct(ce['lightgbm']['share_of_oracle_auc_pr'], 0)} of the best achievable AUC-PR. Little ranking signal is left to find. "
      f"The remaining denials are mostly random adjudication noise, which no model can predict. Calibration: `figures/calibration.png`. "
      f"Drivers: `figures/shap_summary.png` (top SHAP features: {', '.join(list(mdl['shap_top_features'])[:5])}).\n")

    w("## 3. Which payer changed, and when we would have known\n")
    w(f"Every week, for each payer × service line, the detector compares authorisation denials (by the week the remittance arrived) "
      f"with that series' first {26} weeks, using a binomial CUSUM with a threshold fixed before scoring. "
      f"It monitored {m['change_detection_blind']['series_monitored']} series for {m['change_detection_blind']['monitored_weeks']} weeks.\n")
    w(f"- **{payer_name[tc['payer_id']]} began requiring prior authorisation for {tc['service_line']} codes that did not need it before** "
      f"(effective {tc['change_date']}). The first denial of the new kind reached us on {tc['first_denied_remittance']}. "
      f"The CUSUM alerted in the week of {cu['first_alert_week']}: **{cu['weeks_to_detect_from_change']:.0f} weeks after the change and "
      f"{cu['weeks_from_first_denied_ra']:.0f} weeks after the first denied remittance.** Most of the delay is the payer's own turnaround.")
    w(f"- False alarms: {cu['false_alarms']} over the monitoring period ({cu['false_alarms_per_month']:.2f} a month, on "
      f"{cu['false_alarm_series']} series). A naive rule (\"rate doubled vs the last 8 weeks\") alerted "
      f"{_when(nv['weeks_to_detect_from_change'] - cu['weeks_to_detect_from_change'])} than the CUSUM, but raised "
      f"{nv['false_alarms']} false alarms ({nv['false_alarms_per_month']:.1f} a month). Nobody would keep reading those.")
    w(f"- What the change cost: {cost['denied_lines']} lines, {aed(cost['initial_denied_aed'])} initially denied. "
      f"{cost['denied_lines_submitted_after_alert']} of those lines ({aed(cost['initial_denied_aed_submitted_after_alert'])}) were submitted "
      f"*after* the alert. Updating the scrubber's authorisation list when the alert fired would have caught them. The amount is small here because "
      f"the newly covered codes are cheap, low-cost imaging. The same response time applied to a high-cost service line is what matters.")
    w(f"- **{payer_name[sp['payer_id']]} slowed its payments from {sp['from_date']}.** A CUSUM on the weekly median days to payment flagged it "
      f"{sp['weeks_to_detect']:.0f} weeks later, with {sp['false_alarms']} false alarms on the other payers.\n")
    w("![Change detection](figures/change_detection.png)\n")

    w("## 4. Payer scorecard\n")
    w("Expected rate = what the payer's denial rate (by value) would be if it denied each service line at the all-payer rate, given its own service mix.\n")
    w("| Payer | Type | Net billed | Initial denial rate (value) | Expected for its mix | Actual ÷ expected | Overturn rate | Median days to pay | Paid ≤ 45 days | Late-payment fee due | A/R days |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(sc, key=lambda r: -r["denial_rate_vs_expected"]):
        w(f"| {r['payer_name']} | {r['payer_kind']} | {aed(r['net_billed_aed'])} | {pct(r['initial_denial_rate_value'])} | "
          f"{pct(r['expected_denial_rate_value'])} | {r['denial_rate_vs_expected']:.2f} | {pct(r['resubmission_overturn_rate'], 0)} | "
          f"{r['median_days_to_payment']:.0f} | {pct(r['pct_initial_within_45d'], 0)} | {aed(r['late_payment_fee_due_aed'])} | {r['ar_days_last12_avg']:.0f} |")
    w("")
    w(f"**Why the mix-adjusted rate matters:** a payer whose members mostly use high-denial services will show a high raw denial rate even if it treats "
      f"each service exactly like the other payers. Here, {worst_ratio['payer_name']} denies {worst_ratio['denial_rate_vs_expected']:.2f}× what its mix "
      f"explains, and {best_ratio['payer_name']} only {best_ratio['denial_rate_vs_expected']:.2f}×. Raise the gap in contract talks, not the raw rate. "
      f"The raw rate invites the reply \"look at your own case mix\".\n")
    w(f"Hospital-wide: clean claim rate {pct(k['clean_claim_rate'])}, first-pass yield {pct(k['first_pass_yield'])}, resubmission overturn rate "
      f"{pct(k['resubmission_overturn_rate'])}, median days to payment {k['median_days_to_payment']:.0f}, A/R days {k['ar_days_last12_avg']:.1f} "
      f"(mean of the last 12 month-ends), {pct(k['pct_initial_within_45d'])} of claims settled within 45 days. "
      f"Late-submission fees we would owe under PD-05-2025: {aed(k['late_submission_fee_aed'])}.\n")

    w("## 5. Did the analysis find what was planted? (answer key, unsealed last)\n")
    w("The generator planted six effects with sizes and dates drawn from hidden ranges. Only `src/score.py` reads the answer key, and a test enforces that. "
      f"Detection rules and thresholds were fixed before scoring. **Recovered: {s['recovered_effects']}.**\n")
    w("| Planted effect | How the pipeline looks for it | Result |\n|---|---|---|")
    for r in rec:
        res = ("found" if r["recovered"] else "**missed**") + (f", rank {r['rank']}" if r.get("rank") else "") + (f", {r['detail']}" if r.get("detail") else "")
        w(f"| {r['effect']} | {r['method']} | {res} |")
    w("")
    miss = [r for r in rec if not r["recovered"]]
    if miss:
        above = drv["clinician_cells"]["top"][: max(int(miss[0]["rank"] or 1) - 1, 0)]
        rad = sum(1 for r in above if r["specialty"] == "radiology" and r["category"] == "Authorisation")
        w(f"**Why the miss:** the clinician ranking compares each doctor with same-specialty peers across *both* facilities. "
          f"{rad} of the {len(above)} cells ranked above the planted doctor are radiologists at the facility with the authorisation problem, "
          f"which is the facility effect showing up again at clinician level. The planted doctor ranked {miss[0]['rank']}, just outside the top 3. "
          "Comparing clinicians within the same facility is the obvious fix. It was not applied after unsealing, because that would be tuning to the answer key.\n")
    pv = dqr["planted_vs_found"]
    w("**Data quality:** the validator ran " + f"{d['dq_checks']} checks; planted export problems found: "
      + "; ".join(f"{k_} {v['found']}/{v['planted']}" for k_, v in pv.items()) + f". {d['lines_quarantined']} lines quarantined.\n")
    w("**Denials no rule can see** (test of the scrubber's blind spots): "
      f"{dqr['denials_rules_cannot_see']['ELIG_retro_termination_denials']} eligibility denials from coverage the payer ended without telling us, "
      f"{dqr['denials_rules_cannot_see']['AUTH_denials_not_flagged']} authorisation denials from the unannounced rule change, and "
      f"{dqr['denials_rules_cannot_see']['noise_denials']:,} random adjudication denials.\n")

    w("## 6. Limitations (read before quoting any number)\n")
    w("- **The claims are simulated.** The results show how well the *method* works on data with known structure. They are not real UAE denial rates "
      "or real payer behaviour. All payer names are fictional.")
    w("- **The answer key is blind to the code, not to me.** I wrote the generator, so I knew the effect *types*, though not their sizes, targets or dates. "
      "The detectors are generic (every payer × line × category is tested), and thresholds were fixed before scoring.")
    w("- **The AED figures scale with assumptions:** review capacity, minutes per line and fix rates by root cause (`config/review.yaml`).")
    w("- **NCCI/MUE are US CMS edits** (the Medicaid PTP practitioner file and the Medicare MUE table, Q4 2026). UAE payers' own edit sets are not public.")
    w("- **PD-05-2025** was read from the archived official PDF (Wayback Machine, 8 Nov 2025). The live ISAHD link returned 404 on 11 Nov 2026, so "
      "confirm its current status with DHIC. Its timelines are applied to the whole simulated period, including the months before 16 Nov 2025.")
    w("- **Denial-code descriptions** are verified for GC 06/2018 codes. The others come from secondary sources (see `data/reference/SOURCES.md`).")
    w(_dax_check_line())
    return "\n".join(L) + "\n"


def _dax_check_line() -> str:
    """Summarise reports/powerbi/measure_check.csv (DAX results queried in Power BI Desktop vs the SQL values)."""
    import csv
    path = REPORTS / "powerbi" / "measure_check.csv"
    if not path.exists():
        return ("- **The DAX** in `reports/powerbi/MEASURES.md` has not been checked yet. "
                "Check it against `reports/powerbi/expected_values.csv`.")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    ok = sum(r["pass"].strip().lower() == "true" for r in rows)
    n_meas = len({r["measure"] for r in rows})
    return (f"- **The Power BI report** (`reports/powerbi/DenialGuard.pbix`) was checked by querying its DAX measures in Power BI Desktop: "
            f"{ok} of {len(rows)} check values from SQL matched ({n_meas} measures, unfiltered and by payer, service line and month; "
            "see `reports/powerbi/measure_check.csv`). The SQL layer remains the source of truth.")


def main() -> None:
    m = read_metrics()
    (REPORTS / "REPORT.md").write_text(build(m), encoding="utf-8")
    print("wrote reports/REPORT.md")


if __name__ == "__main__":
    main()
