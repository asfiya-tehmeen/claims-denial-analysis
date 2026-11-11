"""No post-submission information may reach the model features."""
import pandas as pd

from src.features import FEATURES, FORBIDDEN, PRE_SUBMISSION_SQL, build_features


def test_no_forbidden_feature_names():
    assert not set(FEATURES) & FORBIDDEN


def test_feature_query_does_not_touch_remittance_fields():
    sql = PRE_SUBMISSION_SQL.lower()
    for word in ["remittance", "initial_ra", "denied", "denial", "paid", "settlement", "resubmi", "overturn", "recovered"]:
        assert word not in sql, word


def test_features_do_not_change_when_outcomes_change(mini_db):
    flags = mini_db.execute("SELECT * FROM raw_scrubber_flags").df()
    before = build_features(mini_db, flags)[FEATURES + ["activity_id"]]
    # flip every outcome: mark all lines denied and rebuild the fact table
    mini_db.execute("CREATE OR REPLACE TABLE raw_remittances_bak AS SELECT * FROM raw_remittances")
    mini_db.execute("UPDATE raw_remittances SET payment_amount = 0, denial_code = 'MNEC-003'")
    from src.common import SQL
    mini_db.execute((SQL / "02_marts.sql").read_text(encoding="utf-8"))
    after = build_features(mini_db, flags)[FEATURES + ["activity_id"]]
    mini_db.execute("CREATE OR REPLACE TABLE raw_remittances AS SELECT * FROM raw_remittances_bak")
    mini_db.execute((SQL / "02_marts.sql").read_text(encoding="utf-8"))
    pd.testing.assert_frame_equal(before.sort_values("activity_id").reset_index(drop=True),
                                  after.sort_values("activity_id").reset_index(drop=True))
