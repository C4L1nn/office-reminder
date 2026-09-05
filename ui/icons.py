"""A small, self-contained stroke icon set.

The geometry below is written for this app — plain SVG path data on a 24×24
grid, no third-party asset and no font dependency, so nothing extra has to be
licensed or shipped. Icons are rendered at runtime and tinted with a theme
colour, which also means they stay crisp at 125% and 150% display scaling.

Emoji are deliberately not used: they render differently per Windows build and
carry a colour the theme cannot control.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

from ui.theme import tokens

_STROKE = 'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'

PATHS: dict[str, str] = {
    "dashboard": "M3.5 11.2 12 4l8.5 7.2M6 10v9.5h12V10",
    "bell": "M6 9a6 6 0 1 1 12 0c0 4 1.3 5.4 2 6.2H4c.7-.8 2-2.2 2-6.2M10 19a2 2 0 0 0 4 0",
    "building": "M4 20V5.2A1.2 1.2 0 0 1 5.2 4h7.6A1.2 1.2 0 0 1 14 5.2V20M14 9.5h4.8A1.2 1.2 0 0 1 20 10.7V20"
                "M3 20h18M7 8h3.5M7 11.5h3.5M7 15h3.5M17 13h.01M17 16.5h.01",
    "car": "M4.6 15.5h14.8M5.8 15.5 7.2 9.6A1.6 1.6 0 0 1 8.8 8.4h6.4a1.6 1.6 0 0 1 1.6 1.2l1.4 5.9"
           "M3.6 15.5v3.1h2.6v-1.6M20.4 15.5v3.1h-2.6v-1.6M7.6 12.6h8.8",
    # A sticky note: a square with its bottom-right corner peeled back.
    "note": "M5 4.8h10.4a1.2 1.2 0 0 1 1.2 1.2v8.4L13.4 19H6a1.2 1.2 0 0 1-1.2-1.2V6"
            "A1.2 1.2 0 0 1 5 4.8ZM16.6 14.4h-2.4a1.2 1.2 0 0 0-1.2 1.2V19"
            "M8 9h7M8 12h5",
    # A month grid: the calendar frame with its weeks ruled in.
    "calendar_month": "M4.5 6.6h15v12.9h-15zM4.5 10.6h15M9.5 10.6v8.9M14.5 10.6v8.9"
                      "M4.5 15h15M8.2 4.5v3.4M15.8 4.5v3.4",
    # A paperclip: this record carries a file.
    "paperclip": "M17.6 11.1 12 16.7a3.9 3.9 0 0 1-5.5-5.5l6.6-6.6a2.6 2.6 0 0 1 3.7 3.7"
                 "l-6.6 6.6a1.3 1.3 0 0 1-1.8-1.8l5.7-5.7",
    # Rich-text formatting.
    "bold": "M8 5h5.4a3.2 3.2 0 0 1 0 6.5H8zM8 11.5h6.2a3.4 3.4 0 0 1 0 6.9H8zM8 5v13.4",
    "italic": "M10.5 5h6M7.5 19h6M14.5 5l-4 14",
    "underline": "M7.5 4.5v6.6a4.5 4.5 0 0 0 9 0V4.5M6.5 19.5h11",
    "text_colour": "M6 15.6 12 4.8l6 10.8M8.4 12.3h7.2M5 19.6h14",
    "bullet_list": "M9.5 6.6h10M9.5 12h10M9.5 17.4h10M5 6.6h.01M5 12h.01M5 17.4h.01",
    # Notes canvas: the three arrangements, the grid toggle and zoom reset.
    "tile_rows": "M4 5.5h5.5v13H4zM14.5 5.5H20v13h-5.5",
    "tile_column": "M4.5 5h15v4.4h-15zM4.5 14.6h15V19h-15",
    "cascade": "M4.5 8.5h9v9h-9zM8 5h9.5v9.5",
    "grid": "M4.5 4.5h6v6h-6zM13.5 4.5h6v6h-6zM4.5 13.5h6v6h-6zM13.5 13.5h6v6h-6",
    "zoom_reset": "M10.6 17.2a6.6 6.6 0 1 0 0-13.2 6.6 6.6 0 0 0 0 13.2ZM15.4 15.4 20 20M7.8 10.6h5.6",
    "chevron_left": "M14.5 5.5 8 12l6.5 6.5",
    "cloud": "M7.4 18.4a3.9 3.9 0 0 1-.3-7.8A5.2 5.2 0 0 1 17 9.8a3.6 3.6 0 0 1 .3 7.1z",
    "settings": "M12 15.1a3.1 3.1 0 1 0 0-6.2 3.1 3.1 0 0 0 0 6.2z"
                "M19.1 14.2a1.4 1.4 0 0 0 .3 1.5l.1.1a1.7 1.7 0 1 1-2.4 2.4l-.1-.1a1.4 1.4 0 0 0-2.4 1v.2a1.7 1.7 0 1 1-3.4 0v-.1"
                "a1.4 1.4 0 0 0-2.4-1l-.1.1a1.7 1.7 0 1 1-2.4-2.4l.1-.1a1.4 1.4 0 0 0-1-2.4H5a1.7 1.7 0 1 1 0-3.4h.1"
                "a1.4 1.4 0 0 0 1-2.4l-.1-.1a1.7 1.7 0 1 1 2.4-2.4l.1.1a1.4 1.4 0 0 0 2.4-1V5a1.7 1.7 0 1 1 3.4 0v.1"
                "a1.4 1.4 0 0 0 2.4 1l.1-.1a1.7 1.7 0 1 1 2.4 2.4l-.1.1a1.4 1.4 0 0 0 1 2.4h.2a1.7 1.7 0 1 1 0 3.4H19z",
    "plus": "M12 5.5v13M5.5 12h13",
    "check": "M5 12.8 9.5 17 19 7.4",
    "trash": "M4.5 6.8h15M9.6 6.8V5.2A1.2 1.2 0 0 1 10.8 4h2.4a1.2 1.2 0 0 1 1.2 1.2v1.6"
             "M6.6 6.8 7.5 19a1.2 1.2 0 0 0 1.2 1.1h6.6a1.2 1.2 0 0 0 1.2-1.1l.9-12.2M10.2 10.4v6M13.8 10.4v6",
    "pencil": "M4.5 19.5h3.6L18.4 9.2a1.7 1.7 0 0 0 0-2.4l-1.2-1.2a1.7 1.7 0 0 0-2.4 0L4.5 15.9zM14 7.2l2.8 2.8",
    "search": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM16.2 16.2 20.5 20.5",
    "calendar": "M5.5 6.5h13a1.2 1.2 0 0 1 1.2 1.2v11a1.2 1.2 0 0 1-1.2 1.2h-13A1.2 1.2 0 0 1 4.3 18.7v-11"
                "A1.2 1.2 0 0 1 5.5 6.5zM8.5 4v4.6M15.5 4v4.6M4.3 11h15.4",
    "clock": "M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17zM12 7.2V12l3.2 2",
    "alert": "M12 4.5 21 19.5H3zM12 10v4.2M12 17h.01",
    "refresh": "M20 6.5v4.8h-4.8M4 17.5v-4.8h4.8"
               "M19.2 11.3A7.4 7.4 0 0 0 6.4 8.2L4 11.3M4.8 12.7a7.4 7.4 0 0 0 12.8 3.1L20 12.7",
    "folder": "M4 18.5V6.7a1.2 1.2 0 0 1 1.2-1.2h3.9l2 2.4h7.7A1.2 1.2 0 0 1 20 9.1v9.4a1.2 1.2 0 0 1-1.2 1.2H5.2A1.2 1.2 0 0 1 4 18.5z",
    "shield": "M12 20.5c4-1.8 6.5-5 6.5-9.2V6.2L12 3.8 5.5 6.2v5.1c0 4.2 2.5 7.4 6.5 9.2zM9.2 11.8l2 2 3.6-3.8",
    "external": "M14 4.5h5.5V10M19.5 4.5 11 13M17 14.4v4.3a1.2 1.2 0 0 1-1.2 1.2H5.7a1.2 1.2 0 0 1-1.2-1.2V8.2A1.2 1.2 0 0 1 5.7 7H10",
    "close": "M6.5 6.5l11 11M17.5 6.5l-11 11",
    "chevron_right": "M9.5 5.5 16 12l-6.5 6.5",
    "chevron_down": "M5.5 9.5 12 16l6.5-6.5",
    "database": "M12 7.6c4.1 0 7.4-1 7.4-2.3S16.1 3 12 3 4.6 4 4.6 5.3 7.9 7.6 12 7.6z"
                "M4.6 5.3v13.4C4.6 20 7.9 21 12 21s7.4-1 7.4-2.3V5.3M4.6 12c0 1.3 3.3 2.3 7.4 2.3s7.4-1 7.4-2.3",
    "download": "M12 4v10.5M7.8 10.6 12 14.8l4.2-4.2M4.8 19.2h14.4",
    "list": "M8.5 6.6h11M8.5 12h11M8.5 17.4h11M4.6 6.6h.01M4.6 12h.01M4.6 17.4h.01",
    "filter": "M4.5 6h15l-5.8 6.9v5.4l-3.4 1.7v-7.1z",
}

_TEMPLATE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{d}" {stroke}/></svg>'


def _svg(name: str, color: str) -> bytes:
    path = PATHS.get(name, PATHS["list"])
    return _TEMPLATE.format(d=path, stroke=_STROKE.format(color=color)).encode("utf-8")


@lru_cache(maxsize=256)
def _render(name: str, color: str, size: int, ratio: int) -> QPixmap:
    from PySide6.QtSvg import QSvgRenderer

    pixels = size * ratio
    image = QImage(pixels, pixels, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    QSvgRenderer(QByteArray(_svg(name, color))).render(painter)
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(float(ratio))
    return pixmap


def pixmap(name: str, size: int = 18, color: str | None = None) -> QPixmap:
    return _render(name, color or tokens().text_muted, size, 2)


def icon(name: str, size: int = 18, color: str | None = None) -> QIcon:
    """A themed icon; the same pixmap is reused for every state."""
    base = pixmap(name, size, color)
    result = QIcon()
    result.addPixmap(base, QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(base, QIcon.Mode.Active, QIcon.State.Off)
    result.addPixmap(base, QIcon.Mode.Selected, QIcon.State.Off)
    return result


def app_icon() -> QIcon:
    """Window and tray icon: a filled rounded square with a bell knocked out."""
    t = tokens()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect x="2" y="2" width="60" height="60" rx="14" fill="{t.accent}"/>'
        f'<path d="M20 28a12 12 0 0 1 24 0c0 8 2.6 10.8 4 12.4H16c1.4-1.6 4-4.4 4-12.4" '
        f'fill="none" stroke="{t.text_on_accent}" stroke-width="3.4" stroke-linejoin="round"/>'
        f'<path d="M27.5 46a4.5 4.5 0 0 0 9 0" fill="none" stroke="{t.text_on_accent}" '
        'stroke-width="3.4" stroke-linecap="round"/>'
        "</svg>"
    )
    from PySide6.QtSvg import QSvgRenderer

    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
        painter.end()
        result.addPixmap(QPixmap.fromImage(image))
    return result


def app_icon_with_badge(count: int) -> QIcon:
    """The app icon with an unread counter dot.

    The taskbar/tray icon is the one thing Do Not Disturb cannot hide, so an
    unread count belongs here: the user sees there is something waiting even
    when Windows suppressed the toast.
    """
    if count <= 0:
        return app_icon()

    t = tokens()
    text = str(count) if count < 10 else ("9+" if count < 100 else "99+")
    width = 26 if len(text) == 1 else 34
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect x="2" y="2" width="60" height="60" rx="14" fill="{t.accent}"/>'
        f'<path d="M20 28a12 12 0 0 1 24 0c0 8 2.6 10.8 4 12.4H16c1.4-1.6 4-4.4 4-12.4" '
        f'fill="none" stroke="{t.text_on_accent}" stroke-width="3.4" stroke-linejoin="round"/>'
        f'<path d="M27.5 46a4.5 4.5 0 0 0 9 0" fill="none" stroke="{t.text_on_accent}" '
        'stroke-width="3.4" stroke-linecap="round"/>'
        f'<rect x="{64 - width - 2}" y="2" width="{width}" height="26" rx="13" '
        f'fill="{t.danger}" stroke="{t.rail}" stroke-width="3"/>'
        f'<text x="{64 - width / 2 - 2}" y="21" text-anchor="middle" '
        f'font-family="Segoe UI, sans-serif" font-size="17" font-weight="700" '
        f'fill="#ffffff">{text}</text>'
        "</svg>"
    )
    from PySide6.QtSvg import QSvgRenderer

    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
        painter.end()
        result.addPixmap(QPixmap.fromImage(image))
    return result


def clear_cache() -> None:
    """Drop rendered icons after a theme change."""
    _render.cache_clear()


ICON_SIZE = QSize(18, 18)
