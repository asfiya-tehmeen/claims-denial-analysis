"""Load clean tables into DuckDB and run the SQL layer (sql/01..05) in order."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src.common import CLEAN, DB_PATH, SQL, catalog, ensure_dirs, load_yaml, sim_config, update_metrics

SQL_FILES = ["01_staging.sql", "02_marts.sql", "03_kpis.sql", "04_scorecard.sql", "05_series.sql"]
CLEAN_TABLES = ["claims", "activities", "remittances", "resubmissions", "members", "payers", "facilities",
                "clinicians", "prior_auths", "scrubber_flags"]

# PD-05-2025 (verified text, see data/reference/SOURCES.md)
PD05 = {"submission_deadline_day": 15, "ra_days_initial": 45, "ra_days_resubmission": 30,
        "resubmission_window_days": 21, "delay_fee_rate_per_day": 0.0003, "max_resubmissions": 2}


def reference_frames() -> dict[str, pd.DataFrame]:
    cfg = sim_config()
    codes = load_yaml("denial_codes.yaml")["codes"]
    dc = pd.DataFrame([{"denial_code": k, "description": v["desc"], "category": v["category"],
                        "avoidable": bool(v["avoidable"]), "source": v["source"]} for k, v in codes.items()])
    sl = pd.DataFrame([{"service_line": k, "service_line_label": v["label"], "sort_order": i}
                       for i, (k, v) in enumerate(catalog()["service_lines"].items())])
    params = pd.DataFrame([{**PD05, "period_start": pd.Timestamp(cfg["period"]["start"]).date(),
                            "period_end": pd.Timestamp(cfg["period"]["end"]).date()}])
    return {"ref_denial_codes": dc, "ref_service_lines": sl, "ref_params": params}


def build(db_path: Path = DB_PATH, clean_dir: Path = CLEAN) -> duckdb.DuckDBPyConnection:
    ensure_dirs()
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    for t in CLEAN_TABLES:
        con.execute(f"CREATE TABLE raw_{t} AS SELECT * FROM read_parquet(?)", [str(clean_dir / f"{t}.parquet")])
    for name, df in reference_frames().items():
        con.register("_tmp", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _tmp")
        con.unregister("_tmp")
    for f in SQL_FILES:
        con.execute((SQL / f).read_text(encoding="utf-8"))
    return con


def main() -> None:
    con = build()
    overall = con.execute("SELECT * FROM kpi_overall").df().iloc[0].drop(
        ["grain", "payer_id", "service_line", "year_month", "facility_id", "initial_denial_category"]).to_dict()
    ar = con.execute("SELECT ar_days_last12_avg FROM kpi_ar_summary WHERE payer_id = 'ALL'").fetchone()[0]
    timely = con.execute("SELECT * FROM kpi_timeliness WHERE payer_id IS NULL").df().iloc[0].drop("payer_id").to_dict()
    overall.update({"ar_days_last12_avg": ar, **timely})
    sc = con.execute("SELECT * FROM payer_scorecard").df()
    leak = con.execute("""SELECT denial_category, ROUND(SUM(initial_denied_aed),2) initial_denied_aed,
                                 ROUND(SUM(final_denied_aed),2) final_denied_aed
                          FROM kpi_leakage GROUP BY 1 ORDER BY 3 DESC""").df()
    leak_sl = con.execute("""SELECT service_line, ROUND(SUM(final_denied_aed),2) final_denied_aed
                             FROM kpi_leakage GROUP BY 1 ORDER BY 2 DESC""").df()
    dq = pd.read_csv(CLEAN / "data_quality.csv")
    update_metrics("data", {
        "claims": int(con.execute("SELECT COUNT(DISTINCT claim_id) FROM fact_claim_line").fetchone()[0]),
        "lines": int(con.execute("SELECT COUNT(*) FROM fact_claim_line").fetchone()[0]),
        "remittance_rows": int(con.execute("SELECT COUNT(*) FROM fact_remittance").fetchone()[0]),
        "service_months": int(con.execute("SELECT COUNT(DISTINCT strftime(service_date, '%Y-%m')) FROM fact_claim_line").fetchone()[0]),
        "period": [str(x) for x in con.execute("SELECT MIN(service_date), MAX(service_date) FROM fact_claim_line").fetchone()],
        "dq_checks": int(len(dq)), "dq_checks_with_failures": int((dq.rows_failed > 0).sum()),
        "lines_quarantined": int(dq.loc[dq.check.str.startswith("TOTAL"), "rows_failed"].iloc[0]),
    })
    update_metrics("kpis", overall)
    update_metrics("scorecard", sc.to_dict(orient="records"))
    update_metrics("leakage_by_category", leak.to_dict(orient="records"))
    update_metrics("leakage_by_service_line", leak_sl.to_dict(orient="records"))
    print(pd.Series(overall).to_string())
    print(sc[["payer_id", "initial_denial_rate_value", "expected_denial_rate_value", "denial_rate_vs_expected",
              "median_days_to_payment", "pct_initial_within_45d", "ar_days_last12_avg"]].round(3).to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
