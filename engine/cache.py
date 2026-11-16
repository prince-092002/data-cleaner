"""Read-once cache (M6). Parsing a big CSV or Excel file is slow, so profile() saves the parsed
all-text table as Parquet, with its "before" profile, and clean() reuses both.

The key is the file's content hash plus sheet, header row, engine version and a hash of the engine source code, so a copy of the
same upload (for example downloaded again to another folder) still hits, and any change misses.
Never writes next to the original upload: only into the cache_dir the caller gives.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path

import polars as pl

from engine import ENGINE_VERSION
from engine.ingest import IngestResult
from engine.models import DatasetProfile, SourceInfo

log = logging.getLogger("data_cleaner.cache")
CACHE_VERSION = "1"


def _engine_fingerprint() -> str:
    """Hash of every engine source file, so any engine code change misses the cache with no manual bump."""
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for file in sorted(root.rglob("*.py")):
        digest.update(file.relative_to(root).as_posix().encode("utf-8"))
        digest.update(file.read_bytes().replace(b"\r\n", b"\n"))   # same hash for CRLF and LF checkouts
    return digest.hexdigest()


ENGINE_FINGERPRINT = _engine_fingerprint()


def _key(path: Path, sheet: str | None, header_row: int | None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return f"{CACHE_VERSION}|{ENGINE_VERSION}|{ENGINE_FINGERPRINT}|{sheet}|{header_row}|{digest.hexdigest()}"


def _files(cache_dir: Path, key: str) -> tuple[Path, Path]:
    stem = "ingest-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{stem}.parquet", cache_dir / f"{stem}.json"


def load(cache_dir: Path | None, path: Path, sheet: str | None, header_row: int | None,
         display_name: str | None) -> tuple[IngestResult, DatasetProfile] | None:
    """The cached table and its before-profile, or None. Needs the resolved sheet and header row."""
    if cache_dir is None or header_row is None:
        return None
    key = _key(path, sheet, header_row)
    parquet, meta_file = _files(Path(cache_dir), key)
    if not (parquet.exists() and meta_file.exists()):
        return None
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    if meta.get("key") != key:
        return None
    source = SourceInfo.model_validate(meta["source"]).model_copy(
        update={"filename": display_name or Path(path).name})
    before = DatasetProfile.model_validate(meta["before"]).model_copy(update={"source": source})
    loaded = IngestResult(df=pl.read_parquet(parquet), source=source, source_names=meta["source_names"])
    return loaded, before


def store(cache_dir: Path | None, path: Path, loaded: IngestResult, before: DatasetProfile) -> None:
    """Save the parsed table (all text) and its before-profile, keyed by the resolved sheet/header.

    Safe when another job stores the same entry at the same time: every writer uses its own
    temporary names and renames atomically, and the content for one key is identical. A cache
    write error is logged and ignored, because the cache is only a speed-up.
    """
    if cache_dir is None:
        return
    tmps: list[Path] = []
    try:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = _key(path, loaded.source.sheet, loaded.source.header_row)
        parquet, meta_file = _files(cache_dir, key)
        unique = uuid.uuid4().hex
        tmps = [parquet.with_name(f"{parquet.name}.{unique}.tmp"), meta_file.with_name(f"{meta_file.name}.{unique}.tmp")]
        loaded.df.write_parquet(tmps[0])
        os.replace(tmps[0], parquet)
        meta = {
            "key": key,
            "source": loaded.source.model_dump(mode="json"),
            "source_names": loaded.source_names,
            "before": before.model_copy(update={"proposals": []}).model_dump(mode="json"),
        }
        tmps[1].write_text(json.dumps(meta), encoding="utf-8")
        os.replace(tmps[1], meta_file)
    except Exception:
        log.warning("could not write the read-once cache", exc_info=True)
    finally:
        for tmp in tmps:
            tmp.unlink(missing_ok=True)
