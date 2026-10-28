"""Frame / matte definitions and rendering.

A frame is a list of concentric bands (outermost first). Band widths are fractions of the canvas
height, so thickness is the same on all four sides and scales with output resolution. The frame
is rendered to a transparent-centered RGBA overlay; the "aperture" is the opening the artwork
shows through. The browser preview and the final TV image both use this same renderer.
"""
from functools import lru_cache

from PIL import Image, ImageColor, ImageDraw

CANVAS = (3840, 2160)


def band(w, color, bevel=None):
    """bevel=(light, dark) shades the four sides like a raised moulding lit from the top-left."""
    return {"w": w, "color": color, "bevel": bevel}


FRAMES = {
    "none": {"label": "No frame", "bands": [], "shadow": False},
    "slim-black": {
        "label": "Slim black",
        "bands": [band(0.012, "#141414", ("#3a3a3a", "#050505"))],
        "shadow": True,
    },
    "modern": {
        "label": "Modern",
        "bands": [
            band(0.010, "#161616", ("#3c3c3c", "#060606")),
            band(0.075, "#f3f0e9"),
            band(0.003, "#d6d1c4", ("#ece8de", "#bdb7a8")),
        ],
        "shadow": True,
    },
    "gallery-white": {
        "label": "Gallery white",
        "bands": [band(0.014, "#efefec", ("#ffffff", "#c9c9c4")), band(0.055, "#fbfbf9"), band(0.003, "#e4e4df")],
        "shadow": True,
    },
    "walnut": {
        "label": "Walnut",
        "bands": [
            band(0.034, "#5a3826", ("#8a5d42", "#2e1b11")),
            band(0.004, "#2a1a10"),
            band(0.040, "#e9e1d1"),
            band(0.003, "#cfc6b3", ("#f3ecdd", "#b3a98f")),
        ],
        "shadow": True,
    },
    "ornate-gold": {
        "label": "Ornate gold",
        "bands": [
            band(0.005, "#4d3a0e"),
            band(0.013, "#c9a23c", ("#f6df86", "#7e6118")),
            band(0.007, "#8a691d", ("#b8923a", "#5b430e")),
            band(0.016, "#d9b24b", ("#fdeeaa", "#94731f")),
            band(0.005, "#5e460f"),
            band(0.011, "#e3c560", ("#fff3b8", "#9c7a26")),
            band(0.006, "#7c5f17", ("#a98528", "#4a360a")),
            band(0.022, "#efe6cf"),
            band(0.004, "#c9a23c", ("#f6df86", "#7e6118")),
        ],
        "shadow": True,
    },
    "matte-white": {
        "label": "White matte",
        "bands": [band(0.085, "#f8f7f3"), band(0.003, "#dcd8cc", ("#efece3", "#c4bfb0"))],
        "shadow": True,
    },
    "matte-black": {
        "label": "Black matte",
        "bands": [band(0.085, "#0f0f0f"), band(0.003, "#2a2a2a", ("#3d3d3d", "#161616"))],
        "shadow": True,
    },
}


def _px(frame_id: str, size) -> list[int]:
    return [round(b["w"] * size[1]) for b in FRAMES[frame_id]["bands"]]


def aperture(frame_id: str, size=CANVAS) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of the opening, in pixels of a canvas of `size`."""
    i = sum(_px(frame_id, size))
    return i, i, size[0] - i, size[1] - i


def aperture_fractions(frame_id: str) -> list[float]:
    x0, y0, x1, y1 = aperture(frame_id)
    return [x0 / CANVAS[0], y0 / CANVAS[1], x1 / CANVAS[0], y1 / CANVAS[1]]


def _mix(a, b, t):
    ca, cb = ImageColor.getrgb(a), ImageColor.getrgb(b)
    return tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


@lru_cache(maxsize=3)
def render_frame(frame_id: str, size=CANVAS) -> Image.Image:
    """RGBA overlay of `size` (treat as read-only: it is cached)."""
    spec = FRAMES[frame_id]
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    if not spec["bands"]:
        return out
    d = ImageDraw.Draw(out)
    x0, y0, x1, y1 = 0, 0, size[0] - 1, size[1] - 1
    for b, w in zip(spec["bands"], _px(frame_id, size)):
        if w <= 0:
            continue
        top = [(x0, y0), (x1, y0), (x1 - w, y0 + w), (x0 + w, y0 + w)]
        bottom = [(x0, y1), (x1, y1), (x1 - w, y1 - w), (x0 + w, y1 - w)]
        left = [(x0, y0), (x0 + w, y0 + w), (x0 + w, y1 - w), (x0, y1)]
        right = [(x1, y0), (x1 - w, y0 + w), (x1 - w, y1 - w), (x1, y1)]
        base = ImageColor.getrgb(b["color"])
        if b["bevel"]:
            hi, lo = b["bevel"]
            cols = (ImageColor.getrgb(hi), _mix(hi, b["color"], 0.45), ImageColor.getrgb(lo), _mix(lo, b["color"], 0.45))
        else:
            cols = (base,) * 4
        for poly, col in zip((top, left, bottom, right), (cols[0], cols[1], cols[2], cols[3])):
            d.polygon(poly, fill=col + (255,))
        x0, y0, x1, y1 = x0 + w, y0 + w, x1 - w, y1 - w

    ax0, ay0, ax1, ay1 = aperture(frame_id, size)
    out.paste((0, 0, 0, 0), (ax0, ay0, ax1, ay1))  # exact, fully transparent opening
    if spec["shadow"]:  # soft shadow cast by the frame onto the art, stronger at top/left
        n = max(2, round(0.007 * size[1]))
        for k in range(n):
            a = round(120 * (1 - k / n) ** 2)
            ix0, iy0, ix1, iy1 = ax0 + k, ay0 + k, ax1 - 1 - k, ay1 - 1 - k
            d.line([(ix0, iy0), (ix1, iy0)], fill=(0, 0, 0, a))
            d.line([(ix0, iy0), (ix0, iy1)], fill=(0, 0, 0, a))
            d.line([(ix0, iy1), (ix1, iy1)], fill=(0, 0, 0, a // 2))
            d.line([(ix1, iy0), (ix1, iy1)], fill=(0, 0, 0, a // 2))
    return out
