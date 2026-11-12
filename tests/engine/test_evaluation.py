"""Runs the precision/recall evaluation (evaluation/run_evaluation.py) and checks its guard rails.

Recall and precision numbers are reported, not asserted yet.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.run_evaluation import DIMENSIONS, FILES, run  # noqa: E402


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
