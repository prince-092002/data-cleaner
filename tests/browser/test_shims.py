"""The pure-Python OSA shim used in the browser must agree with the real rapidfuzz."""
import importlib.util
import random
from pathlib import Path

from rapidfuzz.distance import OSA

SHIM = Path(__file__).resolve().parents[2] / "browser" / "shims" / "rapidfuzz" / "distance.py"


def _load():
    spec = importlib.util.spec_from_file_location("shim_distance", SHIM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_osa_matches_rapidfuzz():
    shim = _load()
    rng = random.Random(7)
    alphabet = "abcde xyZ"
    for _ in range(400):
        a = "".join(rng.choices(alphabet, k=rng.randint(0, 12)))
        b = "".join(rng.choices(alphabet, k=rng.randint(0, 12)))
        assert shim.OSA.distance(a, b) == OSA.distance(a, b), (a, b)


def test_clevercsv_stub_raises():
    import pytest
    spec = importlib.util.spec_from_file_location("cc_stub", SHIM.parents[1] / "clevercsv" / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(Exception):
        mod.Sniffer().sniff("a,b\n1,2\n") if hasattr(mod, "Sniffer") else mod.detect_dialect("a,b")
