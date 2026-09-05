from __future__ import annotations

import logging
from datetime import date, datetime, time

from PySide6.QtCore import QObject, Signal

from database.connection import Database
from database.repositories.notification_rules import NotificationRuleRepository
from database.repositories.notifications import NotificationInboxRepository
from services.formatting import due_sentence, long_date, day_month
from services.notification_adapter import (
    CompositeNotificationAdapter,
    NotificationPayload,
    QtTrayNotificationAdapter,
    WindowsToastNotificationAdapter,
)
from services.reminder_service import DEFAULT_NOTIFICATION_OFFSETS, DueItem, ReminderService

logger = logging.getLogger("office_reminder.notifications")

# Overdue items are re-announced once a day; beyond this they stay on the
# dashboard but stop generating toasts, so the tray never turns into spam.
OVERDUE_NOTIFY_LIMIT_DAYS = 30

#: Delivery channels. IN_APP always succeeds; WINDOWS may be suppressed by the OS.
IN_APP = "IN_APP"
WINDOWS = "WINDOWS"


class NotificationService(QObject):
    """Decides what to announce, delivers it on two channels, records each one.

    Channels, in order of reliability:

    * ``IN_APP``  — the guaranteed one. Every announcement is written to the
      inbox and stays unread until the user looks at it. Windows "Focus
      Assist" / Do Not Disturb cannot suppress it, which is why it exists:
      a silenced toast used to mean the reminder was simply never seen.
    * ``WINDOWS`` — best effort. If the toast cannot be shown it is retried on
      the next check, without duplicating the inbox entry.

    The delivery ledger is therefore per channel. The other two rules still
    hold: a channel is only marked delivered once it actually delivered, and
    the lookahead window follows the configured offsets rather than a fixed 30
    days.
    """

    #: Emitted on the Qt thread after new notifications land in the inbox.
    inbox_changed = Signal(int)  # unread count

    def __init__(
        self,
        database: Database,
        reminder_service: ReminderService,
        tray_icon=None,
        adapter=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.reminder_service = reminder_service
        self.tray_icon = tray_icon
        self._rule_repo = NotificationRuleRepository(database)
        self.inbox = NotificationInboxRepository(database)
        self.adapter = adapter if adapter is not None else self._build_adapter(tray_icon)

    @staticmethod
    def _build_adapter(tray_icon):
        if tray_icon is None:
            return None
        try:
            native = WindowsToastNotificationAdapter()
            tray = QtTrayNotificationAdapter(tray_icon)
            if native.is_available():
                return CompositeNotificationAdapter(native, tray)
            return tray
        except Exception:
            logger.warning("Native toast adapter unavailable, falling back to tray", exc_info=True)
            return QtTrayNotificationAdapter(tray_icon)

    # ------------------------------------------------------------------ main loop
    def check_and_notify(self, today: date | None = None, now: datetime | None = None) -> int:
        if not self.is_enabled():
            return 0

        today = today or date.today()
        now = now or datetime.now()
        delivered = 0

        horizon = self.notification_horizon_days()
        upcoming = self.reminder_service.list_due(horizon_days=horizon, today=today, include_overdue=False)
        overdue = self.reminder_service.list_overdue(today=today, lookback_days=OVERDUE_NOTIFY_LIMIT_DAYS)

        seen: set[tuple] = set()
        for item in upcoming + overdue:
            if item.key in seen:
                continue
            seen.add(item.key)

            offset = (item.due_date - today).days
            if offset >= 0:
                if offset not in self._effective_offsets(item):
                    continue
                if not self._time_reached(item, now):
                    continue
                key = f"DUE_MINUS_{offset}"
            else:
                key = f"OVERDUE_{today.isoformat()}"

            if self._announce_item(item, offset, key):
                delivered += 1

        if delivered:
            self.inbox_changed.emit(self.unread_count())
        return delivered

    def _announce_item(self, item: DueItem, offset: int, key: str) -> bool:
        """Deliver one reminder on both channels. True if anything was new."""
        title, body, severity = self._compose(item, offset)
        kind = "DUE" if offset >= 0 else "OVERDUE"
        new_for_user = False

        if not self._was_delivered(item, key, IN_APP):
            self.inbox.add(
                kind=kind,
                severity=severity,
                title=title,
                body=body,
                source_kind=item.source_kind,
                source_id=item.source_id,
                company_id=item.company_id,
                due_date=item.due_date.isoformat(),
                notification_key=key,
            )
            self._mark_delivered(item, key, IN_APP)
            new_for_user = True

        if not self._was_delivered(item, key, WINDOWS):
            payload = NotificationPayload(
                title=title, body=body, tag=f"{item.source_kind}_{item.source_id}_{key}"
            )
            if self._emit(payload):
                self._mark_delivered(item, key, WINDOWS)

        return new_for_user

    @staticmethod
    def _compose(item: DueItem, offset: int) -> tuple[str, str, str]:
        lines = [item.subject, due_sentence(offset, item.due_date)]
        if item.period_label and item.source_kind == "OFFICIAL":
            lines.insert(1, item.period_label)
        if offset < 0:
            return f"Gecikti: {item.title}", "\n".join(lines), "DANGER"
        if offset == 0:
            return item.title, "\n".join(lines), "WARNING"
        return item.title, "\n".join(lines), "INFO"

    def unread_count(self) -> int:
        try:
            return self.inbox.unread_count()
        except Exception:
            logger.warning("Unread count unavailable", exc_info=True)
            return 0

    def notification_horizon_days(self) -> int:
        """Far enough ahead to catch the longest configured reminder offset."""
        base = max(DEFAULT_NOTIFICATION_OFFSETS)
        try:
            configured = self._rule_repo.max_enabled_offset()
        except Exception:
            logger.warning("Could not read notification rules, using default horizon", exc_info=True)
            configured = 0
        return max(30, base, configured)

    # ------------------------------------------------------------------ official revisions
    def notify_official_revision(
        self,
        *,
        event_id: int,
        company_id: int | None,
        company_name: str | None,
        obligation_name: str,
        old_due: date,
        new_due: date,
        source: str,
        revision_id: int,
    ) -> bool:
        """Announce that an official due date moved. Returns True if shown."""
        key = f"REVISION_{revision_id}"
        item_key = _DeliveryKey("OFFICIAL", event_id, company_id)
        subject = " · ".join(p for p in [company_name, obligation_name] if p)
        body = f"{subject}\n{day_month(old_due)} → {day_month(new_due)}\nKaynak: {source}"
        title = "Resmî tarih değişti"
        new_for_user = False

        if not self._was_delivered(item_key, key, IN_APP):
            self.inbox.add(
                kind="OFFICIAL_REVISION",
                severity="WARNING",
                title=title,
                body=body,
                source_kind="OFFICIAL",
                source_id=event_id,
                company_id=company_id,
                due_date=new_due.isoformat(),
                notification_key=key,
            )
            self._mark_delivered(item_key, key, IN_APP, due_date=new_due)
            new_for_user = True

        if not self._was_delivered(item_key, key, WINDOWS):
            if self._emit(
                NotificationPayload(title=title, body=body, tag=f"REV_{revision_id}_{company_id}")
            ):
                self._mark_delivered(item_key, key, WINDOWS, due_date=new_due)

        if new_for_user:
            self.inbox_changed.emit(self.unread_count())
        return new_for_user

    # ------------------------------------------------------------------ settings
    def is_enabled(self) -> bool:
        try:
            with self.database.session() as connection:
                row = connection.execute(
                    "SELECT value FROM app_settings WHERE key='notifications.enabled'"
                ).fetchone()
        except Exception:
            logger.warning("Could not read notification setting; assuming enabled", exc_info=True)
            return True
        if row is None:
            return True
        return str(row["value"]).strip().lower() not in ("0", "false", "no", "off")

    # ------------------------------------------------------------------ internals
    def _effective_offsets(self, item: DueItem) -> list[int]:
        try:
            return self._rule_repo.get_effective_offsets(item.source_kind, item.source_id)
        except Exception:
            logger.warning("Rule lookup failed for %s/%s", item.source_kind, item.source_id, exc_info=True)
            return list(DEFAULT_NOTIFICATION_OFFSETS)

    def _time_reached(self, item: DueItem, now: datetime) -> bool:
        """Honour notify_time: do not announce before the requested hour."""
        try:
            notify_at = self._rule_repo.get_notify_time(item.source_kind, item.source_id)
        except Exception:
            return True
        if not notify_at:
            return True
        try:
            hour, minute = (int(part) for part in notify_at.split(":")[:2])
            return now.time() >= time(hour, minute)
        except (ValueError, TypeError):
            return True

    def _was_delivered(self, item, key: str, channel: str) -> bool:
        with self.database.session() as connection:
            if item.company_id is None:
                row = connection.execute(
                    "SELECT 1 FROM notification_deliveries "
                    "WHERE source_kind=? AND source_id=? AND company_id IS NULL "
                    "AND notification_key=? AND delivery_channel=? LIMIT 1",
                    (item.source_kind, item.source_id, key, channel),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT 1 FROM notification_deliveries "
                    "WHERE source_kind=? AND source_id=? AND company_id=? "
                    "AND notification_key=? AND delivery_channel=? LIMIT 1",
                    (item.source_kind, item.source_id, item.company_id, key, channel),
                ).fetchone()
        return row is not None

    def _mark_delivered(self, item, key: str, channel: str, due_date: date | None = None) -> None:
        stamp = (due_date or getattr(item, "due_date", None) or date.today()).isoformat()
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO notification_deliveries
                    (source_kind, source_id, company_id, notification_key,
                     due_date_snapshot, delivery_channel, delivery_status)
                VALUES (?, ?, ?, ?, ?, ?, 'SHOWN')
                """,
                (item.source_kind, item.source_id, item.company_id, key, stamp, channel),
            )

    def _emit(self, payload: NotificationPayload) -> bool:
        if self.adapter is None:
            return False
        try:
            return bool(self.adapter.show(payload))
        except Exception:
            logger.warning("Notification adapter raised while showing %s", payload.tag, exc_info=True)
            return False


class _DeliveryKey:
    """Minimal stand-in for DueItem when addressing the delivery log directly."""

    __slots__ = ("source_kind", "source_id", "company_id")

    def __init__(self, source_kind: str, source_id: int, company_id: int | None) -> None:
        self.source_kind = source_kind
        self.source_id = source_id
        self.company_id = company_id
