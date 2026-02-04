"""
Tray icon images: idle (gray), connected (green), error (red). Generated with Pillow.
"""
from PIL import Image, ImageDraw

_SIZE = 32


def _circle_icon(r: int, g: int, b: int) -> Image.Image:
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 2
    draw.ellipse([margin, margin, _SIZE - margin, _SIZE - margin], fill=(r, g, b, 255))
    return img


def icon_idle() -> Image.Image:
    """Gray circle for disconnected / idle."""
    return _circle_icon(128, 128, 128)


def icon_connected() -> Image.Image:
    """Green circle for connected."""
    return _circle_icon(0, 180, 80)


def icon_error() -> Image.Image:
    """Red circle for error."""
    return _circle_icon(200, 60, 60)


def icon_image(state: str) -> Image.Image:
    """Return the icon image for state: 'idle', 'connected', 'error'."""
    if state == "connected":
        return icon_connected()
    if state == "error":
        return icon_error()
    return icon_idle()
