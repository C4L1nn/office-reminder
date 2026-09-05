from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from database.connection import Database

class _Keep:
    """Sentinel: 'argument not supplied', so that an explicit None can mean 'clear'."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "KEEP"


KEEP = _Keep()

VALID_RECURRENCE_KINDS = {"NONE", "MONTHLY", "QUARTERLY", "SEMIANNUAL", "YEARLY", "CUSTOM"}
VALID_STATUSES = {"OPEN", "COMPLETED", "CANCELLED"}
COMPLETION_STATUSES = {"COMPLETED", "PAID", "FILED", "CANCELLED"}

MANUAL_CATEGORIES = {
    "GENERAL",
    "VEHICLE_INSPECTION",
    "TRAFFIC_INSURANCE",
    "KASKO",
    "RENT",
    "CONTRACT",
    "LICENSE",
    "SUBSCRIPTION",
    "SPECIAL_PAYMENT",
    "PERSONNEL_DOC",
    "CUSTOM_REMINDER",
}


def resolve_links(connection, company_id: int | None, vehicle_id: int | None) -> tuple[int | None, int | None]:
    """Validate and reconcile a reminder's company/vehicle pair.

    A vehicle always belongs to exactly one company, so the two fields cannot be
    set independently. Create and update share this helper so both enforce the
    same invariant:

    * an unknown company or vehicle id is rejected;
    * a vehicle from a different company is rejected;
    * a vehicle given without a company adopts that vehicle's company, rather
      than storing a reminder that shows a plate but no company.
    """
    if company_id is not None:
        if connection.execute("SELECT id FROM companies WHERE id = ?", (company_id,)).fetchone() is None:
            raise ValueError(f"Şirket bulunamadı: {company_id}")

    if vehicle_id is None:
        return company_id, None

    row = connection.execute("SELECT company_id FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    if row is None:
        raise ValueError(f"Araç bulunamadı: {vehicle_id}")

    owner = row["company_id"]
    if company_id is None:
        return owner, vehicle_id
    if owner != company_id:
        raise ValueError("Seçilen araç bu şirkete ait değil.")
    return company_id, vehicle_id


@dataclass(slots=True, frozen=True)
class ManualReminderRecord:
    id: int
    company_id: int | None
    company_name: str | None
    vehicle_id: int | None
    plate: str | None
    title: str
    category: str
    due_date: str
    due_time: str | None
    notes: str | None
    recurrence_kind: str
    recurrence_interval: int | None
    recurrence_json: str | None
    status: str
    parent_reminder_id: int | None

    @property
    def due_date_obj(self) -> date:
        return date.fromisoformat(self.due_date)


@dataclass(slots=True, frozen=True)
class CompletionOutcome:
    """What one completion attempt actually did."""

    completion_id: int
    next_reminder_id: int | None = None
    created_next: bool = False
    already_completed: bool = False


class ReminderRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ------------------------------------------------------------------ helpers
    def _validate_title(self, title: str) -> str:
        clean = title.strip()
        if not clean:
            raise ValueError("Hatırlatma başlığı boş olamaz.")
        if len(clean) > 255:
            raise ValueError("Başlık 255 karakteri aşamaz.")
        return clean

    def _validate_category(self, category: str) -> str:
        c = (category or "GENERAL").strip().upper()
        if not c:
            c = "GENERAL"
        # allow any but normalize; keep backwards compatible
        return c

    def _validate_recurrence(self, kind: str, interval: int | None) -> tuple[str, int | None]:
        k = (kind or "NONE").strip().upper()
        if k not in VALID_RECURRENCE_KINDS:
            raise ValueError(f"Geçersiz tekrar türü: {kind}")
        if k == "CUSTOM":
            if interval is not None and interval <= 0:
                raise ValueError("CUSTOM tekrar aralığı pozitif olmalı.")
        elif k != "NONE" and interval is not None and interval <= 0:
            raise ValueError("Tekrar aralığı pozitif olmalı.")
        return k, interval

    # ------------------------------------------------------------------ create
    def create_manual(
        self,
        *,
        title: str,
        due_date: date,
        company_id: int | None = None,
        vehicle_id: int | None = None,
        category: str = "GENERAL",
        due_time: str | None = None,
        notes: str | None = None,
        recurrence_kind: str = "NONE",
        recurrence_interval: int | None = None,
        recurrence_json: str | dict | None = None,
        parent_reminder_id: int | None = None,
        status: str = "OPEN",
    ) -> int:
        clean_title = self._validate_title(title)
        clean_category = self._validate_category(category)
        clean_recurrence, clean_interval = self._validate_recurrence(recurrence_kind, recurrence_interval)
        if status not in VALID_STATUSES:
            raise ValueError(f"Geçersiz status: {status}")
        if not isinstance(due_date, date):
            raise TypeError("due_date date tipinde olmalı.")

        # normalize recurrence_json
        rec_json: str | None = None
        if recurrence_json is not None:
            if isinstance(recurrence_json, dict):
                rec_json = json.dumps(recurrence_json, ensure_ascii=False)
            else:
                # validate json string
                json.loads(recurrence_json)
                rec_json = recurrence_json

        # due_time basic validation HH:MM
        if due_time is not None:
            due_time = due_time.strip()
            if due_time == "":
                due_time = None
            elif len(due_time) not in (5, 8) or due_time.count(":") < 1:
                raise ValueError("Saat formatı HH:MM olmalı.")

        with self.database.session() as connection:
            company_id, vehicle_id = resolve_links(connection, company_id, vehicle_id)

            cursor = connection.execute(
                """
                INSERT INTO manual_reminders
                    (company_id, vehicle_id, title, category, due_date, due_time, notes,
                     recurrence_kind, recurrence_interval, recurrence_json, status, parent_reminder_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company_id,
                    vehicle_id,
                    clean_title,
                    clean_category,
                    due_date.isoformat(),
                    due_time,
                    notes.strip() if isinstance(notes, str) and notes.strip() != "" else notes,
                    clean_recurrence,
                    clean_interval,
                    rec_json,
                    status,
                    parent_reminder_id,
                ),
            )
            return int(cursor.lastrowid)

    # ------------------------------------------------------------------ read
    def get_by_id(self, reminder_id: int) -> ManualReminderRecord | None:
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT mr.id, mr.company_id, c.name AS company_name,
                       mr.vehicle_id, v.plate,
                       mr.title, mr.category, mr.due_date, mr.due_time,
                       mr.notes, mr.recurrence_kind, mr.recurrence_interval,
                       mr.recurrence_json, mr.status, mr.parent_reminder_id
                FROM manual_reminders mr
                LEFT JOIN companies c ON c.id = mr.company_id
                LEFT JOIN vehicles v ON v.id = mr.vehicle_id
                WHERE mr.id = ?
                """,
                (reminder_id,),
            ).fetchone()
        if row is None:
            return None
        return ManualReminderRecord(
            id=row["id"],
            company_id=row["company_id"],
            company_name=row["company_name"],
            vehicle_id=row["vehicle_id"],
            plate=row["plate"],
            title=row["title"],
            category=row["category"],
            due_date=row["due_date"],
            due_time=row["due_time"],
            notes=row["notes"],
            recurrence_kind=row["recurrence_kind"],
            recurrence_interval=row["recurrence_interval"],
            recurrence_json=row["recurrence_json"],
            status=row["status"],
            parent_reminder_id=row["parent_reminder_id"],
        )

    def list_open(self, limit: int = 100) -> list[ManualReminderRecord]:
        return self.list_filtered(status="OPEN", limit=limit, order_by_due=True)

    def list_filtered(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        company_id: int | None = None,
        include_cancelled: bool = False,
        search: str | None = None,
        due_from: date | None = None,
        due_to: date | None = None,
        limit: int = 200,
        order_by_due: bool = True,
    ) -> list[ManualReminderRecord]:
        # Build query dynamically; use view for open, but for all we use base table
        # For simplicity query base table directly and join companies/vehicles
        where: list[str] = []
        params: list[Any] = []

        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"Geçersiz status filtresi: {status}")
            where.append("mr.status = ?")
            params.append(status)
        elif not include_cancelled:
            # default: exclude CANCELLED? but callers can specify
            pass

        if category is not None:
            where.append("mr.category = ?")
            params.append(category.strip().upper())

        if company_id is not None:
            where.append("mr.company_id IS ?")
            # IS handles NULL correctly, but for filtering non-null we use =
            # use simple = for specific id
            where[-1] = "mr.company_id = ?"
            params[-1] = company_id
        # company_id == None means no filter; to filter for "Genel" use explicit call with sentinel? Leave as is.

        if search:
            where.append("(mr.title LIKE ? OR COALESCE(mr.notes,'') LIKE ?)")
            like = f"%{search.strip()}%"
            params.extend([like, like])

        if due_from is not None:
            where.append("mr.due_date >= ?")
            params.append(due_from.isoformat())
        if due_to is not None:
            where.append("mr.due_date <= ?")
            params.append(due_to.isoformat())

        # If filtering by completion_records linkage, we exclude completed via view?
        # But status filter already handles manual status. For completeness, also exclude if completion_records exists?
        # For Faz1, status is authoritative for manual. Keep simple.

        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        order = "ORDER BY mr.due_date, COALESCE(mr.due_time,'23:59'), mr.id" if order_by_due else "ORDER BY mr.updated_at DESC"

        query = f"""
            SELECT mr.id, mr.company_id, c.name AS company_name,
                   mr.vehicle_id, v.plate,
                   mr.title, mr.category, mr.due_date, mr.due_time,
                   mr.notes, mr.recurrence_kind, mr.recurrence_interval,
                   mr.recurrence_json, mr.status, mr.parent_reminder_id
            FROM manual_reminders mr
            LEFT JOIN companies c ON c.id = mr.company_id
            LEFT JOIN vehicles v ON v.id = mr.vehicle_id
            {sql_where}
            {order}
            LIMIT ?
        """
        params.append(limit)

        with self.database.session() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()

        return [
            ManualReminderRecord(
                id=row["id"],
                company_id=row["company_id"],
                company_name=row["company_name"],
                vehicle_id=row["vehicle_id"],
                plate=row["plate"],
                title=row["title"],
                category=row["category"],
                due_date=row["due_date"],
                due_time=row["due_time"],
                notes=row["notes"],
                recurrence_kind=row["recurrence_kind"],
                recurrence_interval=row["recurrence_interval"],
                recurrence_json=row["recurrence_json"],
                status=row["status"],
                parent_reminder_id=row["parent_reminder_id"],
            )
            for row in rows
        ]

    def list_overdue(self, today: date | None = None, limit: int = 200) -> list[ManualReminderRecord]:
        from datetime import date as _date

        today = today or _date.today()
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT mr.id, mr.company_id, c.name AS company_name,
                       mr.vehicle_id, v.plate,
                       mr.title, mr.category, mr.due_date, mr.due_time,
                       mr.notes, mr.recurrence_kind, mr.recurrence_interval,
                       mr.recurrence_json, mr.status, mr.parent_reminder_id
                FROM manual_reminders mr
                LEFT JOIN companies c ON c.id = mr.company_id
                LEFT JOIN vehicles v ON v.id = mr.vehicle_id
                LEFT JOIN completion_records cr
                  ON cr.source_kind = 'MANUAL' AND cr.source_id = mr.id
                 AND ((cr.company_id IS NULL AND mr.company_id IS NULL) OR cr.company_id = mr.company_id)
                WHERE mr.status = 'OPEN'
                  AND mr.due_date < ?
                  AND cr.id IS NULL
                ORDER BY mr.due_date
                LIMIT ?
                """,
                (today.isoformat(), limit),
            ).fetchall()
        return [
            ManualReminderRecord(
                id=row["id"],
                company_id=row["company_id"],
                company_name=row["company_name"],
                vehicle_id=row["vehicle_id"],
                plate=row["plate"],
                title=row["title"],
                category=row["category"],
                due_date=row["due_date"],
                due_time=row["due_time"],
                notes=row["notes"],
                recurrence_kind=row["recurrence_kind"],
                recurrence_interval=row["recurrence_interval"],
                recurrence_json=row["recurrence_json"],
                status=row["status"],
                parent_reminder_id=row["parent_reminder_id"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ update
    def update(
        self,
        reminder_id: int,
        *,
        title: str | None = None,
        due_date: date | None = None,
        company_id: int | None | object = KEEP,
        vehicle_id: int | None | object = KEEP,
        category: str | None = None,
        due_time: str | None | object = KEEP,
        notes: str | None | object = KEEP,
        recurrence_kind: str | None = None,
        recurrence_interval: int | None = None,
        recurrence_json: str | dict | None | object = KEEP,
        status: str | None = None,
    ) -> bool:
        """Update a manual reminder.

        Nullable links (company, vehicle, time, notes, recurrence payload) use the
        KEEP sentinel as their default, so passing an explicit ``None`` clears the
        field while omitting the argument leaves it untouched. Without that
        distinction a reminder could never be detached from a company or vehicle.
        """
        existing = self.get_by_id(reminder_id)
        if existing is None:
            return False

        new_title = self._validate_title(title) if title is not None else existing.title
        new_category = self._validate_category(category) if category is not None else existing.category
        new_recurrence = recurrence_kind if recurrence_kind is not None else existing.recurrence_kind
        new_interval = recurrence_interval if recurrence_kind is not None else existing.recurrence_interval
        new_recurrence, new_interval = self._validate_recurrence(new_recurrence, new_interval)
        new_status = status if status is not None else existing.status
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Geçersiz status: {new_status}")
        new_due_date = due_date.isoformat() if due_date is not None else existing.due_date

        if recurrence_json is KEEP:
            new_rec_json = existing.recurrence_json
        elif isinstance(recurrence_json, dict):
            new_rec_json = json.dumps(recurrence_json, ensure_ascii=False)
        elif isinstance(recurrence_json, str) and recurrence_json.strip():
            json.loads(recurrence_json)
            new_rec_json = recurrence_json
        else:
            new_rec_json = None
        # A non-recurring reminder must not carry a stale recurrence payload.
        if new_recurrence == "NONE":
            new_rec_json = None
            new_interval = None

        effective_company = existing.company_id if company_id is KEEP else company_id
        effective_vehicle = existing.vehicle_id if vehicle_id is KEEP else vehicle_id
        effective_notes = existing.notes if notes is KEEP else notes

        if due_time is KEEP:
            effective_due_time = existing.due_time
        elif due_time is None or not str(due_time).strip():
            effective_due_time = None
        else:
            effective_due_time = str(due_time).strip()
            if len(effective_due_time) not in (5, 8):
                raise ValueError("Saat formatı HH:MM olmalı.")

        with self.database.session() as connection:
            effective_company, effective_vehicle = resolve_links(
                connection, effective_company, effective_vehicle
            )

            cursor = connection.execute(
                """
                UPDATE manual_reminders
                SET company_id = ?, vehicle_id = ?, title = ?, category = ?, due_date = ?, due_time = ?, notes = ?,
                    recurrence_kind = ?, recurrence_interval = ?, recurrence_json = ?, status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    effective_company,
                    effective_vehicle,
                    new_title,
                    new_category,
                    new_due_date,
                    effective_due_time,
                    effective_notes,
                    new_recurrence,
                    new_interval,
                    new_rec_json,
                    new_status,
                    reminder_id,
                ),
            )
            return cursor.rowcount > 0

    # ------------------------------------------------------------------ completion
    def complete_with_next_occurrence(
        self,
        *,
        reminder_id: int,
        company_id: int | None = None,
        completion_status: str = "COMPLETED",
        notes: str | None = None,
        amount: float | None = None,
        next_due: date | None = None,
        notification_offsets: list[int] | None = None,
        notify_time: str | None = None,
    ) -> CompletionOutcome:
        """Complete a manual reminder and roll it forward, atomically.

        The completion record, the reminder's status, the next occurrence and
        that occurrence's notification rules are written on one connection, so a
        failure anywhere leaves none of them behind. Previously the next
        occurrence was created first, in its own transaction, and a failing
        completion left an orphan child.

        The operation is idempotent in both directions that matter:

        * completing an already-completed reminder returns the existing
          completion and changes nothing;
        * a next occurrence that already exists for this (parent, due date) is
          reused instead of duplicated, so complete → undo → complete still
          yields exactly one child.

        Notification rules for the child are written here rather than through
        the rule repository because they have to share this transaction.
        """
        if completion_status not in COMPLETION_STATUSES:
            raise ValueError(f"Geçersiz completion_status: {completion_status}")

        with self.database.session() as connection:
            parent = connection.execute(
                "SELECT id, title, company_id, vehicle_id, category, due_time, notes, "
                "recurrence_kind, recurrence_interval, recurrence_json "
                "FROM manual_reminders WHERE id = ?",
                (reminder_id,),
            ).fetchone()
            if parent is None:
                raise ValueError(f"Manuel hatırlatma bulunamadı: {reminder_id}")

            existing = self._find_completion(connection, reminder_id, company_id)
            if existing is not None:
                return CompletionOutcome(completion_id=int(existing), already_completed=True)

            cursor = connection.execute(
                """
                INSERT INTO completion_records
                    (source_kind, source_id, company_id, completion_status, notes, amount)
                VALUES ('MANUAL', ?, ?, ?, ?, ?)
                """,
                (reminder_id, company_id, completion_status, notes, amount),
            )
            completion_id = int(cursor.lastrowid)

            connection.execute(
                "UPDATE manual_reminders SET status='COMPLETED', updated_at=CURRENT_TIMESTAMP WHERE id = ?",
                (reminder_id,),
            )

            if next_due is None:
                return CompletionOutcome(completion_id=completion_id)

            stamp = next_due.isoformat()
            twin = connection.execute(
                "SELECT id FROM manual_reminders WHERE parent_reminder_id = ? AND due_date = ?",
                (reminder_id, stamp),
            ).fetchone()
            if twin is not None:
                return CompletionOutcome(
                    completion_id=completion_id, next_reminder_id=int(twin["id"])
                )

            child = connection.execute(
                """
                INSERT INTO manual_reminders
                    (company_id, vehicle_id, title, category, due_date, due_time, notes,
                     recurrence_kind, recurrence_interval, recurrence_json, status, parent_reminder_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
                """,
                (
                    parent["company_id"],
                    parent["vehicle_id"],
                    parent["title"],
                    parent["category"],
                    stamp,
                    parent["due_time"],
                    parent["notes"],
                    parent["recurrence_kind"],
                    parent["recurrence_interval"],
                    parent["recurrence_json"],
                    reminder_id,
                ),
            )
            next_id = int(child.lastrowid)

            if notification_offsets:
                for offset in sorted(set(notification_offsets), reverse=True):
                    connection.execute(
                        "INSERT INTO notification_rules(source_kind, source_id, offset_days, notify_time) "
                        "VALUES ('MANUAL', ?, ?, ?)",
                        (next_id, int(offset), notify_time),
                    )

            return CompletionOutcome(
                completion_id=completion_id, next_reminder_id=next_id, created_next=True
            )

    @staticmethod
    def _find_completion(connection, reminder_id: int, company_id: int | None) -> int | None:
        if company_id is None:
            row = connection.execute(
                "SELECT id FROM completion_records "
                "WHERE source_kind='MANUAL' AND source_id=? AND company_id IS NULL",
                (reminder_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT id FROM completion_records "
                "WHERE source_kind='MANUAL' AND source_id=? AND company_id=?",
                (reminder_id, company_id),
            ).fetchone()
        return int(row["id"]) if row else None

    def find_occurrence(self, parent_reminder_id: int, due_date: date) -> int | None:
        """The child already generated for this (parent, due date), if any."""
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT id FROM manual_reminders WHERE parent_reminder_id = ? AND due_date = ?",
                (parent_reminder_id, due_date.isoformat()),
            ).fetchone()
        return int(row["id"]) if row else None

    def set_status(self, reminder_id: int, status: str) -> bool:
        if status not in VALID_STATUSES:
            raise ValueError(f"Geçersiz status: {status}")
        with self.database.session() as connection:
            cursor = connection.execute(
                "UPDATE manual_reminders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, reminder_id),
            )
            return cursor.rowcount > 0

    def delete(self, reminder_id: int) -> bool:
        with self.database.session() as connection:
            cursor = connection.execute("DELETE FROM manual_reminders WHERE id = ?", (reminder_id,))
            return cursor.rowcount > 0

    def count_open(self) -> int:
        with self.database.session() as connection:
            row = connection.execute("SELECT COUNT(*) AS c FROM manual_reminders WHERE status='OPEN'").fetchone()
            return int(row["c"]) if row else 0
