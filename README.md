# ArtBuff

Browse public-domain art from museum collections and push it to a Samsung Frame TV's Art Mode over your LAN. FastAPI + Jinja2 + a little vanilla JS; state lives in one SQLite file.

## Install

Needs Python 3.11+. [uv](https://docs.astral.sh/uv/) provides both the Python interpreter and the virtual environment — no Homebrew (or system Python) needed:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh   # install uv (once)
cd artbuff
uv python install 3.13        # fetch a standalone Python 3.13 (once)
uv venv --python 3.13         # creates .venv
uv pip install -r requirements.txt
cp .env.example .env     # then edit TV_IP etc.
```

To update dependencies later, re-run `uv pip install -r requirements.txt`.

## Find the TV's IP

TV: Settings → General → Network → Network Status → IP Settings. Or check your router's device list. Give the TV a DHCP reservation so the address doesn't change, then set `TV_IP` in `.env`.

## First-run pairing

1. Make sure the TV is on the same network and powered (standby is fine).
2. Start the server, open **TV** in the nav, and click **Pair with TV**. (Your first "Display on TV" also triggers it.)
3. The TV shows an **Allow / Deny** prompt. Press **Allow** with the remote within about a minute.
4. The token is saved to `TV_TOKEN_FILE` (default `data/tv-token.txt`). Later runs reuse it, so the prompt won't reappear. Keep that file; if you delete it, you'll be asked again.

## Run

```sh
.venv/bin/python app.py
```

Open http://localhost:8420. From another device on your LAN use `http://<mac-ip-or-hostname>.local:8420` (the server binds `0.0.0.0`; allow incoming connections if macOS asks). There's no auth, so keep this on your home network. Don't forward the port.

Config is in `.env`: `TV_IP`, `TV_PORT` (8002), `TV_TOKEN_FILE`, `HOST`, `PORT` (8420), `LETTERBOX_COLOR` (`black`, or e.g. `#f5f1e8`), `MAX_TV_UPLOADS` (20; oldest ArtBuff uploads are deleted from the TV past this; other art is never touched).

## How display works

Full-res image is downloaded, scaled to fit inside 3840×2160 (no stretching or cropping), centered on the letterbox color, saved as JPEG (quality 92, stepping down only if over 50 MB), uploaded with no matte, and selected. Art Mode is switched on first if needed. Re-displaying something already on the TV skips the upload.

## Discovery (Met only)

Shown only for providers that implement the optional `discovery()` / `related()` hooks (see `providers/base.py`); a new museum gets none of this unless it opts in.

- **Start here:** one-click presets (Dutch still life, Impressionist landscapes, Hokusai, Cats…). Edit the `PRESETS` list in `providers/met.py`.
- **Department** and **era** filters work with or without a search term. Without one you see the Met's highlights; tick *Include non-highlights* for everything.
- **🎲 Shuffle** visits the current results (filters included) in a seeded random order, so scrolling never repeats.
- **Explore more** on each artwork: more by the artist, from the culture or department, from the same era, and clickable subject tags.

The Met's search sometimes matches records whose full data isn't Open Access or has no image; those are never shown or cached, so a page may have fewer cards than matches.

## Background warmer

While you browse, one low-priority thread quietly caches details and thumbnails for the rest of the current page and the next `WARM_PAGES` (default 2), at about one item per `WARM_INTERVAL` seconds (default 1). It waits while you're actively loading things, stops queued work when you start a different search, and backs off if the Met throttles. Set `WARM_PAGES=0` to turn it off. Progress is at `/stats`, and its activity is logged to `data/artbuff.log` (`artbuff.warm`).

## Caching and the Met's terms

Everything fetched from a museum is cached under `CACHE_DIR` (default `data/cache`), so each item is requested at most once:

- **API responses** (`api.db`, SQLite): search pages for 7 days, object records for 30. If the Met is unreachable, expired entries are used as a fallback.
- **Thumbnails** (`thumbs/`) are served by the app at `/img/<source>/<id>`, and browsers keep them for a year. Cap: `CACHE_THUMBS_MB` (1024).
- **Full-resolution images** (`full/`) are kept so re-cropping or re-displaying doesn't re-download. Cap: `CACHE_FULL_MB` (2048). The least recently used files are evicted first.

Delete `data/cache` any time to start fresh.

Terms: the Met's API page says its Open Access data is CC0 ("unrestricted commercial and noncommercial use") and asks only that you keep requests under 80/second, with no key required. ArtBuff stays far below that (at most 4 parallel requests, about 16/s, with backoff on throttling), sends an honest `User-Agent`, and only shows or caches objects flagged `isPublicDomain`. The full terms are at https://www.metmuseum.org/information/terms-and-conditions. Skim them if you plan to do anything beyond personal use.

## Auto-start on login (launchd)

```sh
mkdir -p data
cp com.artbuff.plist.example ~/Library/LaunchAgents/com.artbuff.plist   # fix paths if you moved the project
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.artbuff.plist
# stop: launchctl bootout gui/$(id -u)/com.artbuff
```

## Adding another art source

Add `providers/<name>.py` with a class implementing the `Provider` protocol in `providers/base.py` (`name`, `label`, `search`, `get`, `get_full_image`), then register an instance in `PROVIDERS` in `providers/__init__.py`. The UI shows a source picker automatically once there's more than one; history and favorites key on `(provider name, id)`.

Note: the Met retired its old `/v1/search` on 2026-10-01; `providers/met.py` uses the paginated `/v1.1/search`.
