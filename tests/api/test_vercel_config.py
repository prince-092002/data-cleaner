"""Deployment wiring (docs/ADR-hosting-vercel.md): one project, exact pins, cron, one 300 s function."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_vercel_function_wiring():
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert cfg["crons"] == [{"path": "/api/cron/cleanup", "schedule": "0 4 * * *"}]
    assert cfg["functions"]["backend/main.py"]["maxDuration"] == 300
    assert "frontend" in cfg["buildCommand"] and cfg["framework"] == "fastapi"
    tool = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["vercel"]
    assert tool["entrypoint"] == "backend.main:app"
    assert tool["subscribers"] == [{"entrypoint": "backend.worker"}]
    assert (ROOT / ".python-version").read_text().strip() == "3.12"


def test_requirements_txt_is_exact_pins():
    """requirements.txt is the exact pin list for local/dev installs; Vercel reads pyproject.toml, not this file."""
    assert all("==" in line for line in (ROOT / "requirements.txt").read_text().splitlines()
               if line and not line.startswith("#"))


def test_backend_runtime_packages_are_project_dependencies():
    # Vercel installs only [project].dependencies; the optional `backend` extra is never installed there.
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    names = " ".join(deps).lower()
    for pkg in ("fastapi", "sqlmodel", "python-multipart", "vercel==", "psycopg[binary]"):
        assert pkg in names, pkg
    assert "uvicorn" not in names


def test_vercelignore_keeps_dev_files_out_but_frontend_in():
    lines = [l for l in (ROOT / ".vercelignore").read_text().splitlines() if l and not l.startswith("#")]
    for out in ("tests", "evaluation", "docs", ".claude", "storage", "node_modules", ".venv", "sample_data"):
        assert out in " ".join(lines).replace("/", " "), out
    assert not any(l.strip("/") in ("frontend", "frontend/public") for l in lines)


def test_env_example_lists_production_names_without_values():
    names = {l.split("=")[0] for l in (ROOT / ".env.example").read_text().splitlines() if "=" in l and not l.startswith("#")}
    assert {"DATABASE_URL", "DC_STORAGE_BACKEND", "DC_JOB_RUNNER", "DC_MAX_UPLOAD_MB", "CRON_SECRET", "DC_IP_HASH_SALT",
            "DC_DAILY_UPLOAD_CAP", "DC_DAILY_JOB_CAP", "DC_DAILY_IP_CAP", "DC_DAILY_IP_UPLOAD_CAP",
            "DC_STORAGE_LIMIT_MB"} <= names


def test_built_frontend_goes_to_site_dir_inside_the_function_bundle():
    # Vercel's Python builder drops **/public/** from the function and serves public/ only if it is in the
    # upload, so a public/ made by buildCommand is lost; backend.main serves site/ instead.
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert cfg["buildCommand"].endswith("cp -r frontend/dist site")
    assert "site" not in cfg["functions"]["backend/main.py"]["excludeFiles"]
