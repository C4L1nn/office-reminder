from __future__ import annotations

from dataclasses import dataclass

from database.connection import Database

DEFAULT_OFFSETS = (14, 7, 3, 1, 0)


@dataclass(slots=True, frozen=True)
class NotificationRule:
    id: int
    source_kind: str
    source_id: int
    offset_days: int
    notify_time: str | None
    is_enabled: bool


class NotificationRuleRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_for_source(self, source_kind: str, source_id: int) -> list[NotificationRule]:
        kind = source_kind.strip().upper()
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT id, source_kind, source_id, offset_days, notify_time, is_enabled "
                "FROM notification_rules WHERE source_kind=? AND source_id=? ORDER BY offset_days DESC",
                (kind, source_id),
            ).fetchall()
        return [
            NotificationRule(
                id=r["id"],
                source_kind=r["source_kind"],
                source_id=r["source_id"],
                offset_days=r["offset_days"],
                notify_time=r["notify_time"],
                is_enabled=bool(r["is_enabled"]),
            )
            for r in rows
        ]

    def get_effective_offsets(self, source_kind: str, source_id: int) -> list[int]:
        rules = self.list_for_source(source_kind, source_id)
        if not rules:
            return list(DEFAULT_OFFSETS)
        # only enabled
        offsets = [r.offset_days for r in rules if r.is_enabled]
        if not offsets:
            return list(DEFAULT_OFFSETS)
        # dedup sort desc
        return sorted(set(offsets), reverse=True)

    def get_notify_time(self, source_kind: str, source_id: int) -> str | None:
        """First configured notify_time for a source (HH:MM), if any."""
        kind = source_kind.strip().upper()
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT notify_time FROM notification_rules "
                "WHERE source_kind=? AND source_id=? AND is_enabled=1 AND notify_time IS NOT NULL "
                "ORDER BY offset_days DESC LIMIT 1",
                (kind, source_id),
            ).fetchone()
        return row["notify_time"] if row else None

    def max_enabled_offset(self) -> int:
        """Largest offset any enabled rule asks for — drives the query horizon."""
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT MAX(offset_days) AS m FROM notification_rules WHERE is_enabled = 1"
            ).fetchone()
        return int(row["m"]) if row and row["m"] is not None else 0

    def set_rules(
        self, source_kind: str, source_id: int, offsets: list[int], notify_time: str | None = None
    ) -> None:
        kind = source_kind.strip().upper()
        if kind not in ("OFFICIAL", "MANUAL"):
            raise ValueError(f"Geçersiz source_kind: {source_kind}")
        # validate offsets
        clean = []
        for o in offsets:
            oi = int(o)
            if oi < 0 or oi > 365:
                raise ValueError(f"Geçersiz offset: {o}")
            clean.append(oi)
        clean = sorted(set(clean), reverse=True)
        if not clean:
            raise ValueError("En az bir offset gerekli.")

        with self.database.session() as connection:
            # delete old
            connection.execute(
                "DELETE FROM notification_rules WHERE source_kind=? AND source_id=?", (kind, source_id)
            )
            for off in clean:
                connection.execute(
                    "INSERT INTO notification_rules(source_kind, source_id, offset_days, notify_time) VALUES (?, ?, ?, ?)",
                    (kind, source_id, off, notify_time),
                )

    def set_enabled(self, rule_id: int, is_enabled: bool) -> bool:
        with self.database.session() as connection:
            cursor = connection.execute(
                "UPDATE notification_rules SET is_enabled=? WHERE id=?", (1 if is_enabled else 0, rule_id)
            )
            return cursor.rowcount > 0

    def delete_for_source(self, source_kind: str, source_id: int) -> int:
        kind = source_kind.strip().upper()
        with self.database.session() as connection:
            cursor = connection.execute(
                "DELETE FROM notification_rules WHERE source_kind=? AND source_id=?", (kind, source_id)
            )
            return cursor.rowcount
