import io
import logging
import logging.handlers
import math
import random
import threading
from types import SimpleNamespace
from urllib.parse import urlencode
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import db
import tv
import frames
from warmer import warmer
from imaging import format_view, parse_view, prepare_for_tv
from providers import DEFAULT_PROVIDER, PROVIDERS, get_provider
from providers.upload import MAX_UPLOAD_BYTES

PER_PAGE = 24
log = logging.getLogger("artbuff")


def setup_logging() -> None:
    """Log to stdout and to a rotating file (outbound museum requests are logged individually)."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_h = logging.handlers.RotatingFileHandler(config.LOG_FILE, maxBytes=5_000_000, backupCount=3)
    stream_h = logging.StreamHandler()
    for h in (file_h, stream_h):
        h.setFormatter(fmt)
    for name in ("artbuff", "uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = [file_h, stream_h]
        lg.setLevel(logging.INFO)
        lg.propagate = False


setup_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    warmer.start()
    threading.Thread(target=tv.learn_mac, daemon=True).start()  # a TV that's off shouldn't hold up startup
    yield


app = FastAPI(title="ArtBuff", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=config.BASE_DIR / "templates")


FILTER_KEYS = ("dept", "from", "to", "tags", "artist", "all")


def _page_ids(provider, q: str, page: int, shuffle: str, filters: dict, known: dict | None = None):
    """(ids, total) for one page of results.

    Providers with `search_ids` give ids only; otherwise full items come from `search` and are put in `known`.
    Shuffle visits result pages in a seeded random order (never repeating) and shuffles within a page."""
    known = known if known is not None else {}

    def fetch(p: int, n: int):
        if hasattr(provider, "search_ids"):
            return provider.search_ids(q, p, n, filters)
        r = provider.search(q, p, n, filters)
        known.update({a.id: a for a in r.items})
        return [a.id for a in r.items], r.total

    if not shuffle:
        return fetch(page, PER_PAGE)
    total = fetch(1, 1)[1]  # cached after the first call for a query
    pages = math.ceil(total / PER_PAGE)
    if not 1 <= page <= pages:
        return [], total
    order = list(range(1, pages + 1))
    random.Random(shuffle).shuffle(order)
    ids, _ = fetch(order[page - 1], PER_PAGE)
    random.Random(f"{shuffle}:{page}").shuffle(ids)
    return ids, total


def _page_cards(provider, q: str, page: int, shuffle: str, filters: dict):
    """Cards for one page, plus the total. Items whose details are already cached come back complete;
    the rest are placeholders the browser fills in as they scroll into view."""
    known: dict[str, object] = {}
    ids, total = _page_ids(provider, q, page, shuffle, filters, known)
    cards = []
    for i in ids:
        art = known.get(i)
        if art is None and hasattr(provider, "peek"):
            try:
                art = provider.peek(i)
            except KeyError:
                continue  # known not displayable
        cards.append(SimpleNamespace(id=i, source=provider.name, art=art))
    return cards, total


def _provider_or_404(source: str):
    try:
        return get_provider(source)
    except KeyError:
        raise HTTPException(404, "Unknown source")


@app.get("/")
def index(
    request: Request, q: str = "", page: int = 1, source: str = DEFAULT_PROVIDER, partial: int = 0, shuffle: str = ""
):
    if not tv.ip():  # first run: nothing can reach the TV until this is set
        return RedirectResponse("/tv", status_code=303)
    provider = _provider_or_404(source)
    page = max(page, 1)
    disc = provider.discovery() if hasattr(provider, "discovery") else None
    # Provider-specific filters are only honored for providers that offer discovery.
    filters = {}
    if disc:
        filters = {k: v for k in FILTER_KEYS if (v := request.query_params.get(k, "").strip())}
    qs = urlencode({"q": q.strip(), "source": source, "shuffle": shuffle, **filters})
    error, cards, total = None, [], 0
    try:
        cards, total = _page_cards(provider, q.strip(), page, shuffle, filters)
    except httpx.HTTPError as e:
        error = f"Couldn't reach {provider.label}: {e}"
    if cards:  # quietly prefetch this page's leftovers and the next few
        sig = (source, q.strip(), shuffle, tuple(sorted(filters.items())))
        warmer.submit(sig, page, provider, lambda p: _page_ids(provider, q.strip(), p, shuffle, filters)[0])
    if partial:  # infinite-scroll fragment: just the cards
        if error:
            raise HTTPException(502, error)
        return templates.TemplateResponse(
            request, "_cards.html", {"cards": cards, "favs": db.favorite_keys()}
        )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "q": q,
            "shuffle": shuffle,
            "disc": disc,
            "flt": filters,
            "qs": qs,
            "source": source,
            "providers": [p for p in PROVIDERS.values() if getattr(p, "browsable", True)],
            "cards": cards,
            "total": total,
            "page": page,
            "pages": math.ceil(total / PER_PAGE),
            "favs": db.favorite_keys(),
            "error": error,
        },
    )


@app.get("/img/{source}/{art_id}")
def thumb(source: str, art_id: str):
    """Locally cached preview image. Browsers keep it for a year (an id's image never changes)."""
    provider = _provider_or_404(source)
    try:
        data = provider.get_thumbnail(art_id)
    except KeyError:
        raise HTTPException(404, "Artwork not found")
    except httpx.HTTPError:
        raise HTTPException(502, "Upstream image unavailable")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


_frame_png_cache: dict[tuple[str, int], bytes] = {}


@app.get("/frames/{frame_id}.png")
def frame_png(frame_id: str, w: int = 1920):
    """Transparent-centered frame overlay for the live preview (same renderer as the TV output)."""
    if frame_id not in frames.FRAMES:
        raise HTTPException(404, "Unknown frame")
    w = min(max(w, 96), 1920)
    key = (frame_id, w)
    if key not in _frame_png_cache:
        buf = io.BytesIO()
        frames.render_frame(frame_id, (w, round(w * 9 / 16))).save(buf, "PNG")
        _frame_png_cache[key] = buf.getvalue()
    return Response(_frame_png_cache[key], media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/card/{source}/{art_id}")
def card(source: str, art_id: str):
    """Details for one grid card, loaded lazily as it scrolls into view. 404 = not displayable."""
    provider = _provider_or_404(source)
    try:
        art = provider.get(art_id)
    except KeyError:
        raise HTTPException(404, "Not available")
    except httpx.HTTPError:
        raise HTTPException(502, "Upstream unavailable")
    return {"title": art.title, "artist": art.artist, "fav": (source, art_id) in db.favorite_keys()}


@app.get("/art/{source}/{art_id}")
def detail(request: Request, source: str, art_id: str, crop: str = ""):
    provider = _provider_or_404(source)
    try:
        art = provider.get(art_id)
    except KeyError:
        raise HTTPException(404, "Artwork not found")
    except httpx.HTTPError:
        raise HTTPException(502, "The museum is unreachable or throttling right now; try again in a moment")
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "art": art,
            "fav": db.is_favorite(source, art_id),
            "frames": {k: {"label": v["label"], "ap": frames.aperture_fractions(k)} for k, v in frames.FRAMES.items()},
            "bg": config.LETTERBOX_COLOR,
            "related": provider.related(art) if hasattr(provider, "related") else [],
            "initial": format_view(parse_view(crop)) if parse_view(crop) else "",
        },
    )


@app.get("/history")
def history(request: Request):
    return templates.TemplateResponse(
        request, "history.html", {"rows": db.history(), "favs": db.favorite_keys()}
    )


@app.get("/favorites")
def favorites(request: Request):
    return templates.TemplateResponse(request, "favorites.html", {"rows": db.favorites()})


@app.get("/stats")
def stats():
    """Outbound request counters per provider, for checking we stay under the museum's rate limit."""
    out = {name: p.stats() for name, p in PROVIDERS.items() if hasattr(p, "stats")}
    out["warmer"] = warmer.stats()
    return out


@app.get("/tv")
def tv_page(request: Request):
    return templates.TemplateResponse(
        request,
        "tv.html",
        {"ip": tv.ip(), "port": config.TV_PORT, "paired": tv.is_paired(), "token_file": config.TV_TOKEN_FILE},
    )


@app.post("/api/tv-ip")
def api_tv_ip(ip: str = ""):
    try:
        tv.set_ip(ip)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True}


@app.post("/api/pair")
def api_pair():
    try:
        tv.pair()
    except tv.TVError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)
    return {"ok": True}


@app.post("/api/display/{source}/{art_id}")
def api_display(source: str, art_id: str, crop: str | None = None):
    provider = _provider_or_404(source)
    parsed = parse_view(crop)
    crop = format_view(parsed) if parsed else None  # canonical form, used as the history/reuse key
    try:
        art = provider.get(art_id)

        def make_jpeg() -> bytes:
            raw, _ = provider.get_full_image(art_id)
            return prepare_for_tv(raw, config.LETTERBOX_COLOR, parsed)

        content_id = tv.display(make_jpeg, db.last_content_id(source, art_id, crop), db.our_content_ids())
        db.add_history(art, content_id, crop)
    except KeyError:
        raise HTTPException(404, "Artwork not found")
    except tv.TVError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)
    except (httpx.HTTPError, ValueError, OSError) as e:
        return JSONResponse({"ok": False, "error": f"Image fetch/processing failed: {e}"}, status_code=502)
    return {"ok": True}


async def _read_upload(request: Request) -> bytes | None:
    """The request body, or None once it passes MAX_UPLOAD_BYTES (so an oversized upload is never held in memory)."""
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/api/send-image")
def api_send_image(title: str = "", data: bytes | None = Depends(_read_upload)):
    """Save the image in the request body to the library and display it. If the TV fails, the
    image stays saved and lands in history. `message` is meant to be shown to the person sending."""

    def fail(status: int, message: str, **extra):
        return JSONResponse({"ok": False, "message": message, **extra}, status_code=status)

    if data is None:
        return fail(413, f"That image is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not data:
        return fail(400, "No image was sent.")
    provider = get_provider("upload")
    try:
        art = provider.save(data, title.strip() or None)
    except ValueError as e:
        return fail(400, str(e))
    log.info("Upload %s: %d bytes", art.id, len(data))

    def make_jpeg() -> bytes:
        return prepare_for_tv(data, config.LETTERBOX_COLOR, None)

    try:
        content_id = tv.display(make_jpeg, db.last_content_id("upload", art.id, None), db.our_content_ids())
    except tv.TVError as e:
        db.add_history(art, None, None)
        return fail(502, f"Saved to ArtBuff, but the TV didn't take it: {e}", saved=True, id=art.id)
    db.add_history(art, content_id, None)
    return {"ok": True, "message": "Sent to the Frame TV.", "id": art.id, "content_id": content_id}


@app.post("/api/favorite/{source}/{art_id}")
def api_favorite(source: str, art_id: str):
    provider = _provider_or_404(source)
    try:
        art = provider.get(art_id)
    except KeyError:
        raise HTTPException(404, "Artwork not found")
    return {"favorite": db.toggle_favorite(art)}


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_config=None)
