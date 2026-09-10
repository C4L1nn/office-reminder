from __future__ import annotations

import logging

import json
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from database.connection import Database
from database.repositories.completions import CompletionRepository
from database.repositories.notification_rules import NotificationRuleRepository
from database.repositories.reminders import KEEP, ReminderRepository
from services.eligibility_service import EligibilityService

DEFAULT_NOTIFICATION_OFFSETS = (14, 7, 3, 1, 0)
# Overdue work older than this is history, not an actionable to-do; without a
# floor a freshly onboarded company would show every past event as overdue.
DEFAULT_OVERDUE_LOOKBACK_DAYS = 180


logger = logging.getLogger("office_reminder.reminders")


@dataclass(slots=True, frozen=True)
class DueItem:
    source_kind: str  # OFFICIAL | MANUAL
    source_id: int
    company_id: int | None
    company_name: str | None
    title: str
    due_date: date
    source_label: str  # GIB/SGK/MANUEL
    category: str | None = None
    due_time: str | None = None
    recurrence_kind: str | None = None
    vehicle_id: int | None = None
    plate: str | None = None
    obligation_code: str | None = None
    period_label: str | None = None

    @property
    def key(self) -> tuple[str, int, int | None]:
        return (self.source_kind, self.source_id, self.company_id)

    @property
    def days_remaining(self) -> int:
        return (self.due_date - date.today()).days

    def days_remaining_on(self, today: date) -> int:
        return (self.due_date - today).days

    @property
    def is_overdue(self) -> bool:
        return self.days_remaining < 0

    @property
    def is_today(self) -> bool:
        return self.days_remaining == 0

    @property
    def subject(self) -> str:
        """Company (and plate, when the item belongs to a vehicle) on one line."""
        parts = [self.company_name or "Genel"]
        if self.plate:
            parts.append(self.plate)
        return " · ".join(parts)


@dataclass(slots=True, frozen=True)
class MiniCounterSnapshot:
    """One row for the always-on-top mini counter.

    `item` is the single most urgent row (oldest overdue, else nearest due),
    `extra` counts everything else shown as "+N iş daha" — counted here so the
    widget never has to recount from the item alone. Anything else the card
    might want later belongs in `get_dashboard_counts`, which already has it.
    """

    item: DueItem | None
    extra: int


def _parse_tags(raw) -> list[str] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, list) else None


def _add_months(d: date, months: int) -> date:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    last_day = monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


def compute_next_due_date(
    current_due: date,
    recurrence_kind: str,
    recurrence_interval: int | None = None,
    recurrence_json: str | dict | None = None,
) -> date | None:
    kind = (recurrence_kind or "NONE").upper()
    if kind == "NONE":
        return None
    if kind == "MONTHLY":
        return _add_months(current_due, 1)
    if kind == "QUARTERLY":
        return _add_months(current_due, 3)
    if kind == "SEMIANNUAL":
        return _add_months(current_due, 6)
    if kind == "YEARLY":
        return _add_months(current_due, 12)
    if kind == "CUSTOM":
        # recurrence_json could be {"interval_months": 2} or {"interval_days": 45}
        interval = recurrence_interval
        payload: dict = {}
        if isinstance(recurrence_json, str) and recurrence_json.strip():
            try:
                payload = json.loads(recurrence_json)
            except ValueError:
                payload = {}
        elif isinstance(recurrence_json, dict):
            payload = recurrence_json

        # A malformed payload falls through to the interval, then to one month:
        # a recurring reminder must still produce a next date.
        if "interval_days" in payload:
            try:
                days = int(payload["interval_days"])
            except (TypeError, ValueError):
                days = 0
            if days > 0:
                return current_due + timedelta(days=days)
        if "interval_months" in payload:
            try:
                months = int(payload["interval_months"])
            except (TypeError, ValueError):
                months = 0
            if months > 0:
                return _add_months(current_due, months)
        # fallback to interval as months
        if interval and interval > 0:
            return _add_months(current_due, interval)
        # default 1 month if custom without spec
        return _add_months(current_due, 1)
    return None


class ReminderService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.reminders = ReminderRepository(database)
        self.completions = CompletionRepository(database)
        self.notification_rules = NotificationRuleRepository(database)
        self.eligibility = EligibilityService(database)

    # ------------------------------------------------------------------ CRUD wrappers
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
        notification_offsets: list[int] | None = None,
        notify_time: str | None = None,
    ) -> int:
        rid = self.reminders.create_manual(
            title=title,
            due_date=due_date,
            company_id=company_id,
            vehicle_id=vehicle_id,
            category=category,
            due_time=due_time,
            notes=notes,
            recurrence_kind=recurrence_kind,
            recurrence_interval=recurrence_interval,
            recurrence_json=recurrence_json,
        )
        # On create there is nothing to preserve, so None genuinely means
        # "use the global defaults".
        self._apply_notification_rules(rid, notification_offsets, notify_time)
        return rid

    def _apply_notification_rules(
        self,
        reminder_id: int,
        offsets: list[int] | None | object = KEEP,
        notify_time: str | None | object = KEEP,
    ) -> None:
        """Persist per-reminder notification rules.

        Three states have to stay distinct, which is why KEEP exists:

        * ``KEEP``  — the caller did not mention this setting; leave it alone.
        * ``None``  — the caller cleared it (empty field in the dialog).
        * a value   — the caller set it.

        Treating a missing argument as ``None`` is what used to wipe a
        reminder's 90-day rule when only its title was edited.
        """
        if offsets is KEEP and notify_time is KEEP:
            return

        if offsets is KEEP:
            current = self.notification_rules.list_for_source("MANUAL", reminder_id)
            effective = [rule.offset_days for rule in current] or None
        else:
            effective = offsets

        if notify_time is KEEP:
            resolved_time = self.notification_rules.get_notify_time("MANUAL", reminder_id)
        else:
            resolved_time = notify_time

        if not effective and resolved_time is None:
            # Nothing custom left to store: fall back to the global defaults.
            self.notification_rules.delete_for_source("MANUAL", reminder_id)
            return

        self.notification_rules.set_rules(
            "MANUAL",
            reminder_id,
            effective or list(DEFAULT_NOTIFICATION_OFFSETS),
            notify_time=resolved_time,
        )

    def quick_add(self, *, title: str, due_date: date, company_id: int | None = None) -> int:
        return self.create_manual(title=title, due_date=due_date, company_id=company_id, category="GENERAL")

    def update_manual(self, reminder_id: int, **kwargs) -> bool:
        """Update a reminder. Omitted notification settings are left untouched.

        The dialog always supplies both notification keys, so a user who clears
        the field really does clear the rule; a caller that only changes the
        title (or any other field) keeps whatever was configured.
        """
        offsets = kwargs.pop("notification_offsets", KEEP)
        notify_time = kwargs.pop("notify_time", KEEP)
        ok = self.reminders.update(reminder_id, **kwargs)
        if ok:
            self._apply_notification_rules(reminder_id, offsets, notify_time)
        return ok

    def delete_manual(self, reminder_id: int) -> bool:
        # cleanup rules + deliveries + completions? keep deliveries for audit
        self.notification_rules.delete_for_source("MANUAL", reminder_id)
        # Files live outside the database, so nothing cascades them away; a
        # deleted reminder would otherwise leave its copies on disk forever.
        try:
            from services.attachment_service import AttachmentService

            AttachmentService(self.database).remove_all_for("MANUAL", reminder_id)
        except Exception:
            logger.warning("Ekler silinemedi: %s", reminder_id, exc_info=True)
        return self.reminders.delete(reminder_id)

    def get_manual(self, reminder_id: int):
        return self.reminders.get_by_id(reminder_id)

    # ------------------------------------------------------------------ completion
    def complete(
        self,
        *,
        source_kind: str,
        source_id: int,
        company_id: int | None = None,
        completion_status: str = "COMPLETED",
        notes: str | None = None,
        amount: float | None = None,
    ) -> int:
        """Mark an obligation done; roll a recurring reminder forward.

        For a manual reminder the completion record, the status change, the next
        occurrence and its notification rules are written in one transaction by
        the repository, so completing twice — or completing, undoing and
        completing again — can never leave a duplicate or orphaned occurrence.
        """
        kind = source_kind.strip().upper()
        if kind != "MANUAL":
            return self.completions.create(
                source_kind=kind,
                source_id=source_id,
                company_id=company_id,
                completion_status=completion_status,
                notes=notes,
                amount=amount,
            )

        record = self.reminders.get_by_id(source_id)
        if record is None:
            raise ValueError(f"Manuel hatırlatma bulunamadı: {source_id}")

        next_due = None
        offsets: list[int] | None = None
        notify_time: str | None = None
        if record.recurrence_kind != "NONE":
            next_due = compute_next_due_date(
                date.fromisoformat(record.due_date),
                record.recurrence_kind,
                record.recurrence_interval,
                record.recurrence_json,
            )
            # Only a reminder with its own rules passes them on; one using the
            # global defaults should keep using them after rolling forward.
            configured = self.notification_rules.list_for_source("MANUAL", source_id)
            if configured:
                offsets = [rule.offset_days for rule in configured]
                # The reminder's own notify_time, not its due_time: those are
                # different things (when to warn vs. when it is due).
                notify_time = self.notification_rules.get_notify_time("MANUAL", source_id)

        outcome = self.reminders.complete_with_next_occurrence(
            reminder_id=source_id,
            company_id=company_id,
            completion_status=completion_status.strip().upper() if completion_status else "COMPLETED",
            notes=notes,
            amount=amount,
            next_due=next_due,
            notification_offsets=offsets,
            notify_time=notify_time,
        )
        return outcome.completion_id

    def undo_complete(self, source_kind: str, source_id: int, company_id: int | None = None) -> bool:
        return self.completions.undo(source_kind, source_id, company_id)

    def is_completed(self, source_kind: str, source_id: int, company_id: int | None = None) -> bool:
        return self.completions.is_completed(source_kind, source_id, company_id)

    # ------------------------------------------------------------------ listing / dashboard queries
    def list_upcoming(self, *, horizon_days: int = 30, today: date | None = None, company_id: int | None = None) -> list[DueItem]:
        return self.list_due(horizon_days=horizon_days, today=today, company_id=company_id, include_overdue=False)

    def list_month(
        self,
        year: int,
        month: int,
        *,
        company_id: int | None = None,
        source_kind_filter: str | None = None,
        include_completed: bool = True,
    ) -> list[DueItem]:
        """Everything falling due inside one calendar month.

        A thin window over `list_due`: anchoring it at the first of the month
        and sizing the horizon to the month gives the same rows the rest of the
        app sees, rather than a second query that could drift from it.
        """
        import calendar as _calendar

        first = date(year, month, 1)
        last = date(year, month, _calendar.monthrange(year, month)[1])
        return self.list_due(
            horizon_days=(last - first).days,
            today=first,
            company_id=company_id,
            include_overdue=False,
            include_completed=include_completed,
            source_kind_filter=source_kind_filter,
        )

    def list_due(
        self,
        *,
        horizon_days: int = 30,
        today: date | None = None,
        company_id: int | None = None,
        include_overdue: bool = False,
        include_completed: bool = False,
        category: str | None = None,
        search: str | None = None,
        source_kind_filter: str | None = None,  # OFFICIAL | MANUAL | None (both)
        overdue_lookback_days: int = DEFAULT_OVERDUE_LOOKBACK_DAYS,
    ) -> list[DueItem]:
        today = today or date.today()
        end = today + timedelta(days=horizon_days)
        # An unbounded lower edge would drag in every past event forever; overdue
        # work older than the lookback window is history, not a to-do.
        start = today - timedelta(days=overdue_lookback_days) if include_overdue else today

        wants = (source_kind_filter or "").upper()
        want_official = wants in ("", "OFFICIAL")
        want_manual = wants in ("", "MANUAL")

        official_rows: list = []
        manual_rows: list = []

        with self.database.session() as connection:
            if want_official:
                q = """
                    SELECT v.company_id, v.company_name, v.official_event_id, v.title,
                           v.due_date, v.source_kind, v.due_time, v.period_label,
                           v.eligibility_tags, v.obligation_code
                    FROM v_active_official_company_events v
                    WHERE v.due_date >= ? AND v.due_date <= ?
                      AND (v.due_date >= ? OR v.due_date >= v.obligation_tracked_from)
                """
                # Past-dated rows are only included once the obligation was tracked.
                params: list = [start.isoformat(), end.isoformat(), today.isoformat()]
                if company_id is not None:
                    q += " AND v.company_id = ?"
                    params.append(company_id)
                if search:
                    q += " AND v.title LIKE ?"
                    params.append(f"%{search}%")
                official_rows = self._filter_eligible(connection.execute(q, tuple(params)).fetchall())

            if want_manual:
                mq = """
                    SELECT mr.id AS manual_reminder_id, mr.company_id, c.name AS company_name,
                           mr.vehicle_id, veh.plate,
                           mr.title, mr.due_date, mr.due_time, mr.category, mr.recurrence_kind
                    FROM manual_reminders mr
                    LEFT JOIN companies c ON c.id = mr.company_id
                    LEFT JOIN vehicles veh ON veh.id = mr.vehicle_id
                    LEFT JOIN completion_records cr
                      ON cr.source_kind='MANUAL' AND cr.source_id=mr.id
                     AND ((cr.company_id IS NULL AND mr.company_id IS NULL) OR cr.company_id = mr.company_id)
                    WHERE mr.status='OPEN' AND cr.id IS NULL
                      AND mr.due_date >= ? AND mr.due_date <= ?
                """
                mparams: list = [start.isoformat(), end.isoformat()]
                if company_id is not None:
                    mq += " AND mr.company_id = ?"
                    mparams.append(company_id)
                if category is not None:
                    mq += " AND mr.category = ?"
                    mparams.append(category.strip().upper())
                if search:
                    mq += " AND (mr.title LIKE ? OR COALESCE(veh.plate,'') LIKE ?)"
                    mparams.extend([f"%{search}%", f"%{search}%"])
                mq += " ORDER BY mr.due_date, COALESCE(mr.due_time,'23:59')"
                manual_rows = connection.execute(mq, tuple(mparams)).fetchall()

        items = [self._official_item(row) for row in official_rows]
        items.extend(self._manual_item(row) for row in manual_rows)
        return sorted(items, key=lambda item: (item.due_date, item.title.casefold()))

    def _filter_eligible(self, rows: list) -> list:
        """Drop official rows the company's profile does not qualify it for.

        The profile settings for every pair in this batch are read in one
        query first; the check itself is unchanged.
        """
        needed = {
            (row["company_id"], row["obligation_code"])
            for row in rows
            if _parse_tags(row["eligibility_tags"])
            and row["obligation_code"] in self.eligibility.PROFILE_REQUIRED
        }
        settings_map = self.eligibility.load_settings(needed) if needed else {}

        kept = []
        for row in rows:
            tags = _parse_tags(row["eligibility_tags"])
            if tags and row["obligation_code"] in self.eligibility.PROFILE_REQUIRED:
                eligible, _reason = self.eligibility.is_event_eligible(
                    row["company_id"],
                    row["obligation_code"],
                    tags,
                    row["source_kind"],
                    settings_map=settings_map,
                )
                if not eligible:
                    continue
            kept.append(row)
        return kept

    @staticmethod
    def _official_item(row) -> DueItem:
        return DueItem(
            source_kind="OFFICIAL",
            source_id=row["official_event_id"],
            company_id=row["company_id"],
            company_name=row["company_name"],
            title=row["title"],
            due_date=date.fromisoformat(row["due_date"]),
            source_label=row["source_kind"],
            due_time=row["due_time"],
            obligation_code=row["obligation_code"],
            period_label=row["period_label"],
        )

    @staticmethod
    def _manual_item(row) -> DueItem:
        return DueItem(
            source_kind="MANUAL",
            source_id=row["manual_reminder_id"],
            company_id=row["company_id"],
            company_name=row["company_name"],
            title=row["title"],
            due_date=date.fromisoformat(row["due_date"]),
            source_label="MANUEL",
            category=row["category"],
            due_time=row["due_time"],
            recurrence_kind=row["recurrence_kind"],
            vehicle_id=row["vehicle_id"],
            plate=row["plate"],
        )

    def list_today(self, today: date | None = None, company_id: int | None = None) -> list[DueItem]:
        today = today or date.today()
        return self.list_due(horizon_days=0, today=today, company_id=company_id, include_overdue=False)

    def list_overdue(
        self,
        today: date | None = None,
        company_id: int | None = None,
        lookback_days: int = DEFAULT_OVERDUE_LOOKBACK_DAYS,
    ) -> list[DueItem]:
        today = today or date.today()
        floor = today - timedelta(days=lookback_days)
        items: list[DueItem] = []

        with self.database.session() as connection:
            # An obligation is only late if it was already being tracked when it
            # came due; events from before the company was onboarded are history.
            q = """
                SELECT v.company_id, v.company_name, v.official_event_id, v.title, v.due_date,
                       v.source_kind, v.due_time, v.period_label, v.eligibility_tags, v.obligation_code
                FROM v_active_official_company_events v
                WHERE v.due_date < ?
                  AND v.due_date >= ?
                  AND v.due_date >= v.obligation_tracked_from
            """
            params: list = [today.isoformat(), floor.isoformat()]
            if company_id is not None:
                q += " AND v.company_id = ?"
                params.append(company_id)
            q += " ORDER BY v.due_date"
            items.extend(
                self._official_item(row)
                for row in self._filter_eligible(connection.execute(q, tuple(params)).fetchall())
            )

        for rec in self.reminders.list_overdue(today=today):
            if company_id is not None and rec.company_id != company_id:
                continue
            items.append(
                DueItem(
                    source_kind="MANUAL",
                    source_id=rec.id,
                    company_id=rec.company_id,
                    company_name=rec.company_name,
                    title=rec.title,
                    due_date=date.fromisoformat(rec.due_date),
                    source_label="MANUEL",
                    category=rec.category,
                    due_time=rec.due_time,
                    recurrence_kind=rec.recurrence_kind,
                    vehicle_id=rec.vehicle_id,
                    plate=rec.plate,
                )
            )
        return sorted(items, key=lambda i: (i.due_date, i.title.casefold()))

    def list_this_month(self, today: date | None = None, company_id: int | None = None) -> list[DueItem]:
        today = today or date.today()
        from calendar import monthrange

        last = monthrange(today.year, today.month)[1]
        end = date(today.year, today.month, last)
        horizon = (end - today).days
        # include overdue within month? No, only from today to month end plus include overdue if they are this month?
        # Return today..end plus overdue this month (overdue already earlier)
        items = self.list_due(horizon_days=horizon, today=today, company_id=company_id, include_overdue=False)
        # also add overdue this month (due in this month but before today)
        overdue = [i for i in self.list_overdue(today=today, company_id=company_id) if i.due_date.month == today.month and i.due_date.year == today.year]
        # merge
        combined = { (i.source_kind, i.source_id, i.company_id): i for i in items }
        for o in overdue:
            combined[(o.source_kind, o.source_id, o.company_id)] = o
        return sorted(combined.values(), key=lambda i: (i.due_date, i.title.casefold()))

    def get_dashboard_counts(self, today: date | None = None, company_id: int | None = None) -> dict:
        today = today or date.today()
        upcoming = self.list_due(horizon_days=30, today=today, company_id=company_id)
        overdue = self.list_overdue(today=today, company_id=company_id)
        today_items = self.list_today(today=today, company_id=company_id)
        this_month = self.list_this_month(today=today, company_id=company_id)
        return {
            "today": len(today_items),
            "upcoming": len(upcoming),
            "overdue": len(overdue),
            "this_month": len(this_month),
            "today_items": today_items,
            "upcoming_items": upcoming,
            "overdue_items": overdue,
            "this_month_items": this_month,
        }

    def get_mini_counter_snapshot(self, today: date | None = None) -> MiniCounterSnapshot:
        """Pick the single row the mini counter shows.

        Priority is oldest overdue first, otherwise nearest due — the same
        `(due_date, title)` order every list in the app uses, so the card can
        never disagree with the dashboard about what is "most urgent".
        """
        today = today or date.today()
        overdue = self.list_overdue(today=today)
        upcoming = self.list_due(horizon_days=30, today=today, include_overdue=False)
        if overdue:
            # list_overdue is already sorted oldest-first.
            return MiniCounterSnapshot(
                item=overdue[0], extra=len(overdue) - 1 + len(upcoming)
            )
        if upcoming:
            return MiniCounterSnapshot(item=upcoming[0], extra=len(upcoming) - 1)
        return MiniCounterSnapshot(item=None, extra=0)

    def search_manual(self, **kwargs):
        return self.reminders.list_filtered(**kwargs)
