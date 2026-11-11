"""Shared paths and config loaders."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DATA = ROOT / "data"
REFERENCE = DATA / "reference"
DOWNLOADS = REFERENCE / "downloads"
RAW = DATA / "raw"
SEALED = RAW / "sealed"          # read ONLY by src/score.py (enforced by tests/test_sealed.py)
CLEAN = DATA / "clean"
GOLD = DATA / "gold"
DB_PATH = GOLD / "denialguard.duckdb"
SQL = ROOT / "sql"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
POWERBI = REPORTS / "powerbi"
METRICS = REPORTS / "metrics.json"

HONESTY_NOTE = (
    "Data honesty: claims are SIMULATED using the published DHA eClaimLink field structure "
    "(NPHIES mapping note in docs/data_dictionary.md). Code sets and edit rules come from real "
    "public sources listed in data/reference/SOURCES.md. No result describes real UAE or Saudi denial rates."
)

# Train / validation / test split by service month index (1 = first simulated month)
TRAIN_MONTHS = range(1, 16)
VALID_MONTHS = range(16, 19)
TEST_MONTHS = range(19, 25)


def load_yaml(name: str) -> dict:
    with open(CONFIG / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def catalog() -> dict:
    return load_yaml("catalog.yaml")


def sim_config() -> dict:
    """Simulator config WITHOUT the planted-effect ranges (analysis code may use this)."""
    cfg = load_yaml("sim.yaml")
    cfg.pop("effects", None)
    cfg.pop("effect_seed", None)
    return cfg


def review_config() -> dict:
    return load_yaml("review.yaml")


def update_metrics(section: str, values) -> None:
    """Merge one section into reports/metrics.json (the single source for every reported number)."""
    import json
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(METRICS.read_text()) if METRICS.exists() else {}
    data[section] = values
    METRICS.write_text(json.dumps(data, indent=2, default=_jsonable))


def read_metrics() -> dict:
    import json
    return json.loads(METRICS.read_text()) if METRICS.exists() else {}


def _jsonable(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def ensure_dirs() -> None:
    for p in (REFERENCE, DOWNLOADS, RAW, SEALED, CLEAN, GOLD, FIGURES, POWERBI):
        p.mkdir(parents=True, exist_ok=True)
