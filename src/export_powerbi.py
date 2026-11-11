"""Export the star schema to reports/powerbi/*.csv and the SQL-computed check values.

CSV conventions: UTF-8, comma-separated, ISO dates (YYYY-MM-DD), booleans as 1/0, integer keys.
expected_values.csv lists KPI values computed in SQL so the DAX in MEASURES.md can be checked.
"""
from __future__ import annotations

import duckdb
import pandas as pd

from src.common import DB_PATH, GOLD, HONESTY_NOTE, POWERBI, ensure_dirs, update_metrics

TABLES = {
    "fact_claim_line": """SELECT activity_id, claim_id, line_no, is_claim_anchor, payer_key, service_line_key, provider_key,
        service_date_key, submission_date_key, initial_ra_date_key, initial_denial_code_key, plan_tier, code, code_type,
        quantity, modifier, has_prior_auth, gross, patient_share, net, initial_paid, initial_denied_amount, is_initial_denied,
        is_avoidable_denial, was_resubmitted, recovered_on_resubmission, was_overturned, final_denied_amount, is_final_denied,
        days_to_initial_ra, days_service_to_submission, late_submission_days, scrubber_flag_count, claim_scrubber_clean,
        claim_first_pass_paid, ar_eligible, submission_date, last_settlement_date
        FROM fact_claim_line ORDER BY activity_id""",
    "fact_remittance": """SELECT activity_id, claim_id, round, round_label, claim_round_id, payer_key, service_line_key,
        provider_key, settlement_date_key, denial_code_key, settlement_date, payment_amount, is_denied, line_net,
        days_to_settlement, deadline_days, within_deadline, late_payment_days, late_payment_fee_aed, ar_eligible
        FROM fact_remittance ORDER BY activity_id, round""",
    "dim_payer": "SELECT * FROM dim_payer ORDER BY payer_key",
    "dim_service_line": "SELECT * FROM dim_service_line ORDER BY service_line_key",
    "dim_provider": "SELECT * FROM dim_provider ORDER BY provider_key",
    "dim_date": "SELECT * FROM dim_date ORDER BY date_key",
    "dim_denial_code": "SELECT * FROM dim_denial_code ORDER BY denial_code_key",
}

KPI_COLS = {
    "Claims": "claims", "Lines": "lines", "Net Billed AED": "net_billed_aed", "Initial Denied AED": "initial_denied_aed",
    "Final Denied AED": "final_denied_aed", "Recovered on Resubmission AED": "recovered_aed",
    "Clean Claim Rate": "clean_claim_rate", "First-Pass Yield": "first_pass_yield",
    "Initial Denial Rate (Count)": "initial_denial_rate_count", "Initial Denial Rate (Value)": "initial_denial_rate_value",
    "Avoidable Denial Share": "avoidable_denial_share", "Final Denial Rate (Value)": "final_denial_rate_value",
    "Resubmission Overturn Rate": "resubmission_overturn_rate", "Median Days to Payment": "median_days_to_payment",
    "Late Submission Fee AED": "late_submission_fee_aed",
}


def expected_values(con) -> pd.DataFrame:
    rows = []
    cube = con.execute("SELECT * FROM kpi_cube WHERE grain IN ('overall', 'payer', 'service_line')").df()
    names = con.execute("SELECT payer_id, payer_name FROM dim_payer").df().set_index("payer_id")["payer_name"]
    labels = con.execute("SELECT service_line, service_line_label FROM dim_service_line").df().set_index("service_line")["service_line_label"]
    for _, r in cube.iterrows():
        filt = ("(no filter)" if r.grain == "overall" else
                f"dim_payer[payer_name] = {names[r.payer_id]}" if r.grain == "payer" else
                f"dim_service_line[service_line_label] = {labels[r.service_line]}")
        for measure, col in KPI_COLS.items():
            rows.append({"measure": measure, "filter": filt, "expected_value": r[col]})
    sc = con.execute("SELECT * FROM payer_scorecard").df()
    for _, r in sc.iterrows():
        filt = f"dim_payer[payer_name] = {r.payer_name}"
        for measure, col in {"Expected Denial Rate (Value)": "expected_denial_rate_value",
                             "Denial Rate vs Expected": "denial_rate_vs_expected",
                             "% Initial RA Within 45 Days": "pct_initial_within_45d",
                             "% Resubmission RA Within 30 Days": "pct_resubmission_within_30d",
                             "Late Payment Fee Due AED": "late_payment_fee_due_aed",
                             "A/R Days (Avg Last 12 Month-Ends)": "ar_days_last12_avg"}.items():
            rows.append({"measure": measure, "filter": filt, "expected_value": r[col]})
    t = con.execute("SELECT * FROM kpi_timeliness WHERE payer_id IS NULL").df().iloc[0]
    ar = con.execute("SELECT ar_days_last12_avg FROM kpi_ar_summary WHERE payer_id = 'ALL'").fetchone()[0]
    for measure, v in {"% Initial RA Within 45 Days": t.pct_initial_within_45d,
                       "% Resubmission RA Within 30 Days": t.pct_resubmission_within_30d,
                       "Late Payment Fee Due AED": t.late_payment_fee_due_aed,
                       "A/R Days (Avg Last 12 Month-Ends)": ar}.items():
        rows.append({"measure": measure, "filter": "(no filter)", "expected_value": v})
    arm = con.execute("SELECT year_month, ar_days FROM kpi_ar_monthly WHERE payer_id = 'ALL' ORDER BY 1").df()
    for _, r in arm.iterrows():
        rows.append({"measure": "A/R Days", "filter": f"dim_date[year_month] = {r.year_month}", "expected_value": r.ar_days})
    out = pd.DataFrame(rows)
    out["expected_value"] = out["expected_value"].astype(float).round(6)
    return out


def main() -> None:
    ensure_dirs()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    sizes = {}
    for name, q in TABLES.items():
        df = con.execute(q).df()
        for c in df.columns:
            vals = set(df[c].dropna().unique()) if df[c].dtype in (object, "boolean") else None
            if df[c].dtype == bool:
                df[c] = df[c].astype(int)
            elif vals is not None and vals and vals <= {True, False}:
                df[c] = df[c].map({True: 1, False: 0}).astype("Int64")      # blank stays blank
            elif str(df[c].dtype).startswith("datetime"):
                df[c] = df[c].dt.strftime("%Y-%m-%d")
        df.to_csv(POWERBI / f"{name}.csv", index=False, encoding="utf-8")
        sizes[name] = len(df)
    # the change detector's own (blind) CUSUM alerts, for the page-2 alert table
    alerts = pd.read_parquet(GOLD / "change_alerts.parquet")
    alerts = alerts[alerts.method == "cusum"].merge(con.execute("SELECT payer_id, payer_key FROM dim_payer").df(), on="payer_id")
    alerts = alerts.merge(con.execute("SELECT service_line, service_line_key FROM dim_service_line").df(), on="service_line")
    alerts["alert_week"] = pd.to_datetime(alerts["alert_week"]).dt.strftime("%Y-%m-%d")
    alerts[["payer_key", "service_line_key", "category", "alert_week", "baseline_rate"]].to_csv(
        POWERBI / "fact_change_alert.csv", index=False)
    sizes["fact_change_alert"] = len(alerts)
    ev = expected_values(con)
    ev.to_csv(POWERBI / "expected_values.csv", index=False)
    (POWERBI / "DATA_HONESTY.txt").write_text(HONESTY_NOTE + "\n", encoding="utf-8")
    con.close()
    update_metrics("powerbi", {"tables": sizes, "expected_values_rows": int(len(ev)), "measures_documented": 25})
    print(sizes, len(ev), "expected values")


if __name__ == "__main__":
    main()
