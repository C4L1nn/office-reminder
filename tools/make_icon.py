"""Render the application icon to resources/icon.ico.

The artwork is the same vector used at runtime (ui.icons.app_icon), so the
window, tray and executable icons cannot drift apart. Run after changing it:

    python tools/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    from ui.icons import app_icon

    target = ROOT / "resources" / "icon.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    icon = app_icon()
    # Qt writes a multi-size .ico from the pixmaps already in the QIcon.
    pixmap = icon.pixmap(256, 256)
    if not pixmap.save(str(target), "ICO"):
        print("icon could not be written", file=sys.stderr)
        return 1
    print(f"wrote resources/icon.ico ({target.stat().st_size} bytes)")
    _ = app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
