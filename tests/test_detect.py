"""Change detectors on synthetic series with a known step."""
import numpy as np

from src.detect_change import binomial_cusum, gaussian_cusum, naive_rule


def test_binomial_cusum_finds_a_step_and_stays_quiet_before_it():
    rng = np.random.default_rng(1)
    n = np.full(60, 200)
    p = np.where(np.arange(60) < 30, 0.01, 0.05)
    x = rng.binomial(n, p)
    alarms = binomial_cusum(n, x, p0=0.01)
    assert alarms and 30 <= alarms[0] <= 34
    assert not [a for a in alarms if a < 30]


def test_binomial_cusum_quiet_on_stationary_series():
    rng = np.random.default_rng(2)
    n = np.full(100, 200)
    x = rng.binomial(n, 0.02)
    assert len(binomial_cusum(n, x, p0=0.02)) <= 1


def test_gaussian_cusum_finds_slower_payment():
    rng = np.random.default_rng(3)
    v = np.concatenate([rng.normal(28, 2, 40), rng.normal(45, 2, 20)])
    alarms = gaussian_cusum(v, 28, 2)
    assert alarms and 40 <= alarms[0] <= 42


def test_naive_rule_needs_three_denials():
    n = np.full(20, 50); x = np.zeros(20, int); x[15] = 2
    assert naive_rule(n, x, start=8) == []
