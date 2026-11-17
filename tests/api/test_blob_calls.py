"""Blob operations budget: the free store allows few advanced operations a month, so one full visit
(upload, profile, clean, all five downloads) must stay cheap. The table is printed with `pytest -s`."""

import io
from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.storage import DOWNLOADS, BlobStorage
from tests.api.fake_blob import FakeBlobClient

SALES = Path(__file__).parents[2] / "sample_data" / "sales_orders_messy.csv"
# Measured after the changes (see the printed table). list includes the one start-up sweep of the in-process dev loop.
MAX_CALLS = {"put": 12, "get": 14, "head": 4, "list": 5, "delete": 2}


def test_one_full_visit_stays_inside_the_blob_budget(tmp_path):
    fake = FakeBlobClient()
    app = create_app(Settings(storage_dir=tmp_path / "s"), storage=BlobStorage(fake))
    with TestClient(app) as c:
        r = c.post("/api/datasets", files={"file": (SALES.name, io.BytesIO(SALES.read_bytes()))})
        dataset_id = r.json()["dataset_id"]
        assert c.post(f"/api/datasets/{dataset_id}/profile", json={}).status_code == 202
        assert c.post(f"/api/datasets/{dataset_id}/clean", json={}).status_code == 202
        assert c.get(f"/api/datasets/{dataset_id}/results").status_code == 200
        for name in DOWNLOADS:
            assert c.get(f"/api/datasets/{dataset_id}/downloads/{name}").status_code == 200, name
    print("\nBlob calls for one full visit:")
    for op in ("put", "get", "head", "list", "delete"):
        print(f"  {op:<7}{fake.calls[op]:>4}")
    print(f"  total  {sum(fake.calls.values()):>4}")
    for op, limit in MAX_CALLS.items():
        assert fake.calls[op] <= limit, f"{op}: {fake.calls[op]} calls, budget {limit}"
