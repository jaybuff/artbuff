# ArtBuff — "Send to Frame TV" Safari Extension

Right-click (or control-click) any image in Safari → **Send to Frame TV** → the
image appears on the Samsung Frame via ArtBuff.

This folder is plain WebExtension source (Manifest V3). Safari can't load it
as-is — it has to be wrapped in a macOS app by Xcode (steps below). The same
source also works unpacked in Chrome/Edge/Firefox for testing the logic.

## Architecture

```
Safari page ──right-click image──▶ extension (background.js)
                                       │  POST {base}/api/send-image
                                       │  {"url", "title", "page_url"}
                                       ▼
                              ArtBuff server (Mac, :8420)
                                       │  downloads the image itself
                                       │  (browser UA + Referer = the page),
                                       │  validates type/size, caches it as
                                       │  source "web", prepare_for_tv(),
                                       ▼
                              tv.display() ──▶ Samsung Frame (Art Mode)
```

Design points:

- **The extension never downloads the image.** It sends only the image URL and
  the page URL. The ArtBuff server fetches server-side with a Safari
  User-Agent and the page as `Referer`, which is what gets past most hotlink
  protection — and it means image-host CORS never applies to the extension.
- **Server side** (in the artbuff repo): `POST /api/send-image` in `app.py`,
  backed by `providers/web.py`. A sent image becomes a normal ArtBuff library
  item under source `web`, keyed by a SHA-256 hash of its URL — so it shows up
  in History, can be favourited and re-displayed from the ArtBuff web UI, and
  sending the same image twice reuses the existing TV upload instead of
  duplicating it. If the TV is off/unreachable, the image is still saved and
  the extension reports "Saved to ArtBuff" instead of success.
- **Feedback**: the server answers JSON (`{"ok": true}` / `{"ok": false,
  "saved": true, ...}` / error text). The extension shows it as a notification
  where `chrome.notifications` exists, otherwise (Safari) as a toolbar badge:
  `…` while sending, `✓` on success, `!` on failure, clearing after 4 s.
- **Base URL** is a setting (extension Settings page), stored in
  `chrome.storage.sync`, default `http://artbuff.jaybuff.com` — the split-DNS
  name for the ArtBuff Mac on the home LAN (Caddy → 127.0.0.1:8420).

## Package it for Safari with Xcode (macOS)

Safari extensions ship inside a macOS app. Apple's converter generates the
whole Xcode project from this folder:

1. Install **Xcode** from the App Store (ships `safari-web-extension-converter`).
2. Convert this folder into a project:

   ```sh
   xcrun safari-web-extension-converter ~/workspace/artbuff-extension \
     --project-location ~/workspace/ArtBuffSender \
     --app-name "ArtBuff Sender" --bundle-identifier com.jaybuff.artbuffsender \
     --swift --copy-resources
   ```

   (Drop `--swift`/`--copy-resources` if your converter version phrases them
   differently; `xcrun safari-web-extension-converter --help` lists them.)
3. Open the generated project in Xcode. Two targets matter:
   - the **app target** ("ArtBuff Sender") — a minimal container app; you run
     it once so Safari registers the extension. Its own UI is irrelevant.
   - the **extension target** ("ArtBuff Sender Extension") — wraps the files
     in this folder.
4. **Signing**: select each target → *Signing & Capabilities* → check
   *Automatically manage signing* and pick your **Team** (your Apple ID as a
   Personal Team is fine for your own Mac; the extension only ever runs
   locally). Xcode may ask to create certificates — accept.
5. **Run** the app target once (▶ in Xcode, or launch the built app from
   Finder). Quit it — it only needs to exist.
6. In **Safari**: *Settings → Extensions* → tick **ArtBuff Sender** on.
   (First time, Safari may say the extension is from an unidentified
   developer workflow — the unsigned path below covers that case.)
7. Browse to any page, right-click an image → **Send to Frame TV**. Watch the
   toolbar badge. If it fails, open the extension's Settings and use
   **Test connection** to check the base URL.

### Testing without signing: unsigned extensions

For quick iteration you can skip proper signing:

1. Safari → *Settings → Advanced* → **Show Develop menu in menu bar**.
2. **Develop → Allow Unsigned Extensions**. (Safari forgets this on every
   restart, so you'll re-tick it often — that's normal.)
3. Build/run the converted project from Xcode with signing set to
   *Sign to Run Locally*, then enable it under *Settings → Extensions*.

## Known limits (v1)

- **Hotlink/login-protected images**: the server fetches with a browser UA
  and the page as Referer, which covers most cases — but images behind a
  login session, signed/expiring URLs you waited too long on, or strict
  CDN bot checks will fail (the extension shows the server's error). The
  server has none of your Safari cookies, by design.
- **Non-URL images**: images Safari shows from `blob:` or `data:` URLs can't
  be fetched by the server; the extension refuses them up front.
- **Plain-http LAN host**: the server is `http://` on the home network (no
  TLS — split DNS can't get a public cert). The manifest's host permission
  names the default base exactly; if you change the base URL in Settings,
  the extension requests host permission for that origin — approve it, or
  sends will fail. Never expose ArtBuff beyond the LAN: it has no auth.
- **Image quality**: ArtBuff fits the whole image on the 3840×2160 canvas
  (no crop), so small web images will look soft on the TV. Source resolution
  is whatever the page linked — the extension sends the image's own URL,
  which for `srcset`-heavy sites may be a mid-size variant.
- **iOS not covered**: this package targets macOS Safari. The WebExtension
  code is portable, but iOS needs its own app/extension project and the
  context-menu flow differs; not part of v1.
- **Badge-only feedback in Safari**: Safari doesn't implement
  `chrome.notifications` for web extensions, so feedback is the toolbar
  badge (`✓` / `!` / "Saved" isn't distinguishable beyond the badge + the
  ArtBuff History page). Error detail lives server-side in ArtBuff's log.

## Files

| File | What |
|---|---|
| `manifest.json` | MV3 manifest: `contextMenus` + `activeTab` + `storage` + `notifications`, host permission for the default ArtBuff base, options page, background service worker |
| `background.js` | Context-menu item, the POST to `/api/send-image`, badge/notification feedback |
| `options.html` / `options.js` | Settings page: ArtBuff base URL (default `http://artbuff.jaybuff.com`), permission request for custom origins, connection test against `/stats` |
| `icon.png` | Toolbar/notification icon (also regenerated by the Xcode converter if absent) |
