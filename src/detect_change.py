"""Payer-behaviour change detection on weekly series (blind: never reads the answer key).

1. Denial-rate shift per payer x service line x denial category (authorisation is the main use):
   binomial CUSUM (log-likelihood ratio for a doubling of the baseline rate), baseline = first 26
   weeks of each series. Compared with a naive rule: weekly rate > 2x trailing 8-week rate and >= 3 denials.
2. Payment-speed shift per payer: one-sided Gaussian CUSUM on the weekly median days to payment.

Thresholds are fixed here, before any scoring: h = 5 for the binomial CUSUM, k = 0.5 / h = 5 for the
Gaussian CUSUM (textbook defaults).
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from src.common import DB_PATH, GOLD, update_metrics

BASELINE_WEEKS = 26
H_BINOM = 5.0
K_GAUSS, H_GAUSS = 0.5, 5.0
MIN_BASE_RATE = 0.002


def binomial_cusum(n: np.ndarray, x: np.ndarray, p0: float, h: float = H_BINOM) -> list[int]:
    """Indices where the CUSUM crosses h (then resets). Detects p0 -> p1 = max(2 p0, p0 + 0.02)."""
    p0 = max(p0, MIN_BASE_RATE)
    p1 = min(max(2 * p0, p0 + 0.02), 0.95)
    a, b = np.log(p1 / p0), np.log((1 - p1) / (1 - p0))
    s, alarms = 0.0, []
    for i, (ni, xi) in enumerate(zip(n, x)):
        s = max(0.0, s + xi * a + (ni - xi) * b)
        if s > h:
            alarms.append(i); s = 0.0
    return alarms


def naive_rule(n: np.ndarray, x: np.ndarray, start: int) -> list[int]:
    alarms = []
    for i in range(start, len(n)):
        nn, xx = n[i - 8:i].sum(), x[i - 8:i].sum()
        trailing = xx / nn if nn else 0.0
        if n[i] and x[i] >= 3 and x[i] / n[i] > 2 * max(trailing, MIN_BASE_RATE):
            alarms.append(i)
    return alarms


def gaussian_cusum(v: np.ndarray, mu: float, sd: float, k=K_GAUSS, h=H_GAUSS) -> list[int]:
    s, alarms = 0.0, []
    for i, vi in enumerate(v):
        if np.isnan(vi):
            continue
        s = max(0.0, s + (vi - mu) / max(sd, 1e-6) - k)
        if s > h:
            alarms.append(i); s = 0.0
    return alarms


def detect_denial_shifts(series: pd.DataFrame, category: str = "Authorisation") -> pd.DataFrame:
    out = []
    s = series[series.denial_category == category]
    for (payer, line), g in s.groupby(["payer_id", "service_line"]):
        g = g.sort_values("week_start")
        n, x = g.adjudicated_lines.to_numpy(), g.denied_lines.to_numpy()
        weeks = g.week_start.to_numpy()
        if n[:BASELINE_WEEKS].sum() == 0:
            continue
        p0 = x[:BASELINE_WEEKS].sum() / n[:BASELINE_WEEKS].sum()
        mon_n, mon_x = n[BASELINE_WEEKS:], x[BASELINE_WEEKS:]
        for i in binomial_cusum(mon_n, mon_x, p0):
            out.append({"method": "cusum", "payer_id": payer, "service_line": line, "category": category,
                        "alert_week": weeks[BASELINE_WEEKS + i], "baseline_rate": p0})
        for i in naive_rule(n, x, BASELINE_WEEKS):
            out.append({"method": "naive", "payer_id": payer, "service_line": line, "category": category,
                        "alert_week": weeks[i], "baseline_rate": p0})
    return pd.DataFrame(out)


def detect_payment_shifts(days: pd.DataFrame) -> pd.DataFrame:
    out = []
    for payer, g in days.groupby("payer_id"):
        g = g.sort_values("week_start")
        v = g.median_days_to_payment.to_numpy(float)
        mu, sd = np.nanmean(v[:BASELINE_WEEKS]), np.nanstd(v[:BASELINE_WEEKS])
        for i in gaussian_cusum(v[BASELINE_WEEKS:], mu, sd):
            out.append({"method": "cusum", "payer_id": payer, "alert_week": g.week_start.iloc[BASELINE_WEEKS + i],
                        "baseline_median_days": mu})
    return pd.DataFrame(out)


def main() -> dict:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    series = con.execute("SELECT * FROM series_denials_weekly").df()
    days = con.execute("SELECT * FROM series_days_to_pay_weekly").df()
    con.close()
    den = detect_denial_shifts(series)
    pay = detect_payment_shifts(days)
    den.to_parquet(GOLD / "change_alerts.parquet", index=False)
    pay.to_parquet(GOLD / "payment_alerts.parquet", index=False)
    monitored_weeks = series.week_start.nunique() - BASELINE_WEEKS
    n_series = series[series.denial_category == "Authorisation"].groupby(["payer_id", "service_line"]).ngroups
    first = (den[den.method == "cusum"].sort_values("alert_week").groupby(["payer_id", "service_line"]).head(1)
             .sort_values("alert_week"))
    summary = {
        "series_monitored": int(n_series), "monitored_weeks": int(monitored_weeks),
        "alerts": den.groupby("method").size().to_dict() if len(den) else {},
        "first_cusum_alert_per_series": [{"payer_id": r.payer_id, "service_line": r.service_line,
                                          "alert_week": str(pd.Timestamp(r.alert_week).date())} for r in first.itertuples()],
        "payment_alerts": [{"payer_id": r.payer_id, "alert_week": str(pd.Timestamp(r.alert_week).date()),
                            "baseline_median_days": round(r.baseline_median_days, 1)}
                           for r in pay.sort_values("alert_week").groupby("payer_id").head(1).itertuples()] if len(pay) else [],
    }
    update_metrics("change_detection_blind", summary)
    print(summary)
    return summary


if __name__ == "__main__":
    main()
