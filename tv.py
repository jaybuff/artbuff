import threading

from samsungtvws import SamsungTVWS

import config

_lock = threading.Lock()  # the TV handles one websocket session at a time


class TVError(Exception):
    pass


def _client(timeout: int = 30) -> SamsungTVWS:
    if not config.TV_IP:
        raise TVError("TV_IP is not set. Add it to .env and restart.")
    return SamsungTVWS(
        host=config.TV_IP,
        port=config.TV_PORT,
        token_file=str(config.TV_TOKEN_FILE),
        timeout=timeout,
        name="ArtBuff",
    )


def is_paired() -> bool:
    return config.TV_TOKEN_FILE.exists() and config.TV_TOKEN_FILE.stat().st_size > 0


def pair() -> None:
    """Open the remote channel. On first contact the TV shows an Allow/Deny prompt;
    samsungtvws saves the token to TV_TOKEN_FILE once approved, so this happens once."""
    with _lock:
        tv = _client(timeout=60)
        try:
            tv.open()
        except Exception as e:
            raise TVError(f"Could not pair with the TV at {config.TV_IP}: {e}") from e
        finally:
            tv.close()
    if not is_paired():
        raise TVError("The TV did not issue a token. Did you press Allow on the TV?")


def display(make_jpeg, reuse_content_id: str | None = None, known_ids: list[str] | None = None) -> str:
    """Show an image in Art Mode. `make_jpeg` is only called if an upload is needed.
    Returns the TV content_id used."""
    with _lock:
        tv = _client(timeout=60)
        art = tv.art()
        try:
            if not art.supported():
                raise TVError("This TV does not report Frame/Art Mode support.")
            if reuse_content_id and any(c.get("content_id") == reuse_content_id for c in art.available()):
                content_id = reuse_content_id
            else:
                content_id = art.upload(make_jpeg(), matte="none", portrait_matte="none", file_type="JPEG")
            if not art.get_artmode() == "on":
                art.set_artmode(True)
            art.select_image(content_id, show=True)
            _prune(art, keep_id=content_id, ours=known_ids or [])
            return content_id
        except TVError:
            raise
        except Exception as e:
            raise TVError(f"TV error: {e}") from e
        finally:
            tv.close()


def _prune(art, keep_id: str, ours: list[str]):
    """Delete the oldest ArtBuff uploads beyond MAX_TV_UPLOADS (never touches other art)."""
    try:
        on_tv = {c.get("content_id") for c in art.available()}
        mine = [c for c in ours if c in on_tv and c != keep_id]
        excess = len(mine) + 1 - config.MAX_TV_UPLOADS
        if excess > 0:
            art.delete_list(mine[:excess])
    except Exception:
        pass  # pruning is best-effort
