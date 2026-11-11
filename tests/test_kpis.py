"""SQL KPI layer vs hand-calculated values on the 20-line mini dataset (tests/conftest.py).

Hand arithmetic
- net: C1 300, C2 200, C3 1000, C4 400, C5 1000, C6 300, C7 500, C8 300 = 4000
- initial denied: C2 100 + C3 1000 + C4 20 + C6 100 = 1220 -> 30.5% by value, 4/20 lines = 20% by count
- clean claims (no scrubber flag): C1 C3 C5 C6 C8 = 5/8; first-pass (no line denied): C1 C5 C7 C8 = 4/8
- avoidable (AUTH-001, PRCE-001, ELIG-005): 220 / 1220
- final denied: C3 1000 + C4 20 + C6 100 = 1120 -> 28%
- overturn: 2 lines resubmitted (C2-L2 paid, C3-L1 not) -> 50%
- days to payment per claim: 20 50 15 18 28 55 25 20 -> median 22.5
- late submission: C3 serviced Feb, deadline 15 Mar, submitted 20 Mar: 5 d x 1000 x 0.03% = 1.5
- RA within 45 d: C2 (50) and C6 (55) late -> 6/8; resubmissions within 30 d: C2 21 d ok, C3 40 d late -> 1/2
- late-payment fee: C2 5 d x 200 + C6 10 d x 300 + C3 (resub) 10 d x 1000, x 0.03% = 0.3 + 0.9 + 3.0 = 4.2
- mix: outpatient rate 220/1500, radiology 1000/2500.
  P01 expected = (500 x 0.14667 + 1500 x 0.4) / 2000 = 0.336667, actual 1100/2000 = 0.55
- A/R at 2025-03-31: charged 4000 - paid 1780 (C1 300, C2 100, C4 380, C5 1000) - written off 20 (C4-L1) = 2200;
  avg daily charges = 4000/90 -> 49.5 days
"""
import pytest


def kpi(con, grain="overall", **where):
    cond = " AND ".join([f"grain = '{grain}'"] + [f"{k} = '{v}'" for k, v in where.items()])
    return con.execute(f"SELECT * FROM kpi_cube WHERE {cond}").df().iloc[0]


def test_volume(mini_db):
    k = kpi(mini_db)
    assert k.claims == 8 and k.lines == 20 and k.net_billed_aed == 4000


def test_denial_rates(mini_db):
    k = kpi(mini_db)
    assert k.initial_denied_aed == pytest.approx(1220)
    assert k.initial_denial_rate_value == pytest.approx(0.305)
    assert k.initial_denial_rate_count == pytest.approx(0.20)
    assert k.final_denial_rate_value == pytest.approx(0.28)
    assert k.avoidable_denial_share == pytest.approx(220 / 1220)


def test_front_end(mini_db):
    k = kpi(mini_db)
    assert k.clean_claim_rate == pytest.approx(5 / 8)
    assert k.first_pass_yield == pytest.approx(4 / 8)


def test_resubmission_and_days(mini_db):
    k = kpi(mini_db)
    assert k.resubmission_overturn_rate == pytest.approx(0.5)
    assert k.median_days_to_payment == pytest.approx(22.5)
    assert k.late_submission_fee_aed == pytest.approx(1.5)


def test_timeliness(mini_db):
    t = mini_db.execute("SELECT * FROM kpi_timeliness WHERE payer_id IS NULL").df().iloc[0]
    assert t.pct_initial_within_45d == pytest.approx(0.75)
    assert t.pct_resubmission_within_30d == pytest.approx(0.5)
    assert t.late_payment_fee_due_aed == pytest.approx(4.2)


def test_mix_adjusted_scorecard(mini_db):
    s = mini_db.execute("SELECT * FROM payer_scorecard WHERE payer_id = 'P01'").df().iloc[0]
    assert s.expected_denial_rate_value == pytest.approx(0.336667, abs=1e-6)
    assert s.initial_denial_rate_value == pytest.approx(0.55)
    assert s.denial_rate_vs_expected == pytest.approx(0.55 / 0.336667, rel=1e-5)


def test_ar_days(mini_db):
    r = mini_db.execute("SELECT * FROM kpi_ar_monthly WHERE payer_id = 'ALL' AND year_month = '2025-03'").df().iloc[0]
    assert r.ar_balance_aed == pytest.approx(2200)
    assert r.ar_days == pytest.approx(2200 / (4000 / 90))


def test_star_schema_grain(mini_db):
    assert mini_db.execute("SELECT COUNT(*) FROM fact_claim_line").fetchone()[0] == 20
    assert mini_db.execute("SELECT COUNT(*) FROM fact_remittance").fetchone()[0] == 22   # 20 initial + 2 resubmitted
    assert mini_db.execute("SELECT COUNT(*) FROM fact_claim_line WHERE is_claim_anchor").fetchone()[0] == 8
    # every fact key resolves to a dimension row
    for col, dim in (("payer_key", "dim_payer"), ("service_line_key", "dim_service_line"), ("provider_key", "dim_provider")):
        assert mini_db.execute(f"SELECT COUNT(*) FROM fact_claim_line f LEFT JOIN {dim} d USING ({col}) WHERE d.{col} IS NULL").fetchone()[0] == 0
    assert mini_db.execute("""SELECT COUNT(*) FROM fact_claim_line f LEFT JOIN dim_date d ON d.date_key = f.service_date_key
                              WHERE d.date_key IS NULL""").fetchone()[0] == 0
