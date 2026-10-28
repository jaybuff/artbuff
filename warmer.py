"""Background cache warmer: slowly fetches details + thumbnails for the pages you're likely to scroll to next.

One daemon thread, one request at a time, ~1/s. It yields to foreground browsing, drops its queue when you
start a different search, and backs off if the museum throttles."""
import collections
import logging
import threading
import time

import httpx

import config

log = logging.getLogger("artbuff.warm")


class Warmer:
    def __init__(self, interval: float, pages_ahead: int):
        self.interval = interval
        self.pages_ahead = pages_ahead
        self._cv = threading.Condition()
        self._jobs: collections.deque = collections.deque()  # (key, provider, resolve_ids)
        self._seen: collections.OrderedDict = collections.OrderedDict()  # job keys already queued/run
        self._sig = None
        self.items_warmed = 0
        self.items_skipped = 0
        self.errors = 0
        self.running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.pages_ahead <= 0 or self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="warmer", daemon=True)
        self._thread.start()

    def submit(self, sig, page: int, provider, resolve_ids) -> None:
        """Queue this page and the next few of one result set. `resolve_ids(page)` -> list of ids."""
        if not self._thread or not hasattr(provider, "warm_item"):
            return
        with self._cv:
            if sig != self._sig:  # new search: older queued work is no longer relevant
                self._jobs.clear()
                self._sig = sig
            for p in range(page, page + self.pages_ahead + 1):
                key = (sig, p)
                if key in self._seen:
                    continue
                self._seen[key] = True
                while len(self._seen) > 500:
                    self._seen.popitem(last=False)
                self._jobs.append((key, provider, lambda p=p: resolve_ids(p)))
            self._cv.notify()

    def stats(self) -> dict:
        return {
            "queued_pages": len(self._jobs),
            "items_warmed": self.items_warmed,
            "items_already_cached": self.items_skipped,
            "errors": self.errors,
            "working": self.running,
        }

    def _next_job(self):
        with self._cv:
            while not self._jobs:
                self.running = False
                self._cv.wait()
            self.running = True
            return self._jobs.popleft()

    def _loop(self) -> None:
        while True:
            key, provider, resolve_ids = self._next_job()
            try:
                self._run(key, provider, resolve_ids)
            except (httpx.HTTPError, ValueError) as e:
                self.errors += 1
                log.warning("warm job %s failed (%s); pausing 30s", key[1], e)
                time.sleep(30)
            except Exception:
                self.errors += 1
                log.exception("warm job crashed")

    def _run(self, key, provider, resolve_ids) -> None:
        ids = resolve_ids()
        before = self.items_warmed
        for art_id in ids:
            with self._cv:
                if self._sig != key[0]:  # user moved on to a different search
                    return
            # Be a polite background citizen: wait for the user to stop browsing, and for any cooldown.
            while provider.foreground_active(1.5) or provider.cooling_down():
                time.sleep(0.5)
            if provider.warm_item(art_id):
                self.items_warmed += 1
                time.sleep(self.interval)
            else:
                self.items_skipped += 1
        log.info("warmed page %s (%d new items of %d)", key[1], self.items_warmed - before, len(ids))


warmer = Warmer(config.WARM_INTERVAL, config.WARM_PAGES)
