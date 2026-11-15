import ast
import csv
import datetime as dt
import hashlib
import io
import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.cleanup import cleanup_expired
from backend.config import Settings
from backend.db import Dataset, Job, fail_interrupted_jobs, utcnow
from backend.main import create_app

ROOT = Path(__file__).parents[2]
SAMPLES = ROOT / "sample_data"
SALES = SAMPLES / "sales_orders_messy.csv"
CUSTOMERS = SAMPLES / "customers_messy.xlsx"
HR = SAMPLES / "hr_survey_messy.csv"
DOWNLOADS = ["clean.csv", "clean.xlsx", "report.html", "recipe.yaml", "changelog.csv"]
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(storage_dir=tmp_path / "storage"))


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def upload(client, path: Path = SALES, name: str | None = None, content: bytes | None = None):
    data = content if content is not None else path.read_bytes()
    return client.post("/api/datasets", files={"file": (name or path.name, io.BytesIO(data))})


def profiled(client, path: Path = SALES, body: dict | None = None) -> str:
    dataset_id = upload(client, path).json()["dataset_id"]
    r = client.post(f"/api/datasets/{dataset_id}/profile", json=body or {})
    assert r.status_code == 202
    assert client.get(f"/api/jobs/{r.json()['job_id']}").json()["status"] == "done"
    return dataset_id


def cleaned(client, path: Path = SALES, approve_all: bool = True) -> tuple[str, str]:
    dataset_id = profiled(client, path)
    proposals = client.get(f"/api/datasets/{dataset_id}/profile").json()["proposals"]
    body = {"approved": [p["id"] for p in proposals]} if approve_all else {}
    r = client.post(f"/api/datasets/{dataset_id}/clean", json=body)
    assert r.status_code == 202
    return dataset_id, r.json()["job_id"]


def error_code(response) -> str:
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"} and body["error"]["message"]
    return body["error"]["code"]


# --------------------------------------------------------------------------- upload

def test_upload_csv(client, app):
    r = upload(client)
    assert r.status_code == 201
    body = r.json()
    assert UUID_RE.match(body["dataset_id"])
    assert body["filename"] == SALES.name and body["file_type"] == "csv"
    assert body["size_bytes"] == SALES.stat().st_size
    assert len(body["sheets"]) == 1
    sheet = body["sheets"][0]
    assert sheet["name"] is None and sheet["detected_header_row"] == 0
    assert sheet["preview"][0][0] == "Order ID" and len(sheet["preview"]) == 10
    expires = dt.datetime.strptime(body["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    assert dt.timedelta(hours=23, minutes=59) < expires - utcnow() <= dt.timedelta(hours=24)


def test_upload_xlsx_lists_sheets(client):
    body = upload(client, CUSTOMERS).json()
    assert [s["name"] for s in body["sheets"]] == ["Customers", "Notes"]
    assert body["sheets"][0]["detected_header_row"] == 2


def test_original_is_stored_unchanged_under_a_fixed_name(client, app):
    dataset_id = upload(client, name="../../evil name.csv").json()["dataset_id"]
    folder = app.state.ctx.storage.root / dataset_id
    stored = folder / "original.csv"
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == hashlib.sha256(SALES.read_bytes()).hexdigest()
    assert sorted(p.name for p in folder.iterdir()) == ["inspection.json", "original.csv"]
    assert not list(app.state.ctx.storage.root.parent.glob("*evil*"))


@pytest.mark.parametrize("name", ["data.txt", "data.xls", "data.json", "noextension", "data.csv.exe"])
def test_upload_rejects_other_file_types(client, name):
    r = upload(client, name=name, content=b"a,b\n1,2\n")
    assert r.status_code == 415 and error_code(r) == "unsupported_file_type"


def test_upload_rejects_wrong_content(client, app):
    fake_xlsx = upload(client, name="fake.xlsx", content=b"a,b\n1,2\n")
    assert fake_xlsx.status_code == 415 and error_code(fake_xlsx) == "unsupported_file_type"
    binary_csv = upload(client, name="binary.csv", content=CUSTOMERS.read_bytes())
    assert binary_csv.status_code == 415
    assert [p.name for p in app.state.ctx.storage.root.iterdir()] == ["app.db"]     # nothing kept


def test_upload_rejects_empty_and_unreadable_files(client):
    assert error_code(upload(client, name="empty.csv", content=b"")) == "unreadable_file"
    r = upload(client, name="blank.csv", content=b"  \n \n")
    assert r.status_code == 422 and error_code(r) == "unreadable_file"


def test_upload_size_limit(tmp_path):
    app = create_app(Settings(storage_dir=tmp_path / "s", max_upload_bytes=1000))
    with TestClient(app) as client:
        ok = upload(client, name="small.csv", content=b"a,b\n" + b"1,2\n" * 100)
        assert ok.status_code == 201
        too_big = upload(client, name="big.csv", content=b"a,b\n" + b"1,2\n" * 300)
        assert too_big.status_code == 413 and error_code(too_big) == "file_too_large"
        assert len([p for p in app.state.ctx.storage.root.iterdir() if p.is_dir()]) == 1


def test_oversized_upload_is_refused_from_its_declared_length(tmp_path):
    app = create_app(Settings(storage_dir=tmp_path / "s", max_upload_bytes=1000))
    with TestClient(app) as client:
        r = upload(client, name="huge.csv", content=b"a,b\n" + b"1,2\n" * 400_000)
        assert r.status_code == 413 and error_code(r) == "file_too_large"


def test_default_limit_is_50_mb():
    assert Settings().max_upload_bytes == 50 * 1024 * 1024 and Settings().ttl_hours == 24


# --------------------------------------------------------------------------- profile

def test_profile_job_and_result(client):
    dataset_id = upload(client).json()["dataset_id"]
    not_yet = client.get(f"/api/datasets/{dataset_id}/profile")
    assert not_yet.status_code == 409 and error_code(not_yet) == "not_ready"

    r = client.post(f"/api/datasets/{dataset_id}/profile")
    assert r.status_code == 202 and UUID_RE.match(r.json()["job_id"])
    job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
    assert set(job) == {"job_id", "dataset_id", "type", "status", "progress_pct", "current_step",
                        "error", "created_at", "updated_at"}
    assert (job["type"], job["status"], job["progress_pct"], job["current_step"], job["error"]) == (
        "profile", "done", 100, "Done", None)
    assert job["dataset_id"] == dataset_id

    profile = client.get(f"/api/datasets/{dataset_id}/profile").json()
    assert profile["dataset_id"] == dataset_id
    assert profile["source"]["filename"] == SALES.name          # the uploaded name, not "original.csv"
    assert profile["row_count"] == 433 and len(profile["columns"]) == 10
    assert profile["quality"]["overall"] == 78.3
    assert len(profile["proposals"]) == 25          # region Tier 1 + Tier 2, customer_name casing
    assert {"id", "rule_id", "mode", "severity", "rows_affected", "samples"} <= set(profile["proposals"][0])


def test_profile_with_sheet_and_header_row(client):
    dataset_id = profiled(client, CUSTOMERS, {"sheet": "Notes", "header_row": 0})
    profile = client.get(f"/api/datasets/{dataset_id}/profile").json()
    assert profile["source"]["sheet"] == "Notes" and [c["name"] for c in profile["columns"]] == ["topic", "note"]


def test_profile_defaults_to_first_sheet_and_detected_header(client):
    dataset_id = profiled(client, CUSTOMERS)
    source = client.get(f"/api/datasets/{dataset_id}/profile").json()["source"]
    assert source["sheet"] == "Customers" and source["header_row"] == 2


def test_profile_bad_requests(client):
    xlsx = upload(client, CUSTOMERS).json()["dataset_id"]
    csv_id = upload(client).json()["dataset_id"]
    for dataset_id, body in [(xlsx, {"sheet": "Nope"}), (xlsx, {"header_row": -1}), (xlsx, {"header_row": 99999}),
                             (csv_id, {"sheet": "Sheet1"}), (csv_id, {"header_row": "abc"})]:
        r = client.post(f"/api/datasets/{dataset_id}/profile", json=body)
        assert r.status_code == 400 and error_code(r) == "invalid_request", body


def test_progress_is_recorded_while_a_job_runs(client, app, monkeypatch):
    from backend import jobs

    seen = []
    original = jobs._update

    def spy(ctx, job_id, **fields):
        original(ctx, job_id, **fields)
        with Session(ctx.engine) as session:
            job = session.get(Job, job_id)
            seen.append((job.status, job.progress_pct, job.current_step))

    monkeypatch.setattr(jobs, "_update", spy)
    profiled(client)
    assert seen[0][0] == "running" and seen[-1] == ("done", 100, "Done")
    steps = [s for _, _, s in seen]
    assert {"Reading file", "Profiling columns", "Scoring quality", "Finding fixes"} <= set(steps)
    pcts = [p for _, p, _ in seen]
    assert pcts == sorted(pcts) and all(p < 100 for p in pcts[:-1])


def test_failed_job_reports_a_safe_error(client, app, monkeypatch):
    from backend import jobs

    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(jobs.pipeline, "profile", boom)
    dataset_id = upload(client).json()["dataset_id"]
    job_id = client.post(f"/api/datasets/{dataset_id}/profile").json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "internal_error"
    assert "secret" not in job["error"]["message"]
    assert client.get(f"/api/datasets/{dataset_id}/profile").status_code == 409


def test_unknown_ids_are_404(client):
    missing = str(uuid.uuid4())
    for url in [f"/api/jobs/{missing}", f"/api/datasets/{missing}/profile", f"/api/datasets/{missing}/results",
                f"/api/datasets/{missing}/downloads/clean.csv", "/api/jobs/not-a-uuid",
                "/api/datasets/..%2F..%2Fetc/profile", "/api/nope"]:
        r = client.get(url)
        assert r.status_code == 404 and error_code(r) == "not_found", url
    assert client.post(f"/api/datasets/{missing}/profile").status_code == 404
    assert client.post(f"/api/datasets/{missing}/clean", json={}).status_code == 404


# --------------------------------------------------------------------------- clean and results

def test_clean_before_profile_is_409(client):
    dataset_id = upload(client).json()["dataset_id"]
    r = client.post(f"/api/datasets/{dataset_id}/clean", json={})
    assert r.status_code == 409 and error_code(r) == "not_ready"
    assert client.get(f"/api/datasets/{dataset_id}/results").status_code == 409
    assert client.get(f"/api/datasets/{dataset_id}/downloads/clean.csv").status_code == 409


def test_clean_job_and_results(client):
    dataset_id, job_id = cleaned(client)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert (job["type"], job["status"], job["progress_pct"]) == ("clean", "done", 100)

    results = client.get(f"/api/datasets/{dataset_id}/results").json()
    assert set(results) == {"dataset_id", "run_id", "before", "after", "columns", "summary", "changes",
                            "downloads", "warnings"}
    assert results["run_id"] == job_id                           # the clean job id is the run id
    assert results["before"]["overall"] == 78.3 and results["after"]["overall"] == 92.0
    assert results["summary"]["rows_after"] == 400
    assert results["downloads"] == DOWNLOADS
    changes = results["changes"]
    assert changes["total"] == results["summary"]["total_changes"] == 1396   # M6.2: +9 "Wset" -> "West"; M6.5: +48 name capitals
    assert (changes["limit"], changes["offset"], len(changes["items"])) == (100, 0, 100)
    first = changes["items"][0]
    assert list(first) == ["run_id", "rule_id", "rule_version", "row_id", "column", "change_type",
                           "old_value", "new_value", "action", "timestamp", "reason"]   # M6b: reason added
    assert first["run_id"] == job_id and first["row_id"] is None and first["change_type"] == "header_renamed"


def test_change_log_filters_and_paging(client):
    dataset_id, _ = cleaned(client)
    url = f"/api/datasets/{dataset_id}/results"
    total = client.get(url).json()["changes"]["total"]

    dates = client.get(url, params={"rule_id": "parse_dates", "limit": 500}).json()["changes"]
    assert 0 < dates["total"] < total and {i["rule_id"] for i in dates["items"]} == {"parse_dates"}
    assert all(isinstance(i["row_id"], int) for i in dates["items"])

    approved = client.get(url, params={"action": "approved"}).json()["changes"]
    assert {i["rule_id"] for i in approved["items"]} <= {"coerce_numeric", "parse_dates", "trim_and_normalize_text"}   # first page only

    both = client.get(url, params={"column": "region", "change_type": "cell", "action": "auto"}).json()["changes"]
    assert both["total"] > 0 and {i["column"] for i in both["items"]} == {"region"}

    removed = client.get(url, params={"change_type": "row_removed"}).json()["changes"]
    assert removed["total"] == 33 and all(i["column"] is None for i in removed["items"])

    page1 = client.get(url, params={"limit": 10, "offset": 0}).json()["changes"]["items"]
    page2 = client.get(url, params={"limit": 10, "offset": 10}).json()["changes"]["items"]
    assert len(page1) == len(page2) == 10 and page1 != page2
    assert client.get(url, params={"offset": total}).json()["changes"]["items"] == []
    for bad in ({"limit": 501}, {"limit": 0}, {"offset": -1}):
        assert client.get(url, params=bad).status_code == 400


def test_change_log_reason_column_is_served_paged_and_downloaded(client):
    """M6b: the 11th column `reason` reaches the API items and the downloaded changelog.csv."""
    dataset_id, _ = cleaned(client)
    url = f"/api/datasets/{dataset_id}/results"
    cats = client.get(url, params={"rule_id": "standardize_categories", "limit": 500}).json()["changes"]
    assert cats["total"] > 0 and all(i["reason"] for i in cats["items"])
    second = client.get(url, params={"rule_id": "standardize_categories", "limit": 1, "offset": 1}).json()["changes"]
    assert second["items"][0]["reason"] == cats["items"][1]["reason"]
    dates = client.get(url, params={"rule_id": "parse_dates"}).json()["changes"]["items"]
    assert dates and all(i["reason"] is None for i in dates)

    text = client.get(f"/api/datasets/{dataset_id}/downloads/changelog.csv").text
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][-1] == "reason" and {len(r) for r in rows} == {11}
    assert {r[-1] for r in rows[1:] if r[1] == "standardize_categories"} == {i["reason"] for i in cats["items"]}


def test_decisions_are_respected(client):
    dataset_id = profiled(client, HR)
    proposals = client.get(f"/api/datasets/{dataset_id}/profile").json()["proposals"]
    by_rule = {(p["rule_id"], p["column"]): p for p in proposals}
    dates = by_rule[("parse_dates", "start_date")]
    bools = by_rule[("standardize_booleans", "remote")]
    assert dates["mode"] == "suggest" and dates["editable_params"] == ["dayfirst"]
    r = client.post(f"/api/datasets/{dataset_id}/clean",
                    json={"rejected": [bools["id"]], "edited": [{"id": dates["id"], "params": {"dayfirst": True}}]})
    assert r.status_code == 202
    csv_text = client.get(f"/api/datasets/{dataset_id}/downloads/clean.csv").text
    header, first = csv_text.splitlines()[0].split(","), csv_text.splitlines()[1].split(",")
    row = dict(zip(header, first))
    assert row["remote"] in ("Y", "N", "y", "n")                 # rejected fix not applied
    raw_day, raw_month, raw_year = HR.read_text(encoding="utf-8-sig").splitlines()[1].split(",")[2].split("/")
    assert row["start_date"] == f"{raw_year}-{raw_month}-{raw_day}"   # edited to day-first
    changes = client.get(f"/api/datasets/{dataset_id}/results", params={"rule_id": "standardize_booleans"}).json()
    assert changes["changes"]["total"] == 0


def test_clean_rejects_bad_decisions(client):
    dataset_id = profiled(client)
    some = client.get(f"/api/datasets/{dataset_id}/profile").json()["proposals"][0]["id"]
    for body in [{"approved": ["sug_unknown00000"]}, {"approved": [some], "rejected": [some]},
                 {"edited": [{"id": some, "params": {"mapping": {}}}]}, {"approved": "not-a-list"}]:
        r = client.post(f"/api/datasets/{dataset_id}/clean", json=body)
        assert r.status_code == 400 and error_code(r) == "invalid_request", body
    assert client.get(f"/api/datasets/{dataset_id}/results").status_code == 409


def test_reprofiling_clears_old_results(client):
    dataset_id, _ = cleaned(client)
    assert client.get(f"/api/datasets/{dataset_id}/results").status_code == 200
    client.post(f"/api/datasets/{dataset_id}/profile")
    assert client.get(f"/api/datasets/{dataset_id}/results").status_code == 409
    assert client.get(f"/api/datasets/{dataset_id}/downloads/clean.csv").status_code == 409


# --------------------------------------------------------------------------- downloads

@pytest.mark.parametrize(
    "name, download_name, content_type, starts_with",
    [
        ("clean.csv", "sales_orders_messy_clean.csv", "text/csv", b"order_id,customer_name"),
        ("clean.xlsx", "sales_orders_messy_clean.xlsx", "application/vnd.openxmlformats", b"PK"),
        ("report.html", "sales_orders_messy_report.html", "text/html", b"<!DOCTYPE html>"),
        ("recipe.yaml", "sales_orders_messy_recipe.yaml", "application/yaml", b"recipe_version"),
        ("changelog.csv", "sales_orders_messy_changelog.csv", "text/csv", b"run_id,rule_id"),
    ],
)
def test_downloads(client, name, download_name, content_type, starts_with):
    dataset_id, _ = cleaned(client)
    r = client.get(f"/api/datasets/{dataset_id}/downloads/{name}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(content_type)
    assert "attachment" in r.headers["content-disposition"] and download_name in r.headers["content-disposition"]
    assert r.content.startswith(starts_with)


def test_report_and_recipe_use_the_uploaded_file_name(client):
    dataset_id, _ = cleaned(client)
    assert SALES.name in client.get(f"/api/datasets/{dataset_id}/downloads/report.html").text
    assert f"filename: {SALES.name}" in client.get(f"/api/datasets/{dataset_id}/downloads/recipe.yaml").text


@pytest.mark.parametrize("name", ["original.csv", "profile.json", "app.db", "results.json", "..%2Fapp.db"])
def test_only_the_five_outputs_can_be_downloaded(client, name):
    dataset_id, _ = cleaned(client)
    r = client.get(f"/api/datasets/{dataset_id}/downloads/{name}")
    assert r.status_code == 404 and error_code(r) == "not_found"


def test_full_flow_on_excel(client):
    dataset_id, job_id = cleaned(client, CUSTOMERS)
    results = client.get(f"/api/datasets/{dataset_id}/results").json()
    assert results["after"]["overall"] > results["before"]["overall"]
    assert client.get(f"/api/datasets/{dataset_id}/downloads/clean.xlsx").status_code == 200


# --------------------------------------------------------------------------- cleanup

def test_cleanup_deletes_expired_datasets_only(client, app):
    ctx = app.state.ctx
    old, _ = cleaned(client)
    fresh = profiled(client, HR)
    with Session(ctx.engine) as session:
        row = session.get(Dataset, old)
        row.expires_at = utcnow() - dt.timedelta(seconds=1)
        session.add(row)
        session.commit()

    assert client.get(f"/api/datasets/{old}/results").status_code == 404      # expired, even before cleanup runs
    assert cleanup_expired(ctx) == 1
    assert not (ctx.storage.root / old).exists() and (ctx.storage.root / fresh).exists()
    with Session(ctx.engine) as session:
        assert session.get(Dataset, old) is None and session.get(Dataset, fresh) is not None
        assert {j.dataset_id for j in session.exec(__import__("sqlmodel").select(Job)).all()} == {fresh}
    assert client.get(f"/api/datasets/{fresh}/profile").status_code == 200
    assert cleanup_expired(ctx) == 0


def test_cleanup_uses_the_24_hour_expiry(client, app):
    ctx = app.state.ctx
    dataset_id = upload(client).json()["dataset_id"]
    assert cleanup_expired(ctx, now=utcnow() + dt.timedelta(hours=23, minutes=59)) == 0
    assert cleanup_expired(ctx, now=utcnow() + dt.timedelta(hours=24, seconds=1)) == 1
    assert not (ctx.storage.root / dataset_id).exists()


def test_cleanup_runs_at_startup(tmp_path):
    settings = Settings(storage_dir=tmp_path / "s")
    with TestClient(create_app(settings)) as client:
        dataset_id = upload(client).json()["dataset_id"]
    app = create_app(settings)
    with Session(app.state.ctx.engine) as session:
        row = session.get(Dataset, dataset_id)
        row.expires_at = utcnow() - dt.timedelta(hours=1)
        session.add(row)
        session.commit()
    with TestClient(app) as client:
        import time

        deadline = time.time() + 5
        while (settings.storage_dir / dataset_id).exists() and time.time() < deadline:
            time.sleep(0.05)
        assert not (settings.storage_dir / dataset_id).exists()


def test_interrupted_jobs_are_marked_failed(app):
    ctx = app.state.ctx
    now = utcnow()
    with Session(ctx.engine) as session:
        session.add(Job(id=str(uuid.uuid4()), dataset_id="d", type="clean", status="running",
                        created_at=now, updated_at=now))
        session.commit()
    assert fail_interrupted_jobs(ctx.engine) == 1
    with Session(ctx.engine) as session:
        job = session.exec(__import__("sqlmodel").select(Job)).one()
        assert job.status == "failed" and job.error_code == "interrupted"


# --------------------------------------------------------------------------- design rules

def test_cors_allows_the_vite_dev_origin(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in client.get("/api/health", headers={"Origin": "http://evil.example"}).headers


def test_backend_uses_only_the_public_engine_surface():
    """Design rule 7: the backend calls engine.pipeline only (plus shared models and errors)."""
    allowed = {"engine", "engine.pipeline", "engine.models", "engine.errors"}
    for path in (ROOT / "backend").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("engine"):
                assert node.module in allowed, f"{path.name} imports {node.module}"
                if node.module == "engine":
                    assert {a.name for a in node.names} <= {"pipeline"}, path.name
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("engine") for a in node.names), path.name


def test_engine_has_no_web_code():
    for path in (ROOT / "engine").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+(fastapi|starlette|sqlmodel|uvicorn|backend)\b", text, re.M), path
