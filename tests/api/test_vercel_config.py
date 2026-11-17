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


def test_requirements_txt_is_the_exact_vercel_pin_list():
    # The Python builder reads requirements.txt; its priority against pyproject.toml is not documented,
    # so the file must be identical to the reviewed pins.
    assert (ROOT / "requirements.txt").read_bytes() == (ROOT / "requirements-vercel.txt").read_bytes()
    assert all("==" in line for line in (ROOT / "requirements.txt").read_text().splitlines()
               if line and not line.startswith("#"))


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
