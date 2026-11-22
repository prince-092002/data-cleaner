"""The browser adapter must answer exactly like backend/routes.py for the same file and requests."""
import io
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from browser import adapter
from browser.adapter import AdapterError

SAMPLES = Path(__file__).parents[2] / "sample_data"
CSV = SAMPLES / "messy_orders_demo.csv"
XLSX = SAMPLES / "customers_messy.xlsx"


@pytest.fixture
def api(tmp_path):
    with TestClient(create_app(Settings(storage_dir=tmp_path / "storage"))) as c:
        yield c


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    adapter.reset(tmp_path / "work")


def code_of(fn, *a, **k):
    with pytest.raises(AdapterError) as e:
        fn(*a, **k)
    return e.value.status, e.value.code


def norm(value):
    """Drop what legitimately differs between two runs: ids and timestamps."""
    text = json.dumps(value, sort_keys=True)
    text = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "ID", text)
    text = re.sub(r"\d{4}-\d\d-\d\dT[\d:.]+(Z|\+00:00)?", "TS", text)
    return json.loads(text)


def backend_clean(api, path: Path):
    r = api.post("/api/datasets", files={"file": (path.name, io.BytesIO(path.read_bytes()))})
    up = r.json()
    api.post(f"/api/datasets/{up['dataset_id']}/profile", json={})
    prof = api.get(f"/api/datasets/{up['dataset_id']}/profile").json()
    api.post(f"/api/datasets/{up['dataset_id']}/clean", json={"approved": [p["id"] for p in prof["proposals"]]})
    return up, prof


def adapter_clean(path: Path):
    up = adapter.upload(path.name, path.read_bytes())
    prof = adapter.profile(up["dataset_id"])
    adapter.clean(up["dataset_id"], json.dumps({"approved": [p["id"] for p in prof["proposals"]]}))
    return up, prof


@pytest.mark.parametrize("path", [CSV, XLSX])
def test_same_answers_as_backend(api, path):
    b_up, b_prof = backend_clean(api, path)
    a_up, a_prof = adapter_clean(path)
    assert norm(a_up) == norm(b_up)
    assert norm(a_prof) == norm(b_prof)
    assert a_up["dataset_id"] == a_prof["dataset_id"]
    for query in [
        {},
        {"limit": 7, "offset": 3},
        {"rule_id": "trim_and_normalize_text"},
        {"action": "auto", "limit": 500},
        {"change_type": "row_removed"},
        {"column": "nope"},
    ]:
        expected = api.get(f"/api/datasets/{b_up['dataset_id']}/results", params=query).json()
        got = adapter.results(a_up["dataset_id"], query)
        assert norm(got) == norm(expected), query
        assert got["changes"]["total"] == expected["changes"]["total"]


def test_downloads_names_and_mime(api):
    b_up, _ = backend_clean(api, CSV)
    a_up, _ = adapter_clean(CSV)
    for name in ["clean.csv", "report.html", "recipe.yaml", "changelog.csv", "clean.xlsx"]:
        r = api.get(f"/api/datasets/{b_up['dataset_id']}/downloads/{name}")
        data, filename, mime = adapter.file(a_up["dataset_id"], name)
        assert filename == re.search(r'filename="([^"]+)"', r.headers["content-disposition"]).group(1)
        assert mime == r.headers["content-type"]
        assert len(data) > 0
    assert adapter.build_xlsx(a_up["dataset_id"]).exists()


def test_upload_errors():
    assert code_of(adapter.upload, "a.txt", b"x") == (415, "unsupported_file_type")
    assert code_of(adapter.upload, "a.csv", b"") == (422, "unreadable_file")
    assert code_of(adapter.upload, "a.xlsx", b"not a zip") == (415, "unsupported_file_type")
    assert code_of(adapter.upload, "a.csv", b"%PDF-1.4 x") == (415, "unsupported_file_type")
    assert code_of(adapter.upload, "a.csv", b"a,b\n" + b"x" * (adapter.MAX_UPLOAD_BYTES + 1)) == (413, "file_too_large")
    assert code_of(adapter.upload, "a.csv", b"\n\n\n") == (422, "unreadable_file")


def test_profile_errors():
    d = adapter.upload("o.csv", CSV.read_bytes())["dataset_id"]
    assert code_of(adapter.profile, "nope") == (404, "not_found")
    assert code_of(adapter.profile, d, sheet="S") == (400, "invalid_request")
    assert code_of(adapter.profile, d, header_row=10**6) == (400, "invalid_request")
    assert code_of(adapter.profile, d, header_row=-1) == (400, "invalid_request")
    x = adapter.upload("c.xlsx", XLSX.read_bytes())["dataset_id"]
    assert code_of(adapter.profile, x, sheet="no such sheet") == (400, "invalid_request")


def test_not_ready_and_unknown():
    d = adapter.upload("o.csv", CSV.read_bytes())["dataset_id"]
    assert code_of(adapter.get_profile, d) == (409, "not_ready")
    assert code_of(adapter.clean, d, "{}") == (409, "not_ready")
    assert code_of(adapter.results, d, {}) == (409, "not_ready")
    assert code_of(adapter.file, d, "clean.csv") == (409, "not_ready")
    assert code_of(adapter.get_profile, "nope") == (404, "not_found")
    assert code_of(adapter.results, "nope", {}) == (404, "not_found")
    adapter.profile(d)
    assert code_of(adapter.clean, d, json.dumps({"approved": ["bogus"]})) == (400, "invalid_request")
    assert code_of(adapter.file, d, "clean.csv") == (409, "not_ready")
    assert code_of(adapter.file, d, "evil.txt") == (404, "not_found")
    assert code_of(adapter.build_xlsx, d) == (409, "not_ready")


def test_results_query_limits():
    up, _ = adapter_clean(CSV)
    for bad in [{"limit": 0}, {"limit": 501}, {"offset": -1}]:
        assert code_of(adapter.results, up["dataset_id"], bad) == (400, "invalid_request")


def test_progress_reported():
    d = adapter.upload("o.csv", CSV.read_bytes())["dataset_id"]
    seen = []
    adapter.profile(d, progress=lambda pct, step: seen.append((pct, step)))
    assert seen and seen[-1][0] == 100


def test_new_upload_drops_earlier_datasets():
    first = adapter.upload("o.csv", CSV.read_bytes())["dataset_id"]
    folder = adapter._datasets[first]["dir"]
    second = adapter.upload("o2.csv", CSV.read_bytes())["dataset_id"]
    assert code_of(adapter.get_profile, first) == (404, "not_found")
    assert not folder.exists()
    assert list(adapter._datasets) == [second]
