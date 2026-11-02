import ipaddress
import logging
import threading
import time

import wakeonlan
from samsungtvws import SamsungTVWS

import config

log = logging.getLogger("artbuff")

_lock = threading.Lock()  # the TV handles one websocket session at a time

WAKE_TIMEOUT = 30  # seconds to wait for the TV to come up
WAKE_RESEND = 5  # seconds between wake packets, in case one is lost


class TVError(Exception):
    pass


def ip() -> str | None:
    try:
        return config.TV_IP_FILE.read_text().strip() or None
    except OSError:
        return None


def set_ip(value: str) -> None:
    """Save the TV's address. Must be a private address: pages can post here with no auth, and
    the pairing token is sent to whatever this points at. Raises ValueError if it's not valid."""
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        raise ValueError("That doesn't look like an IP address, such as 192.168.1.50.") from None
    if not address.is_private:
        raise ValueError(f"{address} isn't an address on a home network.")
    config.TV_IP_FILE.write_text(str(address))


def _client(timeout: int = 30) -> SamsungTVWS:
    host = ip()
    if not host:
        raise TVError("The TV's IP address isn't set. Enter it on the TV page.")
    return SamsungTVWS(
        host=host,
        port=config.TV_PORT,
        token_file=str(config.TV_TOKEN_FILE),
        timeout=timeout,
        name="ArtBuff",
    )


def is_paired() -> bool:
    return config.TV_TOKEN_FILE.exists() and config.TV_TOKEN_FILE.stat().st_size > 0


def _power_state() -> str | None:
    """The TV's reported power state, or None if it can't be reached."""
    try:
        device = _client(timeout=2).rest_device_info()["device"]
    except TVError:
        raise
    except Exception:
        return None
    _remember_mac(device)
    return device.get("PowerState", "on")


def _remember_mac(device: dict) -> None:
    """Save the TV's MAC while it can tell us, since waking it is when it can't."""
    mac = device.get("wifiMac")
    if device.get("networkType") == "wireless" and mac and mac != _saved_mac():
        try:
            config.TV_MAC_FILE.write_text(mac)
            log.info("Learned TV MAC address %s", mac)
        except OSError as e:
            log.warning("Could not save the TV's MAC address: %s", e)


def _saved_mac() -> str | None:
    try:
        return config.TV_MAC_FILE.read_text().strip() or None
    except OSError:
        return None


def learn_mac() -> None:
    """Ask the TV for its MAC, if it's on. Called at startup."""
    if not ip():
        return
    try:
        with _lock:
            _power_state()
    except TVError as e:
        log.warning("Could not learn the TV's MAC address: %s", e)


def _wake() -> None:
    """Wake the TV if it's off and its MAC is known. Call with _lock held. A TV that answers but
    still reports standby is left for the caller to try, since it may accept the connection."""
    if (state := _power_state()) == "on":
        return
    if not (mac := _saved_mac()):
        log.warning("TV is %s, but its MAC address isn't known yet, so it can't be woken", state or "unreachable")
        return
    log.info("TV is %s, waking it", state or "unreachable")
    deadline = time.monotonic() + WAKE_TIMEOUT
    next_packet = 0.0
    while time.monotonic() < deadline:
        if time.monotonic() >= next_packet:
            try:
                wakeonlan.send_magic_packet(mac)
            except (ValueError, OSError) as e:
                raise TVError(f"Could not send a wake packet to {mac}: {e}") from e
            next_packet = time.monotonic() + WAKE_RESEND
        time.sleep(1)
        state = _power_state()
        if state == "on":
            return
    if state is None:
        raise TVError(f"The TV didn't wake within {WAKE_TIMEOUT} seconds.")


def pair() -> None:
    """Open the remote channel. On first contact the TV shows an Allow/Deny prompt;
    samsungtvws saves the token to TV_TOKEN_FILE once approved, so this happens once."""
    with _lock:
        _wake()
        tv = _client(timeout=60)
        try:
            tv.open()
        except Exception as e:
            raise TVError(f"Could not pair with the TV at {ip()}: {e}") from e
        finally:
            tv.close()
    if not is_paired():
        raise TVError("The TV did not issue a token. Did you press Allow on the TV?")


def display(make_jpeg, reuse_content_id: str | None = None, known_ids: list[str] | None = None) -> str:
    """Show an image in Art Mode. `make_jpeg` is only called if an upload is needed.
    Returns the TV content_id used."""
    with _lock:
        _wake()
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
