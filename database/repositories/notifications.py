from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from database.connection import Database

VALID_KINDS = {"DUE", "OVERDUE", "OFFICIAL_REVISION"}
VALID_SEVERITIES = {"INFO", "WARNING", "DANGER"}


@dataclass(slots=True, frozen=True)
class AppNotification:
    id: int
    kind: str
    severity: str
    title: str
    body: str
    source_kind: str
    source_id: int
    company_id: int | None
    company_name: str | None
    due_date: str | None
    created_at: str
    read_at: str | None

    @property
    def is_unread(self) -> bool:
        return self.read_at is None


class NotificationInboxRepository:
    """The in-app notification inbox.

    This is the channel that cannot be silenced: a row here survives Focus
    Assist, a closed window and a restart, and stays unread until the user
    actually looks at it.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def add(
        self,
        *,
        kind: str,
        title: str,
        body: str,
        source_kind: str,
        source_id: int,
        notification_key: str,
        company_id: int | None = None,
        due_date: str | None = None,
        severity: str = "INFO",
    ) -> int | None:
        """Insert one notification. Returns None when it was already there."""
        if kind not in VALID_KINDS:
            raise ValueError(f"Geçersiz bildirim türü: {kind}")
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"Geçersiz önem derecesi: {severity}")

        with self.database.session() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO app_notifications
                    (kind, severity, title, body, source_kind, source_id, company_id,
                     due_date, notification_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (kind, severity, title, body, source_kind, source_id, company_id,
                 due_date, notification_key),
            )
            return int(cursor.lastrowid) if cursor.rowcount else None

    def list_recent(self, limit: int = 100, unread_only: bool = False) -> list[AppNotification]:
        query = """
            SELECT n.*, c.name AS company_name
            FROM app_notifications n
            LEFT JOIN companies c ON c.id = n.company_id
        """
        if unread_only:
            query += " WHERE n.read_at IS NULL"
        query += " ORDER BY n.created_at DESC, n.id DESC LIMIT ?"
        with self.database.session() as connection:
            rows = connection.execute(query, (limit,)).fetchall()
        return [
            AppNotification(
                id=row["id"],
                kind=row["kind"],
                severity=row["severity"],
                title=row["title"],
                body=row["body"],
                source_kind=row["source_kind"],
                source_id=row["source_id"],
                company_id=row["company_id"],
                company_name=row["company_name"],
                due_date=row["due_date"],
                created_at=row["created_at"],
                read_at=row["read_at"],
            )
            for row in rows
        ]

    def unread_count(self) -> int:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS c FROM app_notifications WHERE read_at IS NULL"
            ).fetchone()
        return int(row["c"]) if row else 0

    def mark_read(self, notification_id: int) -> bool:
        with self.database.session() as connection:
            cursor = connection.execute(
                "UPDATE app_notifications SET read_at = ? WHERE id = ? AND read_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), notification_id),
            )
        return cursor.rowcount > 0

    def mark_all_read(self) -> int:
        with self.database.session() as connection:
            cursor = connection.execute(
                "UPDATE app_notifications SET read_at = ? WHERE read_at IS NULL",
                (datetime.now(timezone.utc).isoformat(),),
            )
        return cursor.rowcount

    def delete_read_before(self, cutoff_iso: str) -> int:
        """Housekeeping: drop notifications the user has already seen."""
        with self.database.session() as connection:
            cursor = connection.execute(
                "DELETE FROM app_notifications WHERE read_at IS NOT NULL AND created_at < ?",
                (cutoff_iso,),
            )
        return cursor.rowcount
