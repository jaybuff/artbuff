"""Images sent from the browser ("Send to Frame TV" Safari extension).

Not a catalogue you can search: an artwork comes into being when its URL is
registered (POST /api/send-image), keyed by a hash of the URL, so sending the
same image twice reuses the same library entry (and the same TV upload).
Downloads go through the shared file caches, so /img, history, favorites and
/api/display treat these exactly like museum pieces.
"""
import hashlib
import io
import logging
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image, ImageOps

from cache import full_cache, json_cache, thumb_cache

from .base import Artwork, SearchResult

log = logging.getLogger("artbuff.web")

# Some hosts refuse non-browser clients or images hotlinked from nowhere; a
# Safari UA plus the page the image was found on as Referer gets past most of it.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # same ceiling imaging.py puts on TV output
MAX_PIXELS = 500_000_000  # matches imaging.Image.MAX_IMAGE_PIXELS (decompression-bomb guard)
META_TTL = float("inf")  # a sent URL's metadata never expires


def art_id_for(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


class WebProvider:
    name = "web"
    label = "Web"

    def __init__(self):
        self.client = httpx.Client(
            timeout=60,
            headers={"User-Agent": BROWSER_UA},
            follow_redirects=True,
        )

    # -- registration -----------------------------------------------------

    def register(self, url: str, title: str | None = None, page_url: str | None = None) -> Artwork:
        """Record a sent URL and return its Artwork. Idempotent per URL: a
        re-send keeps the entry (a title given later replaces a derived one)."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Not an http(s) image URL: {url!r}")
        art_id = art_id_for(url)
        key = f"web:obj:{art_id}"
        meta, _ = json_cache.get(key, META_TTL)
        if meta is None:
            meta = {"url": url, "title": title or self._title_from_url(url), "page_url": page_url or ""}
            json_cache.put(key, meta)
        elif title and title != meta.get("title"):
            meta = {**meta, "title": title, "page_url": page_url or meta.get("page_url", "")}
            json_cache.put(key, meta)
        return self._to_artwork(art_id, meta)

    @staticmethod
    def _title_from_url(url: str) -> str:
        name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
        stem = name.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").strip()
        return stem or "Web image"

    # -- Provider interface ------------------------------------------------

    def _meta(self, art_id: str) -> dict:
        meta, _ = json_cache.get(f"web:obj:{art_id}", META_TTL)
        if meta is None:
            raise KeyError(art_id)
        return meta

    def _to_artwork(self, art_id: str, meta: dict) -> Artwork:
        url = meta["url"]
        host = urlparse(meta.get("page_url") or url).netloc
        return Artwork(
            id=art_id,
            title=meta.get("title") or "Web image",
            artist=host or "Web",
            thumbnail_url=url,
            preview_url=url,
            source=self.name,
            page_url=meta.get("page_url") or "",
            extra={"full_url": url},
        )

    def get(self, art_id: str) -> Artwork:
        return self._to_artwork(art_id, self._meta(art_id))

    def search(self, query: str, page: int = 1, per_page: int = 24, filters: dict | None = None) -> SearchResult:
        return SearchResult(items=[], total=0)  # nothing to browse; items arrive via send-image

    # -- downloads ----------------------------------------------------------

    def _download(self, art_id: str, meta: dict) -> bytes:
        """Fetch the image bytes, validating type and size. Raises ValueError
        with a user-facing message for anything that isn't a usable image."""
        url = meta["url"]
        page_url = meta.get("page_url") or ""
        origin = urlparse(page_url) if page_url else urlparse(url)
        headers = {"Referer": page_url or f"{origin.scheme}://{origin.netloc}/"}
        chunks, total = [], 0
        with self.client.stream("GET", url, headers=headers) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype and not ctype.startswith("image/"):
                raise ValueError(f"That URL returned {ctype}, not an image.")
            declared = r.headers.get("content-length")
            if declared and int(declared) > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"That image is too large (over {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB).")
            for chunk in r.iter_bytes(256 * 1024):
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"That image is too large (over {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB).")
                chunks.append(chunk)
        data = b"".join(chunks)
        try:
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
            with Image.open(io.BytesIO(data)) as img:
                if img.width * img.height > MAX_PIXELS:
                    raise ValueError("That image is implausibly large.")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"That URL didn't return a usable image ({e}).") from e
        log.info("WEB GET %s -> %d bytes", url, total)
        return data

    def get_full_image(self, art_id: str) -> tuple[bytes, str]:
        key = f"web_{art_id}.img"
        data = full_cache.get(key)
        if data is None:
            data = self._download(art_id, self._meta(art_id))
            full_cache.put(key, data)
        with Image.open(io.BytesIO(data)) as img:
            ctype = Image.MIME.get(img.format, "image/jpeg")
        return data, ctype

    def get_thumbnail(self, art_id: str) -> bytes:
        key = f"web_{art_id}.jpg"
        data = thumb_cache.get(key)
        if data is None:
            raw, _ = self.get_full_image(art_id)
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
            img.thumbnail((800, 800), Image.LANCZOS)
            out = io.BytesIO()
            img.save(out, "JPEG", quality=85)
            data = out.getvalue()
            thumb_cache.put(key, data)
        return data
