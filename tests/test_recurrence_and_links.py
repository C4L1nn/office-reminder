"""Regression tests for four release bugs found in the independent source audit.

1. Recurring completion was neither atomic nor idempotent.
2. The child occurrence inherited the parent's *due* time as its *notify* time.
3. `create_manual` did not check that a vehicle belongs to the given company.
4. `update_manual` treated an omitted notification setting as "clear it".
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from database.repositories.reminders import KEEP
from services.company_service import CompanyService
from services.reminder_service import ReminderService

TODAY = date(2026, 9, 3)
DUE = TODAY + timedelta(days=10)


def children_of(database, parent_id: int) -> list[dict]:
    with database.session() as connection:
        rows = connection.execute(
            "SELECT id, due_date, status FROM manual_reminders WHERE parent_reminder_id = ? ORDER BY id",
            (parent_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def completions_of(database, reminder_id: int) -> int:
    with database.session() as connection:
        return connection.execute(
            "SELECT COUNT(*) AS c FROM completion_records WHERE source_kind='MANUAL' AND source_id=?",
            (reminder_id,),
        ).fetchone()["c"]


# =========================================================== 1. atomic + idempotent
def test_completing_twice_creates_only_one_next_occurrence(migrated_db):
    reminders = ReminderService(migrated_db)
    parent = reminders.create_manual(title="Kasko", due_date=DUE, recurrence_kind="YEARLY")

    first = reminders.complete(source_kind="MANUAL", source_id=parent)
    second = reminders.complete(source_kind="MANUAL", source_id=parent)

    assert second == first, "ikinci tamamlama mevcut kaydı döndürmeli"
    assert len(children_of(migrated_db, parent)) == 1
    assert completions_of(migrated_db, parent) == 1


def test_complete_undo_complete_creates_only_one_next_occurrence(migrated_db):
    reminders = ReminderService(migrated_db)
    parent = reminders.create_manual(title="Kasko", due_date=DUE, recurrence_kind="YEARLY")

    reminders.complete(source_kind="MANUAL", source_id=parent)
    assert reminders.undo_complete("MANUAL", parent) is True
    reminders.complete(source_kind="MANUAL", source_id=parent)

    occurrences = children_of(migrated_db, parent)
    assert len(occurrences) == 1, "aynı vade için ikinci çocuk üretilmemeli"
    assert occurrences[0]["due_date"] == DUE.replace(year=DUE.year + 1).isoformat()
    assert completions_of(migrated_db, parent) == 1


def test_repeated_cycles_still_yield_one_occurrence_per_period(migrated_db):
    """Rolling forward legitimately produces a new child each period."""
    reminders = ReminderService(migrated_db)
    parent = reminders.create_manual(title="Kira", due_date=DUE, recurrence_kind="MONTHLY")

    reminders.complete(source_kind="MANUAL", source_id=parent)
    child_id = children_of(migrated_db, parent)[0]["id"]
    reminders.complete(source_kind="MANUAL", source_id=child_id)

    assert len(children_of(migrated_db, parent)) == 1
    assert len(children_of(migrated_db, child_id)) == 1


def test_failed_completion_leaves_no_orphan_occurrence(migrated_db):
    """Everything is one transaction: a failure writes nothing at all."""
    reminders = ReminderService(migrated_db)
    parent = reminders.create_manual(title="Kasko", due_date=DUE, recurrence_kind="YEARLY")

    # `amount` reaches the INSERT unvalidated; a value SQLite cannot bind makes
    # the completion statement fail inside the transaction.
    with pytest.raises(Exception):
        reminders.complete(source_kind="MANUAL", source_id=parent, amount={"not": "a number"})

    assert children_of(migrated_db, parent) == [], "başarısız tamamlama çocuk bırakmamalı"
    assert completions_of(migrated_db, parent) == 0
    assert reminders.get_manual(parent).status == "OPEN"


def test_database_refuses_a_duplicate_occurrence(migrated_db):
    """Belt and braces: the invariant is also enforced by a unique index."""
    import sqlite3

    reminders = ReminderService(migrated_db)
    parent = reminders.create_manual(title="Kasko", due_date=DUE, recurrence_kind="YEARLY")
    reminders.complete(source_kind="MANUAL", source_id=parent)
    child = children_of(migrated_db, parent)[0]

    with pytest.raises(sqlite3.IntegrityError):
        with migrated_db.session() as connection:
            connection.execute(
                "INSERT INTO manual_reminders (title, category, due_date, parent_reminder_id) "
                "VALUES ('Kopya', 'GENERAL', ?, ?)",
                (child["due_date"], parent),
            )


def test_non_recurring_completion_creates_no_occurrence(migrated_db):
    reminders = ReminderService(migrated_db)
    reminder_id = reminders.create_manual(title="Tek seferlik", due_date=DUE)

    reminders.complete(source_kind="MANUAL", source_id=reminder_id)

    assert children_of(migrated_db, reminder_id) == []
    assert reminders.get_manual(reminder_id).status == "COMPLETED"


class _FailAfter:
    """Connection proxy that raises once a given number of statements have run.

    Used to fail *after* the next occurrence has been inserted, which is the
    only way to show that the child and the completion really share one
    transaction rather than merely being written in a lucky order.
    """

    def __init__(self, connection, fail_at: int) -> None:
        self._connection = connection
        self._fail_at = fail_at
        self.calls = 0

    def execute(self, *args, **kwargs):
        self.calls += 1
        if self.calls == self._fail_at:
            raise RuntimeError("injected failure")
        return self._connection.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def test_occurrence_is_rolled_back_when_a_later_statement_fails(migrated_db, monkeypatch):
    from contextlib import contextmanager

    reminders = ReminderService(migrated_db)
    parent = reminders.create_manual(
        title="Kasko",
        due_date=DUE,
        recurrence_kind="YEARLY",
        notification_offsets=[7],
        notify_time="09:00",
    )

    original_session = type(migrated_db).session
    proxies: list[_FailAfter] = []

    @contextmanager
    def failing_session(self):
        with original_session(self) as connection:
            proxy = _FailAfter(connection, fail_at=7)
            proxies.append(proxy)
            yield proxy

    # Statement 7 of the completion transaction is the child's notification-rule
    # insert, i.e. after the completion row, the status update and the child.
    monkeypatch.setattr(type(migrated_db), "session", failing_session)
    with pytest.raises(RuntimeError, match="injected failure"):
        reminders.complete(source_kind="MANUAL", source_id=parent)
    monkeypatch.undo()

    assert proxies and proxies[-1].calls == 7, "hata çocuk kayıt eklendikten sonra tetiklenmeli"
    assert children_of(migrated_db, parent) == [], "çocuk kayıt geri alınmalı"
    assert completions_of(migrated_db, parent) == 0, "tamamlama kaydı geri alınmalı"
    assert reminders.get_manual(parent).status == "OPEN"


# ================================================== 2. notify_time is not due_time
def test_occurrence_inherits_notify_time_not_due_time(migrated_db):
    reminders = ReminderService(migrated_db)
    parent = reminders.create_manual(
        title="Sözleşme",
        due_date=DUE,
        due_time="15:00",
        recurrence_kind="YEARLY",
        notification_offsets=[7, 1],
        notify_time="09:00",
    )

    reminders.complete(source_kind="MANUAL", source_id=parent)
    child_id = children_of(migrated_db, parent)[0]["id"]
    child = reminders.get_manual(child_id)

    assert reminders.notification_rules.get_effective_offsets("MANUAL", child_id) == [7, 1]
    assert reminders.notification_rules.get_notify_time("MANUAL", child_id) == "09:00", (
        "bildirim saati kopyalanmalı, vade saati değil"
    )
    assert child.due_time == "15:00", "vade saati ayrı bir alan olarak korunmalı"


def test_occurrence_without_custom_rules_keeps_using_defaults(migrated_db):
    reminders = ReminderService(migrated_db)
    parent = reminders.create_manual(title="Kira", due_date=DUE, recurrence_kind="MONTHLY")

    reminders.complete(source_kind="MANUAL", source_id=parent)
    child_id = children_of(migrated_db, parent)[0]["id"]

    assert reminders.notification_rules.list_for_source("MANUAL", child_id) == []
    assert reminders.notification_rules.get_effective_offsets("MANUAL", child_id) == [14, 7, 3, 1, 0]


# ============================================ 3. company / vehicle consistency
def test_create_rejects_a_vehicle_from_another_company(migrated_db):
    companies = CompanyService(migrated_db)
    reminders = ReminderService(migrated_db)
    first = companies.create("A LTD.")
    second = companies.create("B LTD.")
    vehicle = companies.create_vehicle(company_id=second, plate="34 BB 222")

    with pytest.raises(ValueError, match="ait değil"):
        reminders.create_manual(
            title="Muayene", due_date=DUE, company_id=first, vehicle_id=vehicle
        )

    with migrated_db.session() as connection:
        assert connection.execute("SELECT COUNT(*) AS c FROM manual_reminders").fetchone()["c"] == 0


def test_create_with_vehicle_only_adopts_the_vehicles_company(migrated_db):
    companies = CompanyService(migrated_db)
    reminders = ReminderService(migrated_db)
    company_id = companies.create("NAKLİYAT LTD.")
    vehicle = companies.create_vehicle(company_id=company_id, plate="06 DN 4477")

    reminder_id = reminders.create_manual(title="Muayene", due_date=DUE, vehicle_id=vehicle)

    record = reminders.get_manual(reminder_id)
    assert record.company_id == company_id, "araç verildiyse şirketi de kaydedilmeli"
    assert record.vehicle_id == vehicle
    assert record.plate == "06 DN 4477"


def test_create_rejects_unknown_vehicle(migrated_db):
    reminders = ReminderService(migrated_db)
    with pytest.raises(ValueError, match="Araç bulunamadı"):
        reminders.create_manual(title="Muayene", due_date=DUE, vehicle_id=999)


def test_create_and_update_share_the_same_invariant(migrated_db):
    """Both paths must accept and reject exactly the same combinations."""
    companies = CompanyService(migrated_db)
    reminders = ReminderService(migrated_db)
    first = companies.create("A LTD.")
    second = companies.create("B LTD.")
    foreign = companies.create_vehicle(company_id=second, plate="34 CC 333")
    own = companies.create_vehicle(company_id=first, plate="34 AA 111")

    reminder_id = reminders.create_manual(title="Muayene", due_date=DUE, company_id=first)

    with pytest.raises(ValueError, match="ait değil"):
        reminders.update_manual(reminder_id, vehicle_id=foreign)

    assert reminders.update_manual(reminder_id, vehicle_id=own) is True
    assert reminders.get_manual(reminder_id).vehicle_id == own


# ================================== 4. omitted notification settings are preserved
def test_editing_only_the_title_keeps_notification_settings(migrated_db):
    reminders = ReminderService(migrated_db)
    reminder_id = reminders.create_manual(
        title="Sözleşme",
        due_date=DUE,
        notification_offsets=[90, 7],
        notify_time="09:00",
    )

    assert reminders.update_manual(reminder_id, title="Sözleşme (revize)") is True

    assert reminders.get_manual(reminder_id).title == "Sözleşme (revize)"
    assert reminders.notification_rules.get_effective_offsets("MANUAL", reminder_id) == [90, 7]
    assert reminders.notification_rules.get_notify_time("MANUAL", reminder_id) == "09:00"


def test_changing_offsets_keeps_an_unmentioned_notify_time(migrated_db):
    reminders = ReminderService(migrated_db)
    reminder_id = reminders.create_manual(
        title="Sözleşme", due_date=DUE, notification_offsets=[90, 7], notify_time="09:00"
    )

    reminders.update_manual(reminder_id, notification_offsets=[30])

    assert reminders.notification_rules.get_effective_offsets("MANUAL", reminder_id) == [30]
    assert reminders.notification_rules.get_notify_time("MANUAL", reminder_id) == "09:00"


def test_changing_notify_time_keeps_unmentioned_offsets(migrated_db):
    reminders = ReminderService(migrated_db)
    reminder_id = reminders.create_manual(
        title="Sözleşme", due_date=DUE, notification_offsets=[90, 7], notify_time="09:00"
    )

    reminders.update_manual(reminder_id, notify_time="17:30")

    assert reminders.notification_rules.get_effective_offsets("MANUAL", reminder_id) == [90, 7]
    assert reminders.notification_rules.get_notify_time("MANUAL", reminder_id) == "17:30"


def test_explicitly_clearing_notification_settings_still_works(migrated_db):
    """The dialog always sends both keys, so an empty field must clear."""
    reminders = ReminderService(migrated_db)
    reminder_id = reminders.create_manual(
        title="Sözleşme", due_date=DUE, notification_offsets=[90, 7], notify_time="09:00"
    )

    reminders.update_manual(reminder_id, notification_offsets=None, notify_time=None)

    assert reminders.notification_rules.list_for_source("MANUAL", reminder_id) == []
    assert reminders.notification_rules.get_effective_offsets("MANUAL", reminder_id) == [14, 7, 3, 1, 0]


def test_dialog_payload_round_trips_through_update(migrated_db, qt_app):
    """The real dialog's get_data() must set what the user actually chose."""
    from PySide6.QtCore import QTime

    from ui.dialogs.reminder_dialog import ReminderDialog

    companies = CompanyService(migrated_db)
    reminders = ReminderService(migrated_db)
    reminder_id = reminders.create_manual(
        title="Sözleşme", due_date=DUE, notification_offsets=[90, 7], notify_time="09:00"
    )
    record = reminders.get_manual(reminder_id)

    dialog = ReminderDialog(reminders, companies, existing=record)
    # The dialog loaded what was stored…
    assert dialog.offsets_edit.text() == "90, 7"
    assert dialog.notify_time_check.isChecked()

    # …and a real edit is saved.
    dialog.offsets_edit.setText("45, 5")
    dialog.notify_time_edit.setTime(QTime(8, 15))
    assert dialog.validate()
    reminders.update_manual(reminder_id, **dialog.get_data())

    assert reminders.notification_rules.get_effective_offsets("MANUAL", reminder_id) == [45, 5]
    assert reminders.notification_rules.get_notify_time("MANUAL", reminder_id) == "08:15"


def test_keep_sentinel_is_the_documented_marker():
    """Guards against someone reintroducing None-means-omitted."""
    import inspect

    from services.reminder_service import ReminderService as Service

    source = inspect.getsource(Service.update_manual)
    assert 'kwargs.pop("notification_offsets", KEEP)' in source
    assert 'kwargs.pop("notify_time", KEEP)' in source
    assert KEEP is not None
