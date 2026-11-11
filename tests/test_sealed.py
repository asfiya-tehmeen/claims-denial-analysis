"""Only src/score.py may read the sealed answer key (the generator writes it; common.py names the path)."""
import re

from src.common import ROOT

ALLOWED = {"score.py", "generator.py", "common.py"}
# an actual read needs the path constant or a file name; prose mentioning "sealed truth" is fine
PATTERN = re.compile(r"SEALED|sealed/|answer_key\.json|line_truth\.parquet")


def test_only_score_reads_the_answer_key():
    offenders = []
    for path in list((ROOT / "src").glob("*.py")) + list((ROOT / "sql").glob("*.sql")):
        if path.name in ALLOWED:
            continue
        if PATTERN.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert not offenders, f"these files reference the sealed answer key: {offenders}"


def test_analysis_config_loader_hides_effects():
    from src.common import sim_config
    cfg = sim_config()
    assert "effects" not in cfg and "effect_seed" not in cfg
