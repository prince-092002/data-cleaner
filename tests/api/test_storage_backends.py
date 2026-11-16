"""Step 12: the storage interface on local disk and on Vercel Blob (fake client, no network)."""

import io

import pytest

from backend.storage import BlobStorage, LocalStorage, StorageNotFound, TooLarge, write_limited
from tests.api.fake_blob import FakeBlobClient


@pytest.fixture(params=["local", "blob"])
def store(request, tmp_path):
    if request.param == "local":
        return LocalStorage(tmp_path / "s")
    return BlobStorage(FakeBlobClient())


def test_put_get_stream_exists_and_missing(store, tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"hello")
    store.put_file("d/runs/r/a.txt", src)
    store.put_bytes("d/b.json", b"{}")
    assert store.exists("d/runs/r/a.txt") and not store.exists("d/nope")
    assert store.read_bytes("d/b.json") == b"{}"
    dest = tmp_path / "out" / "a.txt"
    store.get_file("d/runs/r/a.txt", dest)
    assert dest.read_bytes() == b"hello"
    assert b"".join(store.open_stream("d/runs/r/a.txt")) == b"hello"
    with pytest.raises(StorageNotFound):
        store.open_stream("d/nope")
    with pytest.raises(StorageNotFound):
        store.read_bytes("d/nope")
    with pytest.raises(StorageNotFound):
        store.get_file("d/nope", tmp_path / "x")


def test_list_and_delete_by_prefix(store):
    for key in ("d1/original.csv", "d1/runs/r1/clean.csv", "d1/runs/r2/clean.csv", "d2/original.csv"):
        store.put_bytes(key, b"x")
    assert sorted(k for k, _ in store.list_keys("d1/runs/")) == ["d1/runs/r1/clean.csv", "d1/runs/r2/clean.csv"]
    store.delete_prefix("d1/")
    assert [k for k, _ in store.list_keys("")] == ["d2/original.csv"]
    store.delete_prefix("d1/")                         # deleting nothing is fine


def test_write_limited_stops_at_the_limit(tmp_path):
    with pytest.raises(TooLarge):
        write_limited(io.BytesIO(b"x" * 100), tmp_path / "u", 10)
    assert write_limited(io.BytesIO(b"x" * 5), tmp_path / "u", 10) == 5
