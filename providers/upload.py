"""Images uploaded to POST /api/send-image (e.g. from the "Send to Frame TV" Apple Shortcut).

Not a catalogue you can search: an artwork comes into being when its bytes are
uploaded, keyed by a hash of those bytes, so sending the same image twice reuses
the same library entry (and the same TV upload). There's no remote copy to fetch
again, so originals live in UPLOADS_DIR rather than the evictable caches.
"""
import hashlib
import io
import json
import re

import pillow_heif
from PIL import Image, ImageOps

import config
from cache import thumb_cache

from .base import Artwork, SearchResult

pillow_heif.register_heif_opener()  # iPhone photos are usually HEIC

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_TITLE = "Uploaded image"
_ID = re.compile(r"[0-9a-f]{32}")


def _validate(data: bytes) -> None:
    """Decode the whole image, so a truncated file fails here and not on its way to the TV."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError("That image has too many pixels.")
            img.load()
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"That isn't a usable image ({e}).") from e


class UploadProvider:
    name = "upload"
    label = "Uploads"
    browsable = False  # nothing to search, so it stays out of the source picker

    def _paths(self, art_id: str):
        if not _ID.fullmatch(art_id):
            raise KeyError(art_id)
        return config.UPLOADS_DIR / f"{art_id}.img", config.UPLOADS_DIR / f"{art_id}.json"

    def save(self, data: bytes, title: str | None = None) -> Artwork:
        """Validate and store an upload. Idempotent per image: a re-send keeps the
        entry, though a title given later replaces the existing one."""
        _validate(data)
        art_id = hashlib.sha256(data).hexdigest()[:32]
        img_path, meta_path = self._paths(art_id)
        if not img_path.exists():
            tmp = img_path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(img_path)
        if title or not meta_path.exists():
            meta_path.write_text(json.dumps({"title": title or DEFAULT_TITLE}))
        return self.get(art_id)

    # -- Provider interface ------------------------------------------------

    def get(self, art_id: str) -> Artwork:
        _, meta_path = self._paths(art_id)
        try:
            meta = json.loads(meta_path.read_text())
        except FileNotFoundError:
            raise KeyError(art_id)
        return Artwork(
            id=art_id,
            title=meta["title"],
            artist="Uploaded",
            thumbnail_url=f"/img/{self.name}/{art_id}",
            preview_url=f"/img/{self.name}/{art_id}",
            source=self.name,
        )

    def search(self, query: str, page: int = 1, per_page: int = 24, filters: dict | None = None) -> SearchResult:
        return SearchResult(items=[], total=0)

    def get_full_image(self, art_id: str) -> tuple[bytes, str]:
        img_path, _ = self._paths(art_id)
        try:
            data = img_path.read_bytes()
        except FileNotFoundError:
            raise KeyError(art_id)
        with Image.open(io.BytesIO(data)) as img:
            ctype = Image.MIME.get(img.format, "application/octet-stream")
        return data, ctype

    def get_thumbnail(self, art_id: str) -> bytes:
        key = f"upload_{art_id}.jpg"
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
