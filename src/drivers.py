"""Denial drivers (blind). Ranks every cell, tests it against its peers, applies Benjamini-Hochberg.

  payer_cells      payer x service line x denial category  vs the other payers, same service line
  facility_cells   facility x service line x denial category vs the other facility, same service line
  clinician_cells  clinician x denial category              vs same-specialty peers
  code_pairs       (denied code, co-billed code) pairs among Coding denials

A cell is a finding if BH q < 0.05 and it denies more than its peers. Findings are ranked by
excess denied AED = cell denied AED - cell net x peer denial rate (by value).
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import norm

from src.common import DB_PATH, GOLD, update_metrics

Q = 0.05
MIN_LINES = 30


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values (q-values)."""
    p = np.asarray(p, float); n = len(p)
    order = np.argsort(p)
    q = p[order] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n); out[order] = np.clip(q, 0, 1)
    return out


def _base(con) -> pd.DataFrame:
    return con.execute("""
        SELECT f.activity_id, f.claim_id, f.payer_id, f.service_line, f.facility_id, f.clinician_id, p.specialty,
               f.code, f.net, f.is_initial_denied, f.initial_denied_amount, f.initial_denial_category, f.initial_denial_code
        FROM fact_claim_line f JOIN dim_provider p USING (provider_key)""").df()


def peer_test(df: pd.DataFrame, unit: str, peer_group: list[str]) -> pd.DataFrame:
    """For each (unit, peer_group..., category): two-proportion z-test of the denial rate vs peers."""
    rows = []
    cats = [c for c in df.initial_denial_category.unique() if c != "Not denied"]
    keys = [unit] + peer_group
    tot = df.groupby(keys, observed=True).agg(lines=("net", "size"), net=("net", "sum")).reset_index()
    grp_tot = df.groupby(peer_group, observed=True).agg(g_lines=("net", "size"), g_net=("net", "sum")).reset_index()
    for cat in cats:
        d = df[df.initial_denial_category == cat]
        cell = d.groupby(keys, observed=True).agg(den=("net", "size"), den_aed=("initial_denied_amount", "sum")).reset_index()
        grp = d.groupby(peer_group, observed=True).agg(g_den=("net", "size"), g_den_aed=("initial_denied_amount", "sum")).reset_index()
        t = tot.merge(cell, on=keys, how="left").merge(grp_tot, on=peer_group).merge(grp, on=peer_group, how="left").fillna(0)
        t["peer_lines"] = t.g_lines - t.lines; t["peer_den"] = t.g_den - t.den
        t["peer_net"] = t.g_net - t.net; t["peer_den_aed"] = t.g_den_aed - t.den_aed
        t = t[(t.lines >= MIN_LINES) & (t.peer_lines >= MIN_LINES)]
        p1, p2 = t.den / t.lines, t.peer_den / t.peer_lines
        pp = (t.den + t.peer_den) / (t.lines + t.peer_lines)
        se = np.sqrt(pp * (1 - pp) * (1 / t.lines + 1 / t.peer_lines)).replace(0, np.nan)
        z = (p1 - p2) / se
        t = t.assign(category=cat, rate=p1, peer_rate=p2, z=z, p_value=norm.sf(z.fillna(0)),
                     excess_aed=t.den_aed - t.net * (t.peer_den_aed / t.peer_net.replace(0, np.nan)))
        rows.append(t)
    out = pd.concat(rows, ignore_index=True)
    out["q_value"] = bh_qvalues(out.p_value.to_numpy())
    out["finding"] = (out.q_value < Q) & (out.rate > out.peer_rate)
    out = out.sort_values(["finding", "excess_aed"], ascending=[False, False]).reset_index(drop=True)
    out["rank"] = np.where(out.finding, out.groupby("finding").cumcount() + 1, np.nan)
    return out


def code_pairs(con) -> pd.DataFrame:
    return con.execute("""
        SELECT d.code AS denied_code, o.code AS cobilled_code, d.initial_denial_code AS denial_code,
               COUNT(*) AS denied_lines, ROUND(SUM(d.initial_denied_amount), 2) AS denied_aed
        FROM fact_claim_line d JOIN fact_claim_line o ON o.claim_id = d.claim_id AND o.activity_id <> d.activity_id
        WHERE d.is_initial_denied AND d.initial_denial_category = 'Coding' AND d.initial_denial_code = 'PRCE-002'
        GROUP BY ALL ORDER BY denied_aed DESC""").df()


def main() -> dict:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = _base(con)
    payer = peer_test(df, "payer_id", ["service_line"])
    fac = peer_test(df, "facility_id", ["service_line"])
    clin = peer_test(df, "clinician_id", ["specialty"])
    pairs = code_pairs(con)
    con.close()
    for name, t in (("payer_cells", payer), ("facility_cells", fac), ("clinician_cells", clin), ("code_pairs", pairs)):
        t.to_parquet(GOLD / f"drivers_{name}.parquet", index=False)
    cols = lambda t, k: t[t.finding].head(8)[k + ["category", "lines", "rate", "peer_rate", "excess_aed", "q_value"]]
    summary = {
        "payer_cells": {"tested": int(len(payer)), "findings": int(payer.finding.sum()),
                        "top": cols(payer, ["payer_id", "service_line"]).round(4).to_dict(orient="records")},
        "facility_cells": {"tested": int(len(fac)), "findings": int(fac.finding.sum()),
                           "top": cols(fac, ["facility_id", "service_line"]).round(4).to_dict(orient="records")},
        "clinician_cells": {"tested": int(len(clin)), "findings": int(clin.finding.sum()),
                            "top": cols(clin, ["clinician_id", "specialty"]).round(4).to_dict(orient="records")},
        "code_pairs_top": pairs.head(5).to_dict(orient="records"),
    }
    update_metrics("drivers", summary)
    for k in ("payer_cells", "facility_cells", "clinician_cells"):
        print(k, summary[k]["tested"], "tested,", summary[k]["findings"], "findings")
        print(pd.DataFrame(summary[k]["top"]).to_string(index=False))
    print(pairs.head(5).to_string(index=False))
    return summary


if __name__ == "__main__":
    main()
