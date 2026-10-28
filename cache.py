"""Persistent caches so each remote resource is fetched from a museum at most once (per TTL)."""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import config


class JsonCache:
    """key -> JSON value with fetch time, in SQLite. Expired entries are kept so they can serve as stale fallback."""

    def __init__(self, path: Path):
        self.path = path
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS json_cache (key TEXT PRIMARY KEY, body TEXT NOT NULL, ts REAL NOT NULL)")

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def get(self, key: str, ttl: float):
        """Return (value, fresh). (None, False) if absent."""
        c = self._conn()
        try:
            row = c.execute("SELECT body, ts FROM json_cache WHERE key=?", (key,)).fetchone()
        finally:
            c.close()
        if not row:
            return None, False
        return json.loads(row[0]), (time.time() - row[1]) < ttl

    def put(self, key: str, value) -> None:
        c = self._conn()
        try:
            with c:
                c.execute("INSERT OR REPLACE INTO json_cache VALUES (?,?,?)", (key, json.dumps(value), time.time()))
        finally:
            c.close()


class FileCache:
    """Blob cache on disk with a total size cap; least-recently-used files are evicted."""

    def __init__(self, root: Path, max_bytes: int):
        self.root, self.max_bytes = root, max_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, key: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
        return self.root / safe

    def get(self, key: str) -> bytes | None:
        p = self._path(key)
        try:
            data = p.read_bytes()
            os.utime(p)  # mark recently used
            return data
        except FileNotFoundError:
            return None

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        tmp = p.with_suffix(p.suffix + f".{threading.get_ident()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(p)  # atomic: readers never see a partial file
        self._evict()

    def _evict(self) -> None:
        with self._lock:
            files = [(f, f.stat()) for f in self.root.iterdir() if f.is_file() and not f.name.endswith(".tmp")]
            total = sum(st.st_size for _, st in files)
            for f, st in sorted(files, key=lambda x: x[1].st_mtime):
                if total <= self.max_bytes:
                    break
                f.unlink(missing_ok=True)
                total -= st.st_size


json_cache = JsonCache(config.CACHE_DIR / "api.db")
thumb_cache = FileCache(config.CACHE_DIR / "thumbs", config.CACHE_THUMBS_MB * 1024 * 1024)
full_cache = FileCache(config.CACHE_DIR / "full", config.CACHE_FULL_MB * 1024 * 1024)
