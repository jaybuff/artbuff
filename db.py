import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    art_id TEXT NOT NULL,
    title TEXT, artist TEXT, thumbnail_url TEXT,
    tv_content_id TEXT,
    crop TEXT
);
CREATE TABLE IF NOT EXISTS favorites (
    source TEXT NOT NULL,
    art_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    title TEXT, artist TEXT, thumbnail_url TEXT,
    PRIMARY KEY (source, art_id)
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(history)")}
        if "crop" not in cols:
            c.execute("ALTER TABLE history ADD COLUMN crop TEXT")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_history(art, tv_content_id: str, crop: str | None = None):
    with conn() as c:
        c.execute(
            "INSERT INTO history (ts, source, art_id, title, artist, thumbnail_url, tv_content_id, crop)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (_now(), art.source, art.id, art.title, art.artist, art.thumbnail_url, tv_content_id, crop),
        )


def history(limit: int = 100):
    with conn() as c:
        return c.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def last_content_id(source: str, art_id: str, crop: str | None) -> str | None:
    """TV content id of the latest upload of this artwork with exactly this crop."""
    with conn() as c:
        row = c.execute(
            "SELECT tv_content_id FROM history WHERE source=? AND art_id=? AND tv_content_id IS NOT NULL AND crop IS ?"
            " ORDER BY id DESC LIMIT 1",
            (source, art_id, crop),
        ).fetchone()
    return row["tv_content_id"] if row else None


def our_content_ids() -> list[str]:
    """Distinct TV content ids ArtBuff uploaded, oldest first."""
    with conn() as c:
        rows = c.execute(
            "SELECT tv_content_id FROM history WHERE tv_content_id IS NOT NULL GROUP BY tv_content_id ORDER BY MAX(id)"
        ).fetchall()
    return [r["tv_content_id"] for r in rows]


def is_favorite(source: str, art_id: str) -> bool:
    with conn() as c:
        return c.execute("SELECT 1 FROM favorites WHERE source=? AND art_id=?", (source, art_id)).fetchone() is not None


def favorite_keys() -> set[tuple[str, str]]:
    with conn() as c:
        return {(r["source"], r["art_id"]) for r in c.execute("SELECT source, art_id FROM favorites")}


def toggle_favorite(art) -> bool:
    """Flip favorite state; return new state."""
    with conn() as c:
        cur = c.execute("DELETE FROM favorites WHERE source=? AND art_id=?", (art.source, art.id))
        if cur.rowcount:
            return False
        c.execute(
            "INSERT INTO favorites (source, art_id, ts, title, artist, thumbnail_url) VALUES (?,?,?,?,?,?)",
            (art.source, art.id, _now(), art.title, art.artist, art.thumbnail_url),
        )
        return True


def favorites():
    with conn() as c:
        return c.execute("SELECT * FROM favorites ORDER BY ts DESC").fetchall()
