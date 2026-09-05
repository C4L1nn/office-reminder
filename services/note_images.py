"""Pictures dropped into sticky notes.

A screenshot pasted onto a note is stored as a file next to the database, not
as base64 inside the note's HTML: a couple of screenshots would otherwise add
megabytes to every row, every query and every backup of the database.

The HTML refers to the picture through a private scheme (`note-image:name.png`)
so the stored markup never carries an absolute path — the runtime folder can
move between machines and the notes still resolve.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

logger = logging.getLogger("office_reminder.notes.images")

#: The scheme that appears in a note's stored HTML.
SCHEME = "note-image"

#: A pasted screenshot is often far larger than the note it lands on; anything
#: wider than this is scaled down before it is written.
MAX_WIDTH = 1600

#: Guards against a pathological paste filling the runtime folder.
MAX_BYTES = 8 * 1024 * 1024

_REFERENCE = re.compile(rf"{SCHEME}:([A-Za-z0-9_.-]+)")


class NoteImageStore:
    """Reads and writes the pictures a note refers to."""

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            from app.paths import get_runtime_root

            root = get_runtime_root() / "note_images"
        self.root = Path(root)

    def path_for(self, name: str) -> Path:
        """Resolve a stored name, refusing anything that escapes the folder."""
        candidate = (self.root / name).resolve()
        root = self.root.resolve()
        if root not in candidate.parents:
            raise ValueError(f"Geçersiz görsel adı: {name}")
        return candidate

    def save(self, image) -> str:
        """Write a QImage and return the name to put in the note's HTML."""
        from PySide6.QtCore import QBuffer, QIODevice, Qt

        if image is None or image.isNull():
            raise ValueError("Görsel okunamadı.")

        if image.width() > MAX_WIDTH:
            image = image.scaledToWidth(
                MAX_WIDTH, Qt.TransformationMode.SmoothTransformation
            )

        # QBuffer must own its byte array: handing it a temporary QByteArray
        # leaves it pointing at freed memory and crashes the process.
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise ValueError("Görsel kaydedilemedi.")
        data = bytes(buffer.data())
        buffer.close()

        if len(data) > MAX_BYTES:
            raise ValueError("Görsel çok büyük.")

        digest = hashlib.sha256(data).hexdigest()[:16]
        name = f"{digest}.png"
        target = self.root / name
        self.root.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        logger.info("note image saved: %s (%s bytes)", name, len(data))
        return name

    # ------------------------------------------------------------- references
    @staticmethod
    def references(html: str) -> set[str]:
        """Every picture one note's HTML points at."""
        return set(_REFERENCE.findall(html or ""))

    def prune(self, used: set[str]) -> int:
        """Delete stored pictures no note refers to any more.

        Called after a note or a board goes away; nothing else would ever
        remove them, and an image nobody can see is just a file taking space.
        """
        if not self.root.is_dir():
            return 0
        removed = 0
        for path in self.root.glob("*.png"):
            if path.name in used:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                logger.warning("Not görseli silinemedi: %s", path, exc_info=True)
        return removed


__all__ = ["MAX_BYTES", "MAX_WIDTH", "SCHEME", "NoteImageStore"]
