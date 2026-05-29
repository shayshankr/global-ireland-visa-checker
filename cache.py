"""
Disk-based cache with ETag/Last-Modified checking.

Flow:
  1. Check if disk cache exists and is fresh (< MAX_AGE_HOURS)
  2. If stale or missing → HEAD request to check ETag/Last-Modified
  3. If ETag unchanged → refresh timestamp, return cached data (no re-download)
  4. If ETag changed or no ETag → download fresh data, save to disk
"""

import json
import pickle
import hashlib
import requests
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

CACHE_DIR = Path(__file__).parent / ".cache_v2"
CACHE_DIR.mkdir(exist_ok=True)

MAX_AGE_HOURS = 24  # Only re-check server after this many hours

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )
}


def _cache_key(name: str) -> str:
    return hashlib.md5(name.encode()).hexdigest()[:12]


def _meta_path(name: str) -> Path:
    return CACHE_DIR / f"{_cache_key(name)}.meta.json"


def _data_path(name: str) -> Path:
    return CACHE_DIR / f"{_cache_key(name)}.pkl"


def load_from_disk(name: str) -> tuple[pd.DataFrame | None, dict | None]:
    """Load cached DataFrame and metadata from disk. Returns (df, meta) or (None, None)."""
    meta_file = _meta_path(name)
    data_file = _data_path(name)

    if not meta_file.exists() or not data_file.exists():
        return None, None

    try:
        meta = json.loads(meta_file.read_text())
        df = pickle.loads(data_file.read_bytes())
        return df, meta
    except Exception:
        return None, None


def save_to_disk(name: str, df: pd.DataFrame, file_url: str, etag: str | None,
                 last_modified: str | None, reports: list[str]) -> None:
    """Persist DataFrame and metadata to disk."""
    meta = {
        "name": name,
        "file_url": file_url,
        "etag": etag,
        "last_modified": last_modified,
        "reports": reports,
        "cached_at": datetime.utcnow().isoformat(),
    }
    _meta_path(name).write_text(json.dumps(meta, indent=2))
    _data_path(name).write_bytes(pickle.dumps(df))


def is_cache_fresh(meta: dict) -> bool:
    """True if cache is younger than MAX_AGE_HOURS."""
    try:
        cached_at = datetime.fromisoformat(meta["cached_at"])
        return datetime.utcnow() - cached_at < timedelta(hours=MAX_AGE_HOURS)
    except Exception:
        return False


def check_etag(file_url: str) -> tuple[str | None, str | None]:
    """Send HEAD request, return (etag, last_modified)."""
    try:
        r = requests.head(file_url, headers=HEADERS, timeout=10, allow_redirects=True)
        etag = r.headers.get("ETag")
        last_modified = r.headers.get("Last-Modified")
        return etag, last_modified
    except Exception:
        return None, None


def etag_unchanged(meta: dict, new_etag: str | None, new_last_modified: str | None) -> bool:
    """True if the server file hasn't changed since last fetch."""
    if new_etag and meta.get("etag"):
        return new_etag == meta["etag"]
    if new_last_modified and meta.get("last_modified"):
        return new_last_modified == meta["last_modified"]
    return False  # Can't confirm — re-fetch to be safe
