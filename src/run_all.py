"""Rebuild everything from the seed: python -m src.run_all"""
from __future__ import annotations

import time

from src import (build_db, detect_change, drivers, export_powerbi, generator, model, reference, report, score,
                 scrubber, validate, worklist)
from src.common import METRICS, REFERENCE, ensure_dirs

STEPS = [
    ("reference data", lambda: reference.main() if not (REFERENCE / "ncci_ptp.csv").exists() else None),
    ("generate", lambda: print(generator.generate())),
    ("validate", validate.main),
    ("scrub", scrubber.main),
    ("build DuckDB + SQL KPIs", build_db.main),
    ("models", model.main),
    ("worklist", worklist.main),
    ("change detection", detect_change.main),
    ("drivers", drivers.main),
    ("Power BI export", export_powerbi.main),
    ("score (unseal answer key)", score.main),
    ("report", report.main),
]


def main() -> None:
    ensure_dirs()
    if METRICS.exists():
        METRICS.unlink()
    t0 = time.time()
    for name, fn in STEPS:
        t = time.time()
        print(f"\n=== {name} ===", flush=True)
        fn()
        print(f"--- {name}: {time.time() - t:.1f}s", flush=True)
    print(f"\nDone in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
