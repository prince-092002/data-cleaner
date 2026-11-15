"""Runs the precision/recall evaluation (evaluation/run_evaluation.py) and checks its guard rails.

Recall and precision numbers are reported, not asserted yet.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.run_evaluation import DIMENSIONS, FILES, HELDOUT_FILES, run, strict_fixed  # noqa: E402


def test_evaluation_guard_rails(tmp_path, capsys):
    results = run(out_dir=tmp_path)

    assert capsys.readouterr().out == ""                     # run() prints nothing
    assert (tmp_path / "RESULTS.md").is_file()
    assert (tmp_path / "results.json").is_file()

    assert results["damaged_cells"]["total"] == 0, results["damaged_cells"]["examples"][:3]
    assert results["damaged_cells"]["cells_compared"] > 0
    assert set(results["files"]) == set(FILES)
    for name, f in results["files"].items():
        assert f["alignment"]["checked"] > 0, name
        for dim in DIMENSIONS:
            assert f["lift"][dim] >= 0, f"{name}: {dim} dropped by {f['lift'][dim]}"

    held = results["heldout"]                                # M6 step 8: never tune against this batch
    assert set(held["files"]) == set(HELDOUT_FILES)
    assert held["damaged_cells"]["total"] == 0, held["damaged_cells"]["examples"][:3]
    assert held["false_positive_changes"] == 0
    for name, f in held["files"].items():
        assert f["alignment"]["checked"] == f["alignment"]["matched"] > 0, name
        for dim in DIMENSIONS:
            assert f["lift"][dim] >= 0, f"held-out {name}: {dim} dropped by {f['lift'][dim]}"
    for batch in (results, held):
        a = batch["all_errors"]
        assert a["injected"] > 0 and a["fixed"] <= a["detected_cell_level"] <= a["detected"] <= a["injected"]
        assert a["fix_recall"] <= a["fix_recall_if_date_order_is_right"] <= a["detection_recall"] <= 100


def test_strict_fixed_gives_no_partial_credit():
    assert strict_fixed("2024-04-03", "2024-04-03") and not strict_fixed("03/04/2024", "2024-04-03")
    assert strict_fixed("1200.50", "1200.5") and not strict_fixed("$1,200.50", "1200.5")
    assert strict_fixed("true", "Yes") and not strict_fixed("Y", "Yes")
    assert strict_fixed(None, None) and not strict_fixed("N/A", None)
    assert strict_fixed("North", "North") and not strict_fixed("north", "North") and not strict_fixed(" North", "North")
    assert strict_fixed("I don\u2019t know", "I don\u2019t know")          # curly quotes are kept by the engine
    assert not strict_fixed(None, "ORD-1")                             # a deleted value is never fixed
