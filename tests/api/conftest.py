"""Shared fixtures: a SQLite engine always, a Postgres engine only when TEST_DATABASE_URL is set.

The Postgres fixture creates its own schema (s12test_<random>), points the connection at it with
search_path, and drops it afterwards, so it can run against a shared database.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from backend.db import make_engine, normalize_url


@pytest.fixture(params=["sqlite", "postgres"])
def db_engine(request, tmp_path):
    if request.param == "sqlite":
        engine = make_engine(tmp_path / "app.db")
        yield engine
        engine.dispose()
        return
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    schema = f"s12test_{uuid.uuid4().hex[:10]}"
    admin = create_engine(normalize_url(url), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    sep = "&" if "?" in url else "?"
    engine = make_engine(f"{url}{sep}options=-csearch_path%3D{schema}")
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
import pytest


@pytest.fixture(autouse=True)
def _local_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DC_STORAGE_BACKEND", raising=False)
