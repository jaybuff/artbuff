import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import httpx

import config
from cache import full_cache, json_cache, thumb_cache

from .base import Artwork, SearchResult

API = "https://collectionapi.metmuseum.org/public/collection/v1"
SEARCH_API = "https://collectionapi.metmuseum.org/public/collection/v1.1"

log = logging.getLogger("artbuff.met")

# The Met asks for <= 80 req/s and its CDN (Imperva) answers bursty clients with 403/429.
# Every outbound request goes through RateLimiter (config.MET_MAX_RPS, never above 80);
# a global cap on in-flight requests and a shared cooldown after any 403/429 keep us gentle on
# top of that (the CDN blocks on concurrency/bursts well before 80 rps, and retrying during a
# block just extends it).
MAX_PARALLEL = 4
COOLDOWN_STEPS = (3, 8, 20)  # seconds everyone pauses after the 1st, 2nd, 3rd consecutive block
RETRY_STATUSES = {500, 502, 503, 504}

OBJECT_TTL = 30 * 86400  # object metadata rarely changes
SEARCH_TTL = 7 * 86400
OBJECT_FIELDS = (
    "objectID", "title", "artistDisplayName", "culture", "primaryImage", "primaryImageSmall",
    "objectDate", "medium", "objectURL", "isPublicDomain",
    "department", "period", "classification", "objectBeginDate", "objectEndDate", "tags",
)
DEPARTMENTS_TTL = 30 * 86400

# Hand-picked starting points. Departments are named (ids are looked up from the Met's own list).
# URL params: q, dept (name here, id in the URL), from/to (years), tags (match tag terms), artist.
PRESETS = [
    {"label": "Dutch still life", "q": "still life", "dept": "European Paintings", "from": 1600, "to": 1750},
    {"label": "Impressionist landscapes", "q": "landscape", "dept": "European Paintings", "from": 1860, "to": 1910},
    {"label": "Japanese woodblock prints", "q": "woodblock", "dept": "Asian Art"},
    {"label": "Hokusai", "q": "Hokusai", "artist": 1},
    {"label": "Seascapes", "q": "Seascapes", "tags": 1},
    {"label": "Moonlit nights", "q": "moonlight"},
    {"label": "Winter scenes", "q": "Winter", "tags": 1},
    {"label": "Cats", "q": "Cats", "tags": 1},
    {"label": "European portraits", "q": "portrait", "dept": "European Paintings"},
    {"label": "Ancient Egypt", "dept": "Egyptian Art"},
]
ERAS = [
    {"label": "Ancient", "from": -3000, "to": 500},
    {"label": "Medieval", "from": 500, "to": 1400},
    {"label": "Renaissance", "from": 1400, "to": 1600},
    {"label": "Baroque", "from": 1600, "to": 1750},
    {"label": "1750–1900", "from": 1750, "to": 1900},
    {"label": "Modern", "from": 1900, "to": 2026},
]


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _slim(o: dict) -> dict:
    """Keep only the object fields we use; tags reduced to their terms."""
    out = {k: o.get(k) for k in OBJECT_FIELDS}
    out["tags"] = [t.get("term") for t in (o.get("tags") or []) if t.get("term")]
    return out


class RateLimiter:
    """Sliding window: at most `limit` request starts in any 1-second span, across all threads."""

    def __init__(self, limit: int):
        self.limit = limit
        self._starts: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._starts and now - self._starts[0] >= 1.0:
                    self._starts.popleft()
                if len(self._starts) < self.limit:
                    self._starts.append(now)
                    return
                wait = 1.0 - (now - self._starts[0])
            time.sleep(max(wait, 0.001))

    def recent(self, seconds: float) -> int:
        with self._lock:
            now = time.monotonic()
            return sum(1 for t in self._starts if now - t < seconds)


class MetProvider:
    name = "met"
    label = "The Met"

    def __init__(self):
        self.client = httpx.Client(
            timeout=30,
            headers={"User-Agent": "ArtBuff/0.1 (personal home project)"},
            follow_redirects=True,
        )
        self.limiter = RateLimiter(config.MET_MAX_RPS)
        self._slots = threading.BoundedSemaphore(MAX_PARALLEL)  # in-flight requests, all callers
        self._cooldown_until = 0.0
        self._blocks = 0
        self._tl = threading.local()  # .bg = True while the cache warmer is making requests
        self._last_fg = 0.0
        self.requests = 0  # outbound requests since startup (retries included)
        self.peak_rps = 0  # most request starts seen in any 1-second window

    def _get(self, url: str, **kw) -> httpx.Response:
        """GET with global concurrency cap, rate limit, and a shared cooldown when throttled."""
        if not getattr(self._tl, "bg", False):
            self._last_fg = time.monotonic()  # a person is browsing; the warmer yields
        for attempt in range(len(COOLDOWN_STEPS) + 1):
            while (wait := self._cooldown_until - time.monotonic()) > 0:
                time.sleep(wait)
            with self._slots:
                self.limiter.acquire()
                self.requests += 1
                self.peak_rps = max(self.peak_rps, self.limiter.recent(1.0))
                t0 = time.monotonic()
                r = self.client.get(url, **kw)
            log.info("MET GET [%s] %s -> %s (%.0f ms, attempt %d)", threading.current_thread().name, url, r.status_code, (time.monotonic() - t0) * 1000, attempt + 1)
            if r.status_code in (403, 429):
                self._blocks += 1
                try:
                    pause = float(r.headers.get("Retry-After", ""))
                except ValueError:
                    pause = COOLDOWN_STEPS[min(attempt, len(COOLDOWN_STEPS) - 1)]
                self._cooldown_until = max(self._cooldown_until, time.monotonic() + pause)
                log.warning("MET throttled (%s); pausing all Met requests for %.0fs", r.status_code, pause)
            elif r.status_code in RETRY_STATUSES:
                time.sleep(0.75 * 2**attempt)
            else:
                return r
        return r

    def foreground_active(self, window: float) -> bool:
        return time.monotonic() - self._last_fg < window

    def cooling_down(self) -> bool:
        return time.monotonic() < self._cooldown_until

    def warm_item(self, art_id: str) -> bool:
        """Ensure this item's details and thumbnail are cached. True if it needed the network."""
        try:
            art = self.peek(art_id)
        except KeyError:
            return False  # known unusable
        needs_thumb = not thumb_cache.exists(f"met_{art_id}.jpg")
        if art is not None and not needs_thumb:
            return False
        self._tl.bg = True
        try:
            if art is None:
                art = self._fetch(art_id)
                if art is None or not art.thumbnail_url:
                    return True
            if needs_thumb:
                self.get_thumbnail(art_id)
            return True
        finally:
            self._tl.bg = False

    def stats(self) -> dict:
        return {
            "limit_rps": config.MET_MAX_RPS,
            "requests_since_start": self.requests,
            "peak_rps_since_start": self.peak_rps,
            "max_in_flight": MAX_PARALLEL,
            "throttle_responses": self._blocks,
            "requests_last_1s": self.limiter.recent(1.0),
            "log_file": str(config.LOG_FILE),
        }

    def _cached_json(self, key: str, ttl: float, url: str, **kw) -> dict | None:
        """Fresh cache hit, else fetch; on fetch failure fall back to a stale entry if we have one."""
        value, fresh = json_cache.get(key, ttl)
        if fresh:
            return value
        try:
            r = self._get(url, **kw)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            value_new = r.json()
            if "objectID" in value_new:  # object record: keep only the fields we use
                value_new = _slim(value_new)
        except (httpx.HTTPError, ValueError):
            if value is not None:
                return value
            raise
        json_cache.put(key, value_new)
        return value_new

    def _to_artwork(self, o: dict) -> Artwork:
        small = o.get("primaryImageSmall") or o.get("primaryImage") or ""
        return Artwork(
            id=str(o["objectID"]),
            title=o.get("title") or "Untitled",
            artist=o.get("artistDisplayName") or o.get("culture") or "Unknown",
            thumbnail_url=small,
            preview_url=small,
            source=self.name,
            date=o.get("objectDate") or "",
            medium=o.get("medium") or "",
            page_url=o.get("objectURL") or "",
            extra={
                "full_url": o.get("primaryImage") or small,
                "department": o.get("department") or "",
                "culture": o.get("culture") or "",
                "period": o.get("period") or "",
                "classification": o.get("classification") or "",
                "begin": o.get("objectBeginDate"),
                "end": o.get("objectEndDate"),
                "tags": o.get("tags") or [],
            },
        )

    def _fetch(self, art_id: str) -> Artwork | None:
        """Artwork for an id, or None if missing / not public domain (we only show and cache Open Access).
        Network failures raise httpx.HTTPError, so callers can tell "gone" from "try again"."""
        key, url = f"met:obj:{art_id}", f"{API}/objects/{art_id}"
        o = self._cached_json(key, OBJECT_TTL, url)
        if o and "department" not in o:  # cached before we stored discovery fields: refresh once
            o = self._cached_json(key, 0, url)
        if not o or not o.get("isPublicDomain"):
            return None
        return self._to_artwork(o)

    def _fetch_quiet(self, art_id: str) -> Artwork | None:
        try:
            return self._fetch(art_id)
        except (httpx.HTTPError, ValueError):
            return None

    def peek(self, art_id: str) -> Artwork | None:
        """Artwork from the local cache only (never touches the network).
        None = not cached yet; KeyError = cached and known to be unusable (not Open Access / no image)."""
        o, _ = json_cache.get(f"met:obj:{art_id}", float("inf"))
        if not o or "department" not in o:
            return None
        if not o.get("isPublicDomain") or not (o.get("primaryImageSmall") or o.get("primaryImage")):
            raise KeyError(art_id)
        return self._to_artwork(o)

    @staticmethod
    def _search_params(query: str, filters: dict | None) -> dict:
        f = filters or {}
        params = {"q": query or "*", "hasImages": "true", "isPublicDomain": "true"}
        if not query and not f.get("all"):
            params["isHighlight"] = "true"  # browsing: the best-known works, unless asked for everything
        if (dept := _int(f.get("dept"))) is not None:
            params["departmentId"] = dept
        lo, hi = _int(f.get("from")), _int(f.get("to"))
        if lo is not None or hi is not None:  # the API wants both ends
            params["dateBegin"] = lo if lo is not None else -10000
            params["dateEnd"] = hi if hi is not None else 2100
        if query and f.get("tags"):
            params["tags"] = "true"
        elif query and f.get("artist"):
            params["artistOrCulture"] = "true"
        return params

    def search_ids(
        self, query: str, page: int = 1, per_page: int = 24, filters: dict | None = None
    ) -> tuple[list[str], int]:
        """One search call: just the matching object ids (and the total). No per-object lookups."""
        params = self._search_params(query, filters)
        params["offset"] = (page - 1) * per_page
        params["limit"] = per_page
        key = "met:search:" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        data = self._cached_json(key, SEARCH_TTL, f"{SEARCH_API}/search", params=params) or {}
        return [str(i) for i in (data.get("objectIDs") or [])], data.get("total") or 0

    def search(self, query: str, page: int = 1, per_page: int = 24, filters: dict | None = None) -> SearchResult:
        ids, total = self.search_ids(query, page, per_page, filters)
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
            arts = list(pool.map(self._fetch_quiet, ids))
        return SearchResult(items=[a for a in arts if a and a.thumbnail_url], total=total)

    def _departments(self) -> list[dict]:
        try:
            data = self._cached_json("met:departments", DEPARTMENTS_TTL, f"{API}/departments") or {}
        except (httpx.HTTPError, ValueError):
            return []
        return [{"id": d["departmentId"], "name": d["displayName"]} for d in data.get("departments", [])]

    def discovery(self) -> dict:
        depts = self._departments()
        ids = {d["name"]: d["id"] for d in depts}
        presets = []
        for p in PRESETS:
            params = {k: v for k, v in p.items() if k not in ("label", "dept")}
            if "dept" in p:
                if p["dept"] not in ids:
                    continue  # the Met renamed it; skip rather than show a broken link
                params["dept"] = ids[p["dept"]]
            presets.append({"label": p["label"], "params": params})
        return {"presets": presets, "departments": depts, "eras": ERAS}

    def related(self, art: Artwork) -> list[dict]:
        e = art.extra
        out = []
        if art.artist and art.artist not in ("Unknown",) and art.artist != e.get("culture"):
            out.append({"label": f"More by {art.artist}", "params": {"q": art.artist, "artist": 1}})
        if e.get("culture"):
            out.append({"label": f"More from {e['culture']}", "params": {"q": e["culture"], "artist": 1}})
        ids = {d["name"]: d["id"] for d in self._departments()}
        if e.get("department") in ids:
            out.append({"label": f"More from {e['department']}", "params": {"dept": ids[e["department"]]}})
        b, en = e.get("begin"), e.get("end")
        if isinstance(b, int) and isinstance(en, int) and (b or en):
            mid = (b + en) // 2
            out.append({"label": f"Around {mid}" if mid > 0 else f"Around {-mid} BCE", "params": {"from": mid - 30, "to": mid + 30}})
        for tag in e.get("tags", [])[:8]:
            out.append({"label": tag, "params": {"q": tag, "tags": 1}, "kind": "tag"})
        return out

    def get(self, art_id: str) -> Artwork:
        art = self._fetch(art_id)
        if not art or not art.thumbnail_url:
            raise KeyError(art_id)
        return art

    def _download(self, url: str) -> tuple[bytes, str]:
        r = self._get(url, timeout=120)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "image/jpeg")

    def get_thumbnail(self, art_id: str) -> bytes:
        key = f"met_{art_id}.jpg"
        data = thumb_cache.get(key)
        if data is None:
            url = self.get(art_id).thumbnail_url
            data, _ = self._download(url)
            thumb_cache.put(key, data)
        return data

    def get_full_image(self, art_id: str) -> tuple[bytes, str]:
        key = f"met_{art_id}.img"
        data = full_cache.get(key)
        if data is not None:
            return data, "image/jpeg"
        art = self.get(art_id)
        url = art.extra.get("full_url") or art.thumbnail_url
        if not url:
            raise ValueError("No image available for this object")
        data, ctype = self._download(url)
        full_cache.put(key, data)
        return data, ctype
