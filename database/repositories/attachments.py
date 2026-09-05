"""Rows pointing at files on disk.

The file itself never goes into the database — a scanned tahakkuk fişi would
bloat every backup and every query. The row keeps where the copy lives, what it
was called when it arrived, and a digest so a silently corrupted file can be
told from a healthy one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from database.connection import Database

VALID_SOURCES = {"OFFICIAL", "MANUAL", "COMPLETION", "VEHICLE", "COMPANY"}


@dataclass(slots=True, frozen=True)
class AttachmentRecord:
    id: int
    source_kind: str
    source_id: int
    display_name: str
    relative_path: str
    mime_type: str | None
    sha256: str | None
    created_at: str


class AttachmentRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add(
        self,
        *,
        source_kind: str,
        source_id: int,
        display_name: str,
        relative_path: str,
        mime_type: str | None = None,
        sha256: str | None = None,
    ) -> int:
        if source_kind not in VALID_SOURCES:
            raise ValueError(f"Geçersiz ek türü: {source_kind}")
        with self.database.session() as connection:
            cursor = connection.execute(
                "INSERT INTO attachments"
                " (source_kind, source_id, display_name, relative_path, mime_type,"
                "  sha256, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    source_kind,
                    int(source_id),
                    display_name,
                    relative_path,
                    mime_type,
                    sha256,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def list_for(self, source_kind: str, source_id: int) -> list[AttachmentRecord]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT id, source_kind, source_id, display_name, relative_path,"
                "       mime_type, sha256, created_at"
                "  FROM attachments WHERE source_kind = ? AND source_id = ?"
                " ORDER BY created_at, id",
                (source_kind, int(source_id)),
            ).fetchall()
        return [AttachmentRecord(**dict(row)) for row in rows]

    def get(self, attachment_id: int) -> AttachmentRecord | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT id, source_kind, source_id, display_name, relative_path,"
                "       mime_type, sha256, created_at"
                "  FROM attachments WHERE id = ?",
                (int(attachment_id),),
            ).fetchone()
        return AttachmentRecord(**dict(row)) if row else None

    def delete(self, attachment_id: int) -> bool:
        with self.database.session() as connection:
            cursor = connection.execute(
                "DELETE FROM attachments WHERE id = ?", (int(attachment_id),)
            )
            return cursor.rowcount > 0

    def ids_with_attachments(self, source_kind: str) -> set[int]:
        """Every record of this kind that has at least one file.

        One query for the whole list: asking per row would put a query inside
        the table's paint path.
        """
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT DISTINCT source_id FROM attachments WHERE source_kind = ?",
                (source_kind,),
            ).fetchall()
        return {int(row["source_id"]) for row in rows}

    def count_for(self, source_kind: str, source_id: int) -> int:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS c FROM attachments"
                " WHERE source_kind = ? AND source_id = ?",
                (source_kind, int(source_id)),
            ).fetchone()
        return int(row["c"])
