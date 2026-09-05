"""Attaching a file to a record.

The original is copied into the runtime folder rather than referenced where it
was found: a receipt on a USB stick or in Downloads is gone by the time anyone
looks for it again. Each record owns its copies, filed under its own folder, so
removing one record never disturbs another. The copy is named after a digest so
two files with the same name never collide, and the display name the user
recognises is kept in the row.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path

from database.connection import Database
from database.repositories.attachments import AttachmentRecord, AttachmentRepository

logger = logging.getLogger("office_reminder.attachments")

#: Big enough for a scanned multi-page tahakkuk fişi, small enough that the
#: runtime folder does not quietly fill a disk.
MAX_BYTES = 25 * 1024 * 1024

#: What an office actually attaches. Anything executable is refused outright:
#: the app must never become a way to carry a program between machines.
ALLOWED_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff",
    ".txt", ".csv", ".xlsx", ".xls", ".docx", ".doc", ".odt", ".ods", ".zip",
}


class AttachmentError(RuntimeError):
    """Carries a message meant for the user."""


@dataclass(slots=True, frozen=True)
class Attachment:
    record: AttachmentRecord
    path: Path

    @property
    def id(self) -> int:
        return self.record.id

    @property
    def display_name(self) -> str:
        return self.record.display_name

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def size(self) -> int:
        return self.path.stat().st_size if self.exists else 0


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 256), b""):
            sha.update(block)
    return sha.hexdigest()


class AttachmentService:
    def __init__(self, database: Database, root: Path | None = None) -> None:
        self.database = database
        self.repository = AttachmentRepository(database)
        if root is None:
            from app.paths import get_attachments_dir

            root = get_attachments_dir()
        self.root = Path(root)

    # ------------------------------------------------------------------ paths
    def _folder(self, source_kind: str, source_id: int) -> Path:
        return self.root / source_kind.lower() / str(int(source_id))

    def absolute_path(self, record: AttachmentRecord) -> Path:
        return self.root / record.relative_path

    # ----------------------------------------------------------------- attach
    def attach(self, source_kind: str, source_id: int, source_path: Path) -> Attachment:
        """Copy `source_path` next to the record and remember it."""
        source_path = Path(source_path)
        if not source_path.is_file():
            raise AttachmentError("Dosya bulunamadı.")

        suffix = source_path.suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise AttachmentError(
                f"“{suffix or 'uzantısız'}” türünde dosya eklenemez. "
                "PDF, görsel, Office belgesi ve metin dosyaları eklenebilir."
            )

        size = source_path.stat().st_size
        if size > MAX_BYTES:
            raise AttachmentError(
                f"Dosya çok büyük ({human_size(size)}). En fazla {human_size(MAX_BYTES)}."
            )
        if size == 0:
            raise AttachmentError("Dosya boş.")

        digest = _digest(source_path)
        folder = self._folder(source_kind, source_id)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{digest[:16]}{suffix}"
        relative = target.relative_to(self.root).as_posix()

        # The same file attached twice to the same record is one attachment.
        for existing in self.repository.list_for(source_kind, source_id):
            if existing.relative_path == relative:
                return Attachment(existing, self.absolute_path(existing))

        try:
            if not target.exists():
                shutil.copy2(source_path, target)
        except OSError as exc:
            raise AttachmentError(f"Dosya kopyalanamadı: {exc.strerror or exc}") from exc

        attachment_id = self.repository.add(
            source_kind=source_kind,
            source_id=source_id,
            display_name=source_path.name,
            relative_path=relative,
            mime_type=mimetypes.guess_type(source_path.name)[0],
            sha256=digest,
        )
        record = self.repository.get(attachment_id)
        logger.info("attached %s -> %s", source_path.name, relative)
        return Attachment(record, target)

    # ------------------------------------------------------------------ query
    def list_for(self, source_kind: str, source_id: int) -> list[Attachment]:
        return [
            Attachment(record, self.absolute_path(record))
            for record in self.repository.list_for(source_kind, source_id)
        ]

    def count_for(self, source_kind: str, source_id: int) -> int:
        return self.repository.count_for(source_kind, source_id)

    def ids_with_attachments(self, source_kind: str) -> set[int]:
        return self.repository.ids_with_attachments(source_kind)

    # ----------------------------------------------------------------- remove
    def remove(self, attachment_id: int) -> None:
        """Drop the row and the file.

        Each record owns its copy — the folder is keyed by record, so the same
        document attached to two obligations is stored twice. That costs a few
        kilobytes and buys the guarantee that deleting one record can never
        take a file out from under another.
        """
        record = self.repository.get(attachment_id)
        if record is None:
            return
        path = self.absolute_path(record)
        self.repository.delete(attachment_id)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Ek dosyası silinemedi: %s", path, exc_info=True)

    def remove_all_for(self, source_kind: str, source_id: int) -> int:
        """Used when the record itself goes away."""
        removed = 0
        for attachment in self.list_for(source_kind, source_id):
            self.remove(attachment.id)
            removed += 1
        return removed


__all__ = [
    "ALLOWED_SUFFIXES",
    "MAX_BYTES",
    "Attachment",
    "AttachmentError",
    "AttachmentService",
    "human_size",
]
