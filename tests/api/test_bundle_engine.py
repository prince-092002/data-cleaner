"""frontend/scripts/bundle-engine.mjs packs engine/ + browser/ into the Pyodide bundle."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "frontend" / "scripts" / "bundle-engine.mjs"


def _run(root):
    return subprocess.run(["node", str(SCRIPT), str(root)], capture_output=True, text=True)


def _tree(tmp_path, with_browser=True):
    shutil.copytree(ROOT / "engine", tmp_path / "engine", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "engine" / "__pycache__").mkdir(exist_ok=True)
    (tmp_path / "engine" / "__pycache__" / "x.py").write_text("junk")
    if with_browser:
        (tmp_path / "browser" / "shims").mkdir(parents=True)
        (tmp_path / "browser" / "adapter.py").write_text("A = 1")
        (tmp_path / "browser" / "shims" / "s.py").write_text("S = 1")
    return tmp_path


def test_bundle_has_every_engine_file_and_no_pycache(tmp_path):
    _tree(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    bundle = json.loads((tmp_path / "frontend" / "public" / "py" / "bundle.json").read_text(encoding="utf-8"))
    want = {"engine/" + p.relative_to(ROOT / "engine").as_posix() for p in (ROOT / "engine").rglob("*.py")
            if "__pycache__" not in p.parts}
    assert want
    assert not any("__pycache__" in k for k in bundle)
    assert set(bundle) == want | {"browser/adapter.py", "shims/s.py"}
    assert bundle["browser/adapter.py"] == "A = 1" and bundle["shims/s.py"] == "S = 1"


def test_missing_browser_dir_fails_without_writing(tmp_path):
    _tree(tmp_path, with_browser=False)
    r = _run(tmp_path)
    assert r.returncode != 0 and "browser" in r.stderr
    assert not (tmp_path / "frontend" / "public" / "py" / "bundle.json").exists()
