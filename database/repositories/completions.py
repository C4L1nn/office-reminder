from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from database.connection import Database

VALID_SOURCE_KINDS = {"OFFICIAL", "MANUAL"}
VALID_STATUSES = {"COMPLETED", "PAID", "FILED", "CANCELLED"}


@dataclass(slots=True, frozen=True)
class CompletionRecord:
    id: int
    source_kind: str
    source_id: int
    company_id: int | None
    completion_status: str
    completed_at: str
    notes: str | None
    amount: float | None


class CompletionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        source_kind: str,
        source_id: int,
        company_id: int | None = None,
        completion_status: str = "COMPLETED",
        notes: str | None = None,
        amount: float | None = None,
    ) -> int:
        kind = source_kind.strip().upper()
        if kind not in VALID_SOURCE_KINDS:
            raise ValueError(f"Geçersiz source_kind: {source_kind}")
        status = completion_status.strip().upper() if completion_status else "COMPLETED"
        if status not in VALID_STATUSES:
            raise ValueError(f"Geçersiz completion_status: {completion_status}")
        with self.database.session() as connection:
            # validate source exists? soft check
            if kind == "MANUAL":
                row = connection.execute("SELECT id FROM manual_reminders WHERE id = ?", (source_id,)).fetchone()
                if row is None:
                    raise ValueError(f"Manuel hatırlatma bulunamadı: {source_id}")
            else:
                row = connection.execute(
                    "SELECT id FROM official_calendar_events WHERE id = ?", (source_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"Resmî event bulunamadı: {source_id}")

            cursor = connection.execute(
                """
                INSERT INTO completion_records
                    (source_kind, source_id, company_id, completion_status, notes, amount)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (kind, source_id, company_id, status, notes, amount),
            )
            # For manual, also set status to COMPLETED for backward view compatibility
            if kind == "MANUAL":
                connection.execute(
                    "UPDATE manual_reminders SET status='COMPLETED', updated_at=CURRENT_TIMESTAMP WHERE id = ?",
                    (source_id,),
                )
            return int(cursor.lastrowid)

    def is_completed(self, source_kind: str, source_id: int, company_id: int | None = None) -> bool:
        kind = source_kind.strip().upper()
        with self.database.session() as connection:
            if company_id is None:
                row = connection.execute(
                    "SELECT 1 FROM completion_records WHERE source_kind=? AND source_id=? AND company_id IS NULL LIMIT 1",
                    (kind, source_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT 1 FROM completion_records WHERE source_kind=? AND source_id=? AND company_id=? LIMIT 1",
                    (kind, source_id, company_id),
                ).fetchone()
            return row is not None

    def get(self, source_kind: str, source_id: int, company_id: int | None = None) -> CompletionRecord | None:
        kind = source_kind.strip().upper()
        with self.database.session() as connection:
            if company_id is None:
                row = connection.execute(
                    "SELECT * FROM completion_records WHERE source_kind=? AND source_id=? AND company_id IS NULL",
                    (kind, source_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM completion_records WHERE source_kind=? AND source_id=? AND company_id=?",
                    (kind, source_id, company_id),
                ).fetchone()
            if row is None:
                return None
            return CompletionRecord(
                id=row["id"],
                source_kind=row["source_kind"],
                source_id=row["source_id"],
                company_id=row["company_id"],
                completion_status=row["completion_status"],
                completed_at=row["completed_at"],
                notes=row["notes"],
                amount=row["amount"],
            )

    def undo(self, source_kind: str, source_id: int, company_id: int | None = None) -> bool:
        kind = source_kind.strip().upper()
        with self.database.session() as connection:
            if company_id is None:
                cursor = connection.execute(
                    "DELETE FROM completion_records WHERE source_kind=? AND source_id=? AND company_id IS NULL",
                    (kind, source_id),
                )
            else:
                cursor = connection.execute(
                    "DELETE FROM completion_records WHERE source_kind=? AND source_id=? AND company_id=?",
                    (kind, source_id, company_id),
                )
            # For manual, revert status to OPEN if no other completion remains
            if kind == "MANUAL" and cursor.rowcount > 0:
                connection.execute(
                    "UPDATE manual_reminders SET status='OPEN', updated_at=CURRENT_TIMESTAMP WHERE id = ?",
                    (source_id,),
                )
            return cursor.rowcount > 0

    def list_for_company(self, company_id: int, limit: int = 200) -> list[CompletionRecord]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM completion_records WHERE company_id=? ORDER BY completed_at DESC LIMIT ?",
                (company_id, limit),
            ).fetchall()
        return [
            CompletionRecord(
                id=r["id"],
                source_kind=r["source_kind"],
                source_id=r["source_id"],
                company_id=r["company_id"],
                completion_status=r["completion_status"],
                completed_at=r["completed_at"],
                notes=r["notes"],
                amount=r["amount"],
            )
            for r in rows
        ]
