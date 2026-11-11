"""Seeded claims simulator: eClaimLink-style claims, activity lines, prior auths, remittance
advice rounds and resubmissions, with planted effects and a sealed answer key.

    python -m src.generator              # full run (config/sim.yaml)
    python -m src.generator --small      # quick run for development

Outputs: data/raw/*.csv (what a hospital's billing system would export)
         data/raw/sealed/answer_key.json, line_truth.parquet (read ONLY by src/score.py)
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src import reference
from src.common import RAW, SEALED, catalog, ensure_dirs, load_yaml

MECHANISMS = ["ELIG", "AUTH", "CODE_DX", "CODE_MUE", "CODE_NCCI0", "CODE_MOD", "DUPL", "TIME",
              "PRCE", "NCOV", "BENX", "MNEC", "noise"]
HARD = [m for m in MECHANISMS if m not in ("MNEC", "noise")]
NOISE_CODES = (["MNEC-003", "CLAI-012", "AUTH-005", "CODE-016", "NCOV-003"], [0.35, 0.2, 0.15, 0.15, 0.15])
NO_COPAY_LINES = {"emergency", "day_surgery"}
DAY_SURGERY_SPECIALTY = {"K219": "gastroenterology", "K2970": "gastroenterology", "Z1211": "gastroenterology",
                         "K635": "gastroenterology", "S83241A": "orthopaedics", "M23205": "orthopaedics",
                         "H259": "ophthalmology", "K8020": "general_surgery", "K4090": "general_surgery"}


def _d(s) -> date:
    return s if isinstance(s, date) else date.fromisoformat(str(s))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


@dataclass
class World:
    cfg: dict
    cat: dict
    rng: np.random.Generator
    start: date
    end: date
    eff: dict
    ptp: dict = field(default_factory=dict)     # (col1, col2) -> modifier indicator
    mue: dict = field(default_factory=dict)

    def month_index(self, d: date) -> int:
        return (d.year - self.start.year) * 12 + d.month - self.start.month + 1


# ----------------------------------------------------------------------------------------------
# Planted effects (drawn with the effect seed; written only to the sealed folder)
# ----------------------------------------------------------------------------------------------
def draw_effects(cfg: dict, doctors: pd.DataFrame, start: date) -> dict:
    erng = np.random.default_rng(cfg["effect_seed"])
    e = cfg["effects"]
    payers = [p["id"] for p in cfg["payers"]]
    pay = {p["id"]: p for p in cfg["payers"]}

    strict_payer = str(erng.choice(payers))
    change_line = str(erng.choice(e["auth_policy_change"]["service_lines"]))
    eligible = [p for p in payers if p != strict_payer and change_line not in pay[p]["auth_lines"]]
    change_payer = str(erng.choice(eligible))
    change_month = int(erng.integers(e["auth_policy_change"]["month_range"][0], e["auth_policy_change"]["month_range"][1] + 1))
    m0 = _add_months(start, change_month - 1)
    change_date = m0 + timedelta(days=int(erng.integers(0, 21)))
    change_date += timedelta(days=(7 - change_date.weekday()) % 7)            # a Monday
    slow_payer = str(erng.choice([p for p in payers if p not in (change_payer, strict_payer)]))
    slow_month = int(erng.integers(e["slow_payer"]["month_range"][0], e["slow_payer"]["month_range"][1] + 1))
    gps = doctors[doctors["specialty"].isin(["family_medicine", "internal_medicine"])]["clinician_id"].tolist()
    return {
        "payer_service_mnec": {"payer_id": strict_payer, "service_line": e["payer_service_mnec"]["service_line"],
                               "logit": float(erng.uniform(*e["payer_service_mnec"]["logit_range"]))},
        "facility_radiology_auth": {"facility_id": str(erng.choice(["FAC-HH", "FAC-CM"])),
                                    "service_line": "radiology", "scope": "high_cost",
                                    "auth_success": float(erng.uniform(*e["facility_radiology_auth"]["auth_success_range"]))},
        "ncci_pair": {"col1": e["ncci_pair"]["col1"], "col2": e["ncci_pair"]["col2"], "department": "gastroenterology",
                      "rate": float(erng.uniform(*e["ncci_pair"]["rate_range"]))},
        "auth_policy_change": {"payer_id": change_payer, "service_line": change_line,
                               "change_date": change_date.isoformat(),
                               "learn_delay_weeks": int(erng.integers(e["auth_policy_change"]["learn_delay_weeks"][0], e["auth_policy_change"]["learn_delay_weeks"][1] + 1)),
                               "adoption_weeks": int(erng.integers(e["auth_policy_change"]["adoption_weeks"][0], e["auth_policy_change"]["adoption_weeks"][1] + 1))},
        "slow_payer": {"payer_id": slow_payer, "from_date": _add_months(start, slow_month - 1).isoformat(),
                       "median_days": float(erng.uniform(*e["slow_payer"]["median_days_range"]))},
        "weak_doctor": {"clinician_id": str(erng.choice(gps)), "logit": float(erng.uniform(*e["weak_doctor"]["logit_range"]))},
    }


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


# ----------------------------------------------------------------------------------------------
# Master data
# ----------------------------------------------------------------------------------------------
def make_doctors(cfg: dict, rng) -> pd.DataFrame:
    rows, i = [], 1
    for spec, n in cfg["doctors_per_specialty"].items():
        for k in range(n):
            fac = cfg["facilities"][k % len(cfg["facilities"])]["id"]
            off = cfg["doctor_offlabel_rate"]["mean"] * float(np.exp(rng.normal(0, cfg["doctor_offlabel_rate"]["sd"])))
            rows.append({"clinician_id": f"CLN-{i:03d}", "specialty": spec, "facility_id": fac,
                         "_offlabel": min(off, 0.4), "_mnec_effect": rng.normal(0, cfg["adjudication"]["mnec_logit"]["doctor_sd"])})
            i += 1
    return pd.DataFrame(rows)


def make_members(cfg: dict, rng, n: int, start: date, end: date) -> pd.DataFrame:
    pids = [p["id"] for p in cfg["payers"]]
    pw = np.array([p["share"] for p in cfg["payers"]]); pw /= pw.sum()
    tiers = list(cfg["plans"]); tw = np.array([cfg["plans"][t]["share"] for t in tiers]); tw /= tw.sum()
    cov_start = [start + timedelta(days=int(x)) for x in rng.integers(-365, 600, n)]
    cov_len = rng.integers(365, 1096, n)
    known_end = [s + timedelta(days=int(l)) for s, l in zip(cov_start, cov_len)]
    retro = rng.random(n) < cfg["provider"]["retro_termination_rate"]
    true_end = [ke - timedelta(days=int(rng.integers(15, 121))) if r else ke for ke, r in zip(known_end, retro)]
    true_end = [max(te, s + timedelta(days=30)) for te, s in zip(true_end, cov_start)]
    age = np.clip(rng.gamma(4.0, 9.0, n), 0, 85).astype(int)
    birth = [date(start.year - int(a), int(rng.integers(1, 13)), int(rng.integers(1, 29))) for a in age]
    return pd.DataFrame({
        "member_id": [f"MBR-{i:06d}" for i in range(1, n + 1)],
        "payer_id": rng.choice(pids, n, p=pw),
        "plan_tier": rng.choice(tiers, n, p=tw),
        "gender": rng.choice(["F", "M"], n),
        "birth_date": birth,
        "coverage_start": cov_start,
        "coverage_end": known_end,          # what the provider has on file
        "_true_coverage_end": true_end,     # payer-side truth (sealed)
    })


# ----------------------------------------------------------------------------------------------
# Clinical content
# ----------------------------------------------------------------------------------------------
class Clinical:
    def __init__(self, cat: dict):
        self.cat = cat
        self.code_line = {c: v["line"] for c, v in cat["codes"].items()}
        self.price = {c: v["price"] for c, v in cat["codes"].items()}
        self.price.update({c: v["price"] for c, v in cat["drugs"].items()})
        self.high_cost = {c for c, v in cat["codes"].items() if v.get("high_cost")}
        self.drug_cls = {c: v["cls"] for c, v in cat["drugs"].items()}
        self.group_of = {}
        for g, spec in cat["support"].items():
            for c in spec["codes"]:
                self.group_of[c] = spec

    def support(self, code: str, dx: str) -> str:
        spec = self.cat["drug_support"][self.drug_cls[code]] if code in self.drug_cls else self.group_of[code]
        if dx in spec.get("strong", []):
            return "strong"
        if dx in spec.get("weak", []):
            return "weak"
        if spec.get("any"):
            return "strong"
        if spec.get("any_weak"):
            return "weak"
        return "none"

    def pick(self, rng, candidates: list[str], dx: str, offlabel: float, weights=None) -> str:
        """Pick a code: usually one the diagnosis strongly supports, sometimes off-label."""
        strong = [c for c in candidates if self.support(c, dx) == "strong"]
        if strong and rng.random() > offlabel:
            return str(rng.choice(strong))
        p = None if weights is None else np.array(weights) / np.sum(weights)
        return str(rng.choice(candidates, p=p))


def dx_sample(rng, cat, line: str) -> str:
    pool = cat["dx_pools"][line]
    k = list(pool); w = np.array(list(pool.values()), float)
    return str(rng.choice(k, p=w / w.sum()))


def build_lines(rng, cl: Clinical, cfg: dict, eff: dict, line: str, dx: str, doc: pd.Series,
                first_session: bool) -> list[dict]:
    """Return activity lines [{code, units, modifier}] for one claim."""
    P = cfg["provider"]; off = doc["_offlabel"]; out = []

    def add(code, units=1):
        out.append({"code": code, "units": int(units), "modifier": ""})

    if line == "outpatient":
        if rng.random() < 0.2:
            add(str(rng.choice(["99202", "99203", "99204"], p=[0.3, 0.5, 0.2])))
        else:
            add(str(rng.choice(["99212", "99213", "99214", "99215"], p=[0.2, 0.5, 0.25, 0.05])))
        if rng.random() < P["em_injection_rate"]:
            add("96372")
        if rng.random() < 0.45:
            for c in rng.choice(["85025", "80053", "83036", "80061"], size=int(rng.integers(1, 4)), replace=False):
                add(str(c))
            add("36415")
    elif line == "emergency":
        add(str(rng.choice(["99283", "99284", "99285"], p=[0.4, 0.4, 0.2])))
        if rng.random() < 0.4:
            add("96372")
        if dx in ("R079", "R0789", "J189", "R509") or rng.random() < 0.1:
            add("71046")
        if rng.random() < 0.35:
            add("85025")
        if rng.random() < 0.2:
            add("80048")
    elif line == "laboratory":
        add(str(rng.choice(["80053", "80048"], p=[0.7, 0.3])))
        if rng.random() < 0.7:
            add("85025")
        specific = ["83036", "80061", "84443", "81001"]
        for _ in range(int(rng.integers(1, 4))):
            c = cl.pick(rng, specific, dx, off)
            if c not in [o["code"] for o in out]:
                add(c)
        if rng.random() < 0.7:
            add("36415")
    elif line == "radiology":
        codes = ["71046", "76700", "72148", "70551", "73721", "74177"]
        add(cl.pick(rng, codes, dx, off, [25, 15, 18, 12, 15, 15]))
    elif line == "physiotherapy":
        if first_session:
            add(str(rng.choice(["97161", "97162"], p=[0.7, 0.3])))
            if rng.random() < 0.06:
                add("99213")                                       # real NCCI: 97161/97162 vs E/M
        n = int(rng.integers(1, 3)) if first_session else int(rng.integers(2, 5))
        for c in rng.choice(["97110", "97140", "97112", "97530", "97035"], size=n, replace=False, p=[0.3, 0.25, 0.15, 0.2, 0.1]):
            add(str(c), 1 if c == "97035" else rng.integers(1, 4))
    elif line == "pharmacy":
        drugs = list(cl.drug_cls)
        for _ in range(int(rng.integers(1, 5))):
            c = cl.pick(rng, drugs, dx, off)
            if c not in [o["code"] for o in out]:
                add(c, rng.integers(1, 4))
    elif line == "day_surgery":
        procs = ["43239", "45380", "45378", "29881", "66984", "47562", "49505"]
        c = cl.pick(rng, procs, dx, off, [14, 14, 18, 12, 18, 12, 12])
        add(c)
        pair = eff["ncci_pair"]
        rate = pair["rate"] if doc["specialty"] == pair["department"] else P["ncci_pair_rate"]
        if c == pair["col1"] and rng.random() < rate:
            add(pair["col2"])                                      # indicator 0: never payable
        if c == "45380" and rng.random() < P["ncci_pair_rate"]:
            add("45378")
        if rng.random() < 0.15:
            add("96372")
    return out


# ----------------------------------------------------------------------------------------------
# Main simulation
# ----------------------------------------------------------------------------------------------
def generate(n_claims: int | None = None, n_members: int | None = None, out_dir: Path = RAW,
             sealed_dir: Path = SEALED, seed: int | None = None) -> dict:
    cfg = load_yaml("sim.yaml"); cat = catalog()
    if seed is not None:
        cfg["seed"] = seed
    n_claims = n_claims or cfg["n_claims"]; n_members = n_members or cfg["n_members"]
    rng = np.random.default_rng(cfg["seed"])
    start, end = _d(cfg["period"]["start"]), _d(cfg["period"]["end"])
    P, A = cfg["provider"], cfg["adjudication"]
    cl = Clinical(cat)
    ptp_df, mue_df = reference.load("ncci_ptp"), reference.load("mue")
    ptp = {(r.col1, r.col2): int(r.modifier_indicator) for r in ptp_df.itertuples()}
    mue = dict(zip(mue_df["code"], mue_df["mue_value"]))

    doctors = make_doctors(cfg, rng)
    eff = draw_effects(cfg, doctors, start)
    members = make_members(cfg, rng, n_members, start, end)
    payers = {p["id"]: p for p in cfg["payers"]}
    plans = cfg["plans"]
    mrec = members.to_dict("records")            # plain records: pandas row access is slow

    # coverage window inside the period (provider-known)
    ws = [max(r["coverage_start"], start) for r in mrec]
    we = [min(r["coverage_end"], end) for r in mrec]
    wlen = np.array([(b - a).days for a, b in zip(ws, we)], float).clip(min=0)
    mprob = wlen / wlen.sum()
    month_factor = {7: 0.8, 8: 0.8, 12: 0.9}

    def sample_date(i):
        a, b = ws[i], we[i]
        while True:
            d = a + timedelta(days=int(rng.integers(0, (b - a).days + 1)))
            if rng.random() < month_factor.get(d.month, 1.0):
                return d

    drec = doctors.to_dict("records")
    lines_cfg = cat["service_lines"]
    line_names = list(lines_cfg)

    def pick_doctor(line, facility, dx=None):
        specs = lines_cfg[line]["specialty"]
        if line == "day_surgery":                 # the surgeon's specialty follows the procedure
            specs = [DAY_SURGERY_SPECIALTY[dx]]
        cand = [r for r in drec if r["specialty"] in specs]
        same = [r for r in cand if r["facility_id"] == facility] or cand
        return same[int(rng.integers(len(same)))]

    fac_ids = [f["id"] for f in cfg["facilities"]]
    fac_w = np.array([f["share"] for f in cfg["facilities"]]); fac_w /= fac_w.sum()

    # ---- encounters ---------------------------------------------------------------------
    encounters = []   # dicts: member_idx, date, line, facility, doctor, dx, first_session
    n_physio = int(n_claims * lines_cfg["physiotherapy"]["weight"])
    n_other = n_claims - n_physio
    other_lines = [k for k in line_names if k != "physiotherapy"]
    ow = np.array([lines_cfg[k]["weight"] for k in other_lines]); ow /= ow.sum()
    m_idx = rng.choice(len(members), n_other, p=mprob)
    o_lines = rng.choice(other_lines, n_other, p=ow)
    for mi, line in zip(m_idx, o_lines):
        d = sample_date(mi)
        if rng.random() < P["registration_error_rate"]:      # date outside coverage on file
            ce = mrec[mi]["coverage_end"]
            if ce < end - timedelta(days=5):
                d = ce + timedelta(days=int(rng.integers(1, min(60, (end - ce).days))))
        fac = str(rng.choice(fac_ids, p=fac_w))
        dx = dx_sample(rng, cat, str(line))
        doc = pick_doctor(str(line), fac, dx)
        encounters.append({"mi": mi, "date": d, "line": str(line), "fac": fac, "doc": doc,
                           "dx": dx, "first": False})
    # physiotherapy as episodes of weekly-ish sessions
    made = 0
    while made < n_physio:
        mi = int(rng.choice(len(members), p=mprob))
        d = sample_date(mi)
        fac = str(rng.choice(fac_ids, p=fac_w)); doc = pick_doctor("physiotherapy", fac)
        dx = dx_sample(rng, cat, "physiotherapy")
        sessions = 1 + int(rng.negative_binomial(2, 2 / (2 + 9)))
        for s in range(sessions):
            if d > end or made >= n_physio:
                break
            encounters.append({"mi": mi, "date": d, "line": "physiotherapy", "fac": fac, "doc": doc,
                               "dx": dx, "first": s == 0})
            made += 1
            d = d + timedelta(days=int(rng.integers(3, 9)))
    encounters.sort(key=lambda e: e["date"])

    # ---- claims and lines ----------------------------------------------------------------
    pc = eff["auth_policy_change"]; pc_date = _d(pc["change_date"])
    learn_from = pc_date + timedelta(weeks=pc["learn_delay_weeks"])
    sp = eff["slow_payer"]; sp_date = _d(sp["from_date"])
    fra = eff["facility_radiology_auth"]
    ps_eff = eff["payer_service_mnec"]; wd = eff["weak_doctor"]
    ml = A["mnec_logit"]
    physio_count: dict[tuple, int] = {}

    def payer_requires_auth(payer, line, code, d):
        p = payers[payer]
        if line in p["auth_lines"]:
            return True
        if line == "radiology" and code in cl.high_cost and p["auth_high_cost_radiology"]:
            return True
        if payer == pc["payer_id"] and line == pc["service_line"] and d >= pc_date:
            return True
        return False

    def provider_requests_auth(payer, line, code, d):
        p = payers[payer]
        if line in p["auth_lines"] or (line == "radiology" and code in cl.high_cost and p["auth_high_cost_radiology"]):
            return True
        if payer == pc["payer_id"] and line == pc["service_line"] and d >= learn_from:
            frac = min(1.0, (d - learn_from).days / (7 * pc["adoption_weeks"]))
            return rng.random() < 0.92 * frac
        return False

    claims, acts, auths, truth = [], [], [], []
    aid = 0
    for ci, e in enumerate(encounters, start=1):
        m = mrec[e["mi"]]; payer = m["payer_id"]; tier = m["plan_tier"]; plan = plans[tier]
        d, line, doc, dx = e["date"], e["line"], e["doc"], e["dx"]
        claim_id = f"CLM-{ci:07d}"
        invalid_dx = rng.random() < P["invalid_dx_rate"]
        dx_billed = str(rng.choice(cat["invalid_dx_headers"])) if invalid_dx else dx
        lines = build_lines(rng, cl, cfg, eff, line, dx, doc, e["first"])
        codes_on_claim = [l["code"] for l in lines]
        # NCCI modifiers for indicator-1 pairs (provider appends modifier most of the time)
        for l in lines:
            for c1 in codes_on_claim:
                if ptp.get((c1, l["code"])) == 1 and rng.random() < P["ncci_modifier_rate"]:
                    l["modifier"] = "25" if l["code"].startswith("99") else "59"
        # MUE unit typos
        for l in lines:
            if l["code"] in mue and rng.random() < P["mue_unit_error_rate"]:
                l["units"] = mue[l["code"]] + int(rng.integers(1, 3))
        # submission timing
        lag = int(np.round(np.exp(rng.normal(np.log(P["submission_lag_median_days"]), 0.6))))
        if rng.random() < P["late_hold_rate"]:
            lag = int(rng.integers(60, 201))
        submit = d + timedelta(days=max(lag, 0))
        # prior authorisation (claim level)
        needs_prov = any(provider_requests_auth(payer, line, l["code"], d) for l in lines)
        auth_id, auth_valid_to = None, None
        if needs_prov:
            succ = P["auth_success_rate"]
            if line == "radiology" and e["fac"] == fra["facility_id"] and any(l["code"] in cl.high_cost for l in lines):
                succ = fra["auth_success"]
            if rng.random() < succ:
                auth_id = f"PA-{ci:07d}"
                req = d - timedelta(days=int(rng.integers(0, 8)))
                if rng.random() < P["auth_expired_rate"]:
                    req = d - timedelta(days=int(rng.integers(P["auth_validity_days"] + 1, P["auth_validity_days"] + 20)))
                auth_valid_to = req + timedelta(days=P["auth_validity_days"])
                auths.append({"prior_auth_id": auth_id, "claim_id": claim_id, "member_id": m["member_id"],
                              "payer_id": payer, "request_date": req, "status": "approved",
                              "valid_from": req, "valid_to": auth_valid_to})
        # benefit counting (physio sessions per calendar year)
        over_limit = False
        if line == "physiotherapy":
            key = (m["member_id"], d.year)
            physio_count[key] = physio_count.get(key, 0) + 1
            lim = plan["physio_sessions_per_year"]
            over_limit = lim is not None and physio_count[key] > lim
        covered_truth = m["coverage_start"] <= d <= m["_true_coverage_end"]
        before_start = d < m["coverage_start"]
        pfac = cfg["payer_price_factor"][payer]
        copay = 0.0 if line in NO_COPAY_LINES else plan["copay"]
        c_gross = c_ps = c_net = 0.0
        for li, l in enumerate(lines, start=1):
            aid += 1
            code, units = l["code"], l["units"]
            contract = round(cl.price[code] * pfac, 2)
            billed = contract
            overbilled = rng.random() < P["overbilling_rate"]
            if overbilled:
                billed = round(contract * (1 + rng.uniform(*P["overbilling_range"])), 2)
            gross = round(billed * units, 2); ps = round(gross * copay, 2); net = round(gross - ps, 2)
            contract_net = round(contract * units * (1 - copay), 2)
            c_gross += gross; c_ps += ps; c_net += net
            sup = cl.support(code, dx)
            is_drug = code in cl.drug_cls
            # --- denial components (true probabilities) ---
            hard = A["hard_rule_catch"]
            comp = dict.fromkeys(MECHANISMS, 0.0)
            req_truth = payer_requires_auth(payer, line, code, d)
            if not covered_truth:
                comp["ELIG"] = hard
            if req_truth and (auth_id is None or d > auth_valid_to):
                comp["AUTH"] = hard
            if invalid_dx:
                comp["CODE_DX"] = hard
            if code in mue and units > mue[code]:
                comp["CODE_MUE"] = hard
            for c1 in codes_on_claim:
                ind = ptp.get((c1, code))
                if ind == 0:
                    comp["CODE_NCCI0"] = hard
                elif ind == 1 and not l["modifier"]:
                    comp["CODE_MOD"] = hard
            if lag > A["timely_filing_days"]:
                comp["TIME"] = hard
            if overbilled:
                comp["PRCE"] = hard
            excluded = (code in plan["excluded_codes"] or dx in plan["excluded_dx"]
                        or (is_drug and cl.drug_cls[code] in plan["excluded_drug_classes"]))
            if excluded:
                comp["NCOV"] = hard
            if over_limit:
                comp["BENX"] = hard
            logit = ml["base"] + ml["line_offset"][line] + {"strong": 0.0, "weak": ml["weak"], "none": ml["none"]}[sup]
            logit += payers[payer]["mnec_strictness"] + doc["_mnec_effect"]
            if payer == ps_eff["payer_id"] and line == ps_eff["service_line"]:
                logit += ps_eff["logit"]
            if doc["clinician_id"] == wd["clinician_id"]:
                logit += wd["logit"]
            comp["MNEC"] = float(sigmoid(logit))
            comp["noise"] = payers[payer]["noise"]
            acts.append({"activity_id": f"ACT-{aid:08d}", "claim_id": claim_id, "line_no": li,
                         "start": d, "type": "DRUG" if is_drug else "CPT", "code": code, "quantity": units,
                         "modifier": l["modifier"], "gross": gross, "patient_share": ps, "net": net,
                         "clinician_id": doc["clinician_id"],
                         "prior_auth_id": auth_id})
            truth.append({"activity_id": f"ACT-{aid:08d}", "claim_id": claim_id, "support": sup,
                          "contract_net": contract_net, "net": net, "payer_id": payer, "line": line,
                          "excluded_kind": ("dx" if dx in plan["excluded_dx"] else "drug" if is_drug else "code") if excluded else None,
                          "elig_kind": ("before" if before_start else "after") if not covered_truth else None,
                          "auth_kind": ("missing" if auth_id is None else "expired") if comp["AUTH"] else None,
                          **{f"p_{k}": v for k, v in comp.items()}})
        claims.append({"claim_id": claim_id, "member_id": m["member_id"], "payer_id": payer,
                       "provider_id": e["fac"], "encounter_type": line, "encounter_start": d,
                       "principal_dx": dx_billed, "gross": round(c_gross, 2), "patient_share": round(c_ps, 2),
                       "net": round(c_net, 2), "submission_date": submit, "_lag": lag, "_dup_of": None})

    claims = pd.DataFrame(claims); acts = pd.DataFrame(acts); truth = pd.DataFrame(truth)

    # ---- duplicate claims ----------------------------------------------------------------
    dup_src = claims.sample(frac=P["duplicate_claim_rate"], random_state=int(rng.integers(1 << 31)))
    new_claims, new_acts, new_truth = [], [], []
    nxt = len(claims)
    act_idx = acts.groupby("claim_id").indices
    for _, c in dup_src.iterrows():
        nxt += 1
        cid = f"CLM-{nxt:07d}"
        c2 = c.copy(); c2["claim_id"] = cid; c2["_dup_of"] = c["claim_id"]
        c2["submission_date"] = c["submission_date"] + timedelta(days=int(rng.integers(10, 41)))
        c2["_lag"] = (c2["submission_date"] - c2["encounter_start"]).days
        new_claims.append(c2)
        a = acts.iloc[act_idx[c["claim_id"]]].copy()
        t = truth.iloc[act_idx[c["claim_id"]]].copy()
        ids = [f"ACT-{aid + k + 1:08d}" for k in range(len(a))]; aid += len(a)
        a["activity_id"] = ids; a["claim_id"] = cid; t["activity_id"] = ids; t["claim_id"] = cid
        t["p_DUPL"] = A["hard_rule_catch"]
        t["p_TIME"] = A["hard_rule_catch"] if c2["_lag"] > A["timely_filing_days"] else 0.0
        new_acts.append(a); new_truth.append(t)
    claims = pd.concat([claims, pd.DataFrame(new_claims)], ignore_index=True)
    acts = pd.concat([acts] + new_acts, ignore_index=True)
    truth = pd.concat([truth] + new_truth, ignore_index=True)

    # ---- adjudication: initial round -----------------------------------------------------
    pm = truth[[f"p_{k}" for k in MECHANISMS]].to_numpy()
    p_total = 1 - np.prod(1 - pm, axis=1)
    denied = rng.random(len(truth)) < p_total
    mech_idx = np.array([rng.choice(len(MECHANISMS), p=row / row.sum()) if d_ and row.sum() > 0 else -1
                         for row, d_ in zip(pm, denied)])
    truth["p_total"] = p_total
    truth["denied_initial"] = denied
    truth["mechanism"] = [MECHANISMS[i] if i >= 0 else None for i in mech_idx]
    truth["denial_code"] = [_denial_code(rng, r) for r in truth.itertuples()]
    truth["denied_amount_initial"] = np.where(
        truth["mechanism"] == "PRCE", (truth["net"] - truth["contract_net"]).clip(lower=0),
        np.where(truth["denied_initial"], truth["net"], 0.0)).round(2)

    claims = claims.set_index("claim_id")
    pay_med = {pid: p["pay_median_days"] for pid, p in payers.items()}

    def pay_lag(payer, submitted, median_scale=1.0):
        med = pay_med[payer]
        if payer == sp["payer_id"] and submitted >= sp_date:
            med = sp["median_days"]
        return max(3, int(round(np.exp(rng.normal(np.log(med * median_scale), 0.3)))))

    ra0 = {cid: c["submission_date"] + timedelta(days=pay_lag(c["payer_id"], c["submission_date"]))
           for cid, c in zip(claims.index, claims[["payer_id", "submission_date"]].to_dict("records"))}

    # ---- resubmission rounds -------------------------------------------------------------
    rem, resubs = [], []
    remaining = truth["denied_amount_initial"].to_numpy().copy()
    recovered = np.zeros(len(truth))
    t_claim = truth["claim_id"].to_numpy(); t_mech = truth["mechanism"].to_numpy()
    t_aid = truth["activity_id"].to_numpy(); t_code = truth["denial_code"].to_numpy()
    claim_payer = claims["payer_id"].to_dict()
    for i, r in enumerate(truth.itertuples()):
        rem.append({"claim_id": r.claim_id, "activity_id": r.activity_id, "round": 0,
                    "date_settlement": ra0[r.claim_id], "payment_amount": round(r.net - r.denied_amount_initial, 2),
                    "denial_code": r.denial_code if r.denied_amount_initial > 0 else None})
    by_claim = truth.groupby("claim_id").indices
    r1_dates, r2_dates = {}, {}
    for cid, idx in by_claim.items():
        den = [i for i in idx if remaining[i] > 0]
        if not den:
            continue
        chosen = [i for i in den if rng.random() < A["resubmit_prob"][t_mech[i]]]
        if not chosen:
            continue
        rs = ra0[cid] + timedelta(days=int(rng.integers(*A["resubmission_delay_days"])))
        ra1 = rs + timedelta(days=pay_lag(claim_payer[cid], rs, 0.6))
        resubs.append({"claim_id": cid, "round": 1, "resubmission_type": "correction" if rng.random() < 0.85 else "internal complaint",
                       "resubmission_date": rs})
        still = []
        for i in chosen:
            ok = rng.random() < A["overturn_prob"][t_mech[i]]
            amt = remaining[i] if ok else 0.0
            recovered[i] += amt; remaining[i] -= amt
            rem.append({"claim_id": cid, "activity_id": t_aid[i], "round": 1, "date_settlement": ra1,
                        "payment_amount": round(amt, 2), "denial_code": None if ok else t_code[i]})
            if not ok:
                still.append(i)
        recon = [i for i in still if rng.random() < A["reconciliation_prob"]]
        if recon:
            rs2 = ra1 + timedelta(days=int(rng.integers(30, 121)))
            ra2 = rs2 + timedelta(days=pay_lag(claim_payer[cid], rs2, 0.7))
            resubs.append({"claim_id": cid, "round": 2, "resubmission_type": "reconciliation", "resubmission_date": rs2})
            for i in recon:
                ok = rng.random() < A["reconciliation_overturn"]
                amt = remaining[i] if ok else 0.0
                recovered[i] += amt; remaining[i] -= amt
                rem.append({"claim_id": cid, "activity_id": t_aid[i], "round": 2, "date_settlement": ra2,
                            "payment_amount": round(amt, 2), "denial_code": None if ok else t_code[i]})
    truth["recovered_amount"] = recovered.round(2)
    truth["final_denied_amount"] = remaining.round(2)
    rem = pd.DataFrame(rem); resubs = pd.DataFrame(resubs)
    rem["payment_reference"] = "PAY-" + rem["claim_id"].str[4:] + "-" + rem["round"].astype(str)
    claims = claims.reset_index()

    # ---- planted data-quality problems in the exports --------------------------------------
    dq = cfg["data_quality"]; dq_key = {}
    dup_rows = rem.sample(frac=dq["remittance_dup_rows"], random_state=int(rng.integers(1 << 31)))
    rem_export = pd.concat([rem, dup_rows], ignore_index=True)
    dq_key["remittance_dup_rows"] = int(len(dup_rows))
    acts_export = acts.copy()
    bad_net = acts_export.sample(frac=dq["nonpositive_net"], random_state=int(rng.integers(1 << 31))).index
    acts_export.loc[bad_net, "net"] = rng.choice([0.0, -1.0], len(bad_net)) * acts_export.loc[bad_net, "net"]
    dq_key["nonpositive_net_activity_ids"] = acts_export.loc[bad_net, "activity_id"].tolist()
    gm = acts_export.drop(bad_net).sample(frac=dq["gross_mismatch"], random_state=int(rng.integers(1 << 31))).index
    acts_export.loc[gm, "patient_share"] = acts_export.loc[gm, "patient_share"] + rng.integers(5, 50, len(gm))
    dq_key["gross_mismatch_activity_ids"] = acts_export.loc[gm, "activity_id"].tolist()
    r0 = rem_export[rem_export["round"] == 0]
    bad_ra = r0.drop_duplicates("claim_id").sample(frac=dq["ra_before_submission"], random_state=int(rng.integers(1 << 31)))
    sub_map = claims.set_index("claim_id")["submission_date"]
    for cid in bad_ra["claim_id"]:
        mask = (rem_export["claim_id"] == cid) & (rem_export["round"] == 0)
        rem_export.loc[mask, "date_settlement"] = sub_map[cid] - timedelta(days=int(rng.integers(1, 10)))
    dq_key["ra_before_submission_claim_ids"] = bad_ra["claim_id"].tolist()

    # ---- write ---------------------------------------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=True); sealed_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"payer_id": p["id"], "payer_name": p["name"], "payer_kind": p["kind"]} for p in cfg["payers"]]).to_csv(out_dir / "payers.csv", index=False)
    pd.DataFrame(cfg["facilities"]).rename(columns={"id": "facility_id", "name": "facility_name"})[["facility_id", "facility_name"]].to_csv(out_dir / "facilities.csv", index=False)
    doctors[["clinician_id", "specialty", "facility_id"]].to_csv(out_dir / "clinicians.csv", index=False)
    members.drop(columns=["_true_coverage_end"]).to_csv(out_dir / "members.csv", index=False)
    rows = []
    for pid in payers:
        for code, price in cl.price.items():
            rows.append({"payer_id": pid, "code": code, "contract_price": round(price * cfg["payer_price_factor"][pid], 2)})
    pd.DataFrame(rows).to_csv(out_dir / "contract_prices.csv", index=False)
    # the payers' published prior-auth lists as the provider had them at the start of the period
    rows = []
    for pid, p in payers.items():
        for ln in p["auth_lines"]:
            rows.append({"payer_id": pid, "service_line": ln, "scope": "all"})
        if p["auth_high_cost_radiology"]:
            rows.append({"payer_id": pid, "service_line": "radiology", "scope": "high_cost"})
    pd.DataFrame(rows).to_csv(out_dir / "payer_auth_rules.csv", index=False)
    pd.DataFrame([{"plan_tier": t, "copay": v["copay"], "physio_sessions_per_year": v["physio_sessions_per_year"],
                   "excluded_codes": "|".join(v["excluded_codes"]), "excluded_dx": "|".join(v["excluded_dx"]),
                   "excluded_drug_classes": "|".join(v["excluded_drug_classes"])} for t, v in plans.items()]).to_csv(out_dir / "plan_benefits.csv", index=False)
    claims.drop(columns=["_lag", "_dup_of"]).to_csv(out_dir / "claims.csv", index=False)
    acts_export.to_csv(out_dir / "activities.csv", index=False)
    pd.DataFrame(auths).to_csv(out_dir / "prior_auths.csv", index=False)
    rem_export.to_csv(out_dir / "remittances.csv", index=False)
    resubs.to_csv(out_dir / "resubmissions.csv", index=False)

    truth["dup_of"] = truth["claim_id"].map(claims.set_index("claim_id")["_dup_of"])
    truth.to_parquet(sealed_dir / "line_truth.parquet", index=False)
    key = {"effects": eff, "data_quality": dq_key, "seed": cfg["seed"], "effect_seed": cfg["effect_seed"],
           "counts": {"claims": int(len(claims)), "activities": int(len(acts)), "duplicate_claims": int(len(dup_src))}}
    (sealed_dir / "answer_key.json").write_text(json.dumps(key, indent=2, default=str))
    return key["counts"]


def _denial_code(rng, r) -> str | None:
    m = r.mechanism
    if not isinstance(m, str):
        return None
    if m == "ELIG":
        return "ELIG-006" if r.elig_kind == "before" else "ELIG-005"
    if m == "AUTH":
        return "AUTH-004" if r.auth_kind == "expired" else "AUTH-001"
    if m == "NCOV":
        return {"dx": "NCOV-019", "drug": "NCOV-027"}.get(r.excluded_kind, "NCOV-003")
    if m == "MNEC":
        if r.support == "none":
            return str(rng.choice(["CODE-006", "MNEC-004"]))
        if r.support == "weak":
            return str(rng.choice(["MNEC-004", "MNEC-003"], p=[0.6, 0.4]))
        return str(rng.choice(["MNEC-007", "MNEC-003"]))
    if m == "noise":
        return str(rng.choice(NOISE_CODES[0], p=NOISE_CODES[1]))
    return {"CODE_DX": "CODE-001", "CODE_MUE": "MNEC-005", "CODE_NCCI0": "PRCE-002", "CODE_MOD": "PRCE-002",
            "DUPL": "DUPL-001", "TIME": "TIME-001", "PRCE": "PRCE-001", "BENX": "BENX-002"}[m]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--small", action="store_true")
    a = ap.parse_args()
    ensure_dirs()
    counts = generate(n_claims=4000, n_members=2500) if a.small else generate()
    print(counts)


if __name__ == "__main__":
    main()
