import io

from PIL import Image, ImageColor, ImageOps

import frames

TARGET = frames.CANVAS
MAX_BYTES = 50 * 1024 * 1024
MAX_ZOOM = 8.0

# Museum scans can be enormous; allow big but not decompression-bomb big.
Image.MAX_IMAGE_PIXELS = 500_000_000

# A view is (frame_id, cx, cy, zoom): the point of the image (as fractions) centered in the
# frame's opening, and zoom relative to "cover" (1 = image just fills the opening; below 1 shows
# the whole image with background around it). zoom None = fit the whole image.
View = tuple[str, float, float, "float | None"]


def parse_view(s: str | None) -> View | None:
    """"frame,cx,cy,zoom" (zoom may be 'fit') -> View; None if absent or malformed."""
    if not s:
        return None
    try:
        frame, cx, cy, z = s.split(",")
        if frame not in frames.FRAMES:
            return None
        return frame, float(cx), float(cy), None if z == "fit" else float(z)
    except ValueError:
        return None


def format_view(v: View) -> str:
    frame, cx, cy, z = v
    return f"{frame},{cx:.4f},{cy:.4f},{'fit' if z is None else f'{z:.4f}'}"


def _axis_center(c: float, visible: float, total: float) -> float:
    """Clamp a view center: a view smaller than the image stays inside it, a larger one keeps the image inside it."""
    half = visible / 2 / total
    lo, hi = min(half, 1 - half), max(half, 1 - half)
    return min(max(c, lo), hi)


def prepare_for_tv(data: bytes, background: str = "black", view: View | None = None) -> bytes:
    """Return a 3840x2160 JPEG: the image placed in the frame's opening per `view`, frame on top.

    With no view the whole image is fit (no stretch, no crop) on a solid background."""
    bg = ImageColor.getrgb(background)
    frame_id, cx, cy, zoom = view or ("none", 0.5, 0.5, None)

    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGBA", rgba.size, bg + (255,))
        flat.alpha_composite(rgba)
        img = flat.convert("RGB")
    else:
        img = img.convert("RGB")

    ax0, ay0, ax1, ay1 = frames.aperture(frame_id)
    aw, ah = ax1 - ax0, ay1 - ay0
    cover = max(aw / img.width, ah / img.height)  # px per source px that just fills the opening
    fit = min(aw / img.width, ah / img.height)
    z = fit / cover if zoom is None else min(max(zoom, fit / cover), MAX_ZOOM)
    s = cover * z
    sw, sh = aw / s, ah / s  # source area visible through the opening
    cx = _axis_center(cx, sw, img.width)
    cy = _axis_center(cy, sh, img.height)
    left, top = cx * img.width - sw / 2, cy * img.height - sh / 2

    # Visible part of the source, and where it lands inside the opening.
    l, t = max(left, 0.0), max(top, 0.0)
    r, b = min(left + sw, float(img.width)), min(top + sh, float(img.height))
    dw, dh = max(1, round((r - l) * s)), max(1, round((b - t) * s))
    region = img.resize((dw, dh), Image.LANCZOS, box=(l, t, r, b))

    canvas = Image.new("RGB", TARGET, bg)
    canvas.paste(region, (ax0 + round((l - left) * s), ay0 + round((t - top) * s)))

    if frame_id != "none":
        canvas = Image.alpha_composite(canvas.convert("RGBA"), frames.render_frame(frame_id, TARGET)).convert("RGB")

    for quality in (92, 85, 75, 60):
        out = io.BytesIO()
        canvas.save(out, "JPEG", quality=quality, optimize=True, subsampling=0)
        if out.tell() <= MAX_BYTES:
            break
    return out.getvalue()
