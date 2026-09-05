"""Release-candidate acceptance tests.

These cover the end-to-end behaviours a user depends on, each one written
against a defect that was actually present: a lost obligation profile, a
notification recorded but never shown, a long reminder offset that never fired,
a vehicle link the UI could not set.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from database.connection import Database
from database.migrations import MigrationRunner
from services.company_service import CompanyService
from services.notification_adapter import RecordingNotificationAdapter
from services.notification_service import NotificationService
from services.reminder_service import ReminderService
from tests.conftest import MIGRATIONS_DIR

TODAY = date(2026, 9, 3)


def obligation_ids(companies: CompanyService, *codes: str) -> list[int]:
    lookup = {o.code: o.id for o in companies.list_obligation_types()}
    return [lookup[code] for code in codes]


# --------------------------------------------------------------------------- A
def test_first_time_kdv_profile_survives_and_projects_twelve_events(seeded_db):
    """A: the very first save must persist obligation AND profile together."""
    companies = CompanyService(seeded_db)
    reminders = ReminderService(seeded_db)

    company_id = companies.create("TEST LTD.")
    companies.save_obligation_profile(
        company_id,
        obligation_ids(companies, "GIB_KDV"),
        kdv_variants=["KDV_STANDARD_MONTHLY"],
        enabled_from=date(2026, 1, 1),
    )

    # The profile is really in the database, not just in the dialog.
    assert companies.get_kdv_profile(company_id) == ["KDV_STANDARD_MONTHLY"]
    with seeded_db.session() as conn:
        row = conn.execute(
            """
            SELECT co.settings_json FROM company_obligations co
            JOIN obligation_types ot ON ot.id = co.obligation_type_id
            WHERE co.company_id = ? AND ot.code = 'GIB_KDV'
            """,
            (company_id,),
        ).fetchone()
    assert row is not None and "KDV_STANDARD_MONTHLY" in row["settings_json"]

    items = reminders.list_due(horizon_days=400, today=date(2026, 1, 1), company_id=company_id)
    monthly = [i for i in items if i.obligation_code == "GIB_KDV"]
    assert len(monthly) == 12, "aylık KDV beyanı yılda 12 kez"
    assert companies.profile_gaps(company_id) == []


def test_kdv_without_variant_shows_nothing_and_is_reported_as_a_gap(seeded_db):
    """Fail-safe: no profile means no dates, and the gap is visible to the user."""
    companies = CompanyService(seeded_db)
    reminders = ReminderService(seeded_db)

    company_id = companies.create("PROFİLSİZ LTD.")
    companies.save_obligation_profile(
        company_id, obligation_ids(companies, "GIB_KDV"), enabled_from=date(2026, 1, 1)
    )

    items = reminders.list_due(horizon_days=400, today=date(2026, 1, 1), company_id=company_id)
    assert [i for i in items if i.obligation_code == "GIB_KDV"] == []
    assert companies.profile_gaps(company_id) == ["GIB_KDV"]


# --------------------------------------------------------------------------- B
@pytest.mark.parametrize(
    "wage_period,expected_tag",
    [("MONTHLY_1_END", "SGK_4A_1END"), ("MONTHLY_15_14", "SGK_4A_15_14")],
)
def test_sgk_wage_period_selects_the_right_schedule(seeded_db, wage_period, expected_tag):
    """B: each wage period projects its own twelve payment dates, never both."""
    companies = CompanyService(seeded_db)
    reminders = ReminderService(seeded_db)

    company_id = companies.create(f"SGK {wage_period}")
    companies.save_obligation_profile(
        company_id,
        obligation_ids(companies, "SGK_4A_PREMIUM"),
        sgk_wage_period=wage_period,
        enabled_from=date(2026, 1, 1),
    )
    assert companies.get_sgk_wage_period(company_id) == wage_period

    # The 15-14 period for December falls due on 2027-02-14, so the window has
    # to reach past the following February for both wage periods to show 12.
    items = [
        i
        for i in reminders.list_due(horizon_days=450, today=date(2026, 1, 1), company_id=company_id)
        if i.obligation_code == "SGK_4A_PREMIUM"
    ]
    assert len(items) == 12

    with seeded_db.session() as conn:
        keys = {
            conn.execute(
                "SELECT source_event_key FROM official_calendar_events WHERE id = ?", (item.source_id,)
            ).fetchone()["source_event_key"]
            for item in items
        }
    suffix = "1END" if wage_period == "MONTHLY_1_END" else "15_14"
    assert all(key.endswith(suffix) for key in keys)

    with seeded_db.session() as conn:
        tags = conn.execute(
            "SELECT eligibility_tags FROM official_calendar_events WHERE source_event_key = ?",
            (sorted(keys)[0],),
        ).fetchone()["eligibility_tags"]
    assert expected_tag in tags


def test_sgk_january_period_due_dates_follow_the_rule(seeded_db):
    """1–ay sonu: takip eden ayın son günü. 15–14: dönem sonunu takip eden ayın 14'ü."""
    with seeded_db.session() as conn:
        one_end = conn.execute(
            "SELECT normal_due_date FROM official_calendar_events WHERE source_event_key='SGK_4A_2026_01_1END'"
        ).fetchone()["normal_due_date"]
        fifteen = conn.execute(
            "SELECT normal_due_date FROM official_calendar_events WHERE source_event_key='SGK_4A_2026_01_15_14'"
        ).fetchone()["normal_due_date"]
    assert one_end == "2026-02-28"
    assert fifteen == "2026-03-14"


# --------------------------------------------------------------------------- E
def test_failed_windows_toast_is_not_recorded_as_delivered(migrated_db):
    """E: a toast that never appeared must be retried, not silently swallowed.

    The rule is now per channel. The in-app inbox always delivers (that is the
    point of it — Do Not Disturb cannot silence it), while the Windows channel
    is only marked delivered once the toast really appeared, so a suppressed
    one is retried on the next pass.
    """
    from services.notification_service import IN_APP, WINDOWS

    def channel_rows(channel: str) -> int:
        with migrated_db.session() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM notification_deliveries WHERE delivery_channel = ?",
                (channel,),
            ).fetchone()["c"]

    reminders = ReminderService(migrated_db)
    reminders.create_manual(title="Bildirim testi", due_date=TODAY + timedelta(days=3))

    failing = RecordingNotificationAdapter(succeed=False)
    service = NotificationService(migrated_db, reminders, adapter=failing)

    # Announced to the user via the inbox, even though the toast failed.
    assert service.check_and_notify(today=TODAY) == 1
    assert failing.shown == []
    assert service.unread_count() == 1
    assert channel_rows(IN_APP) == 1
    assert channel_rows(WINDOWS) == 0, "gösterilemeyen toast teslim sayılmaz"

    working = RecordingNotificationAdapter(succeed=True)
    service.adapter = working
    # Nothing new for the user (already in the inbox), but the toast is retried.
    assert service.check_and_notify(today=TODAY) == 0
    assert len(working.shown) == 1, "Windows kanalı yeniden denendi"
    assert channel_rows(WINDOWS) == 1
    assert channel_rows(IN_APP) == 1, "kutuya ikinci kez yazılmadı"

    # And neither channel repeats after that.
    assert service.check_and_notify(today=TODAY) == 0
    assert len(working.shown) == 1
    assert len(service.inbox.list_recent()) == 1


def test_notification_text_reads_like_a_sentence(migrated_db):
    companies = CompanyService(migrated_db)
    company_id = companies.create("ABC LTD.")
    vehicle_id = companies.create_vehicle(company_id=company_id, plate="35 ABC 123")
    reminders = ReminderService(migrated_db)
    reminders.create_manual(
        title="Araç Muayenesi",
        due_date=TODAY + timedelta(days=3),
        company_id=company_id,
        vehicle_id=vehicle_id,
        category="VEHICLE_INSPECTION",
    )

    adapter = RecordingNotificationAdapter()
    NotificationService(migrated_db, reminders, adapter=adapter).check_and_notify(today=TODAY)

    payload = adapter.shown[0]
    assert payload.title == "Araç Muayenesi"
    assert "ABC LTD." in payload.body and "35 ABC 123" in payload.body
    assert "3 gün kaldı" in payload.body
    assert "6 Eylül 2026" in payload.body


# --------------------------------------------------------------------------- F
def test_ninety_day_offset_actually_fires(migrated_db):
    """F: the query horizon follows the rules, not a hard-coded 30 days."""
    reminders = ReminderService(migrated_db)
    reminder_id = reminders.create_manual(
        title="Sözleşme yenileme",
        due_date=TODAY + timedelta(days=90),
        notification_offsets=[90, 30, 7],
    )
    assert reminders.notification_rules.get_effective_offsets("MANUAL", reminder_id) == [90, 30, 7]

    adapter = RecordingNotificationAdapter()
    service = NotificationService(migrated_db, reminders, adapter=adapter)
    assert service.notification_horizon_days() >= 90
    assert service.check_and_notify(today=TODAY) == 1
    assert "90 gün kaldı" in adapter.shown[0].body


def test_notify_time_defers_until_the_requested_hour(migrated_db):
    reminders = ReminderService(migrated_db)
    reminders.create_manual(
        title="Sabah kontrolü",
        due_date=TODAY + timedelta(days=1),
        notification_offsets=[1],
        notify_time="09:00",
    )
    adapter = RecordingNotificationAdapter()
    service = NotificationService(migrated_db, reminders, adapter=adapter)

    early = datetime(2026, 9, 3, 7, 30)
    assert service.check_and_notify(today=TODAY, now=early) == 0

    later = datetime(2026, 9, 3, 9, 15)
    assert service.check_and_notify(today=TODAY, now=later) == 1


# --------------------------------------------------------------------------- G
def test_vehicle_link_round_trips_through_the_service(migrated_db):
    """G: vehicle_id is written, read back, changeable, and clearable."""
    companies = CompanyService(migrated_db)
    reminders = ReminderService(migrated_db)

    company_id = companies.create("NAKLİYAT LTD.")
    first = companies.create_vehicle(company_id=company_id, plate="06 DN 4477", make="Mercedes")
    second = companies.create_vehicle(company_id=company_id, plate="06 DN 8899")

    reminder_id = reminders.create_manual(
        title="Araç Muayenesi",
        due_date=TODAY + timedelta(days=14),
        company_id=company_id,
        vehicle_id=first,
        category="VEHICLE_INSPECTION",
    )

    record = reminders.get_manual(reminder_id)
    assert record.vehicle_id == first
    assert record.plate == "06 DN 4477"

    reminders.update_manual(reminder_id, vehicle_id=second)
    assert reminders.get_manual(reminder_id).plate == "06 DN 8899"

    reminders.update_manual(reminder_id, vehicle_id=None)
    assert reminders.get_manual(reminder_id).vehicle_id is None

    item = next(
        i
        for i in reminders.list_due(horizon_days=30, today=TODAY, company_id=company_id)
        if i.source_id == reminder_id
    )
    assert item.plate is None


def test_vehicle_from_another_company_is_rejected(migrated_db):
    companies = CompanyService(migrated_db)
    reminders = ReminderService(migrated_db)
    first = companies.create("BİR LTD.")
    second = companies.create("İKİ LTD.")
    vehicle = companies.create_vehicle(company_id=second, plate="34 AA 111")
    reminder_id = reminders.create_manual(title="Muayene", due_date=TODAY, company_id=first)

    with pytest.raises(ValueError):
        reminders.update_manual(reminder_id, vehicle_id=vehicle)


# --------------------------------------------------------------------------- H
def test_data_survives_a_restart(tmp_path):
    """H: closing and reopening the database preserves company, profile, reminder."""
    path = tmp_path / "restart.db"

    first = Database(path)
    MigrationRunner(first, MIGRATIONS_DIR).run()
    companies = CompanyService(first)
    company_id = companies.create("KALICI LTD.", "1112223334")
    companies.save_obligation_profile(
        company_id,
        obligation_ids(companies, "GIB_KDV", "SGK_4A_PREMIUM"),
        kdv_variants=["KDV_TEVKIFAT"],
        sgk_wage_period="MONTHLY_15_14",
    )
    reminder_id = ReminderService(first).create_manual(
        title="Kalıcı hatırlatma", due_date=TODAY + timedelta(days=5), company_id=company_id
    )

    reopened = Database(path)
    # Re-running migrations on an existing database must be a no-op.
    assert MigrationRunner(reopened, MIGRATIONS_DIR).run() == []
    companies_again = CompanyService(reopened)

    assert companies_again.get_by_id(company_id).tax_number == "1112223334"
    assert companies_again.get_kdv_profile(company_id) == ["KDV_TEVKIFAT"]
    assert companies_again.get_sgk_wage_period(company_id) == "MONTHLY_15_14"
    assert ReminderService(reopened).get_manual(reminder_id).title == "Kalıcı hatırlatma"


# --------------------------------------------------------------------------- I
def test_everything_local_works_without_network(seeded_db, monkeypatch):
    """I: offline, the dashboard and local notifications keep working."""
    import socket

    def refuse(*args, **kwargs):
        raise OSError("network is unreachable")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)

    companies = CompanyService(seeded_db)
    reminders = ReminderService(seeded_db)
    company_id = companies.create("OFFLINE LTD.")
    companies.save_obligation_profile(
        company_id,
        obligation_ids(companies, "GIB_KDV"),
        kdv_variants=["KDV_STANDARD_MONTHLY"],
        enabled_from=date(2026, 1, 1),
    )
    reminders.create_manual(
        title="Çevrimdışı hatırlatma", due_date=TODAY, company_id=company_id
    )

    counts = reminders.get_dashboard_counts(today=TODAY, company_id=company_id)
    assert counts["today"] >= 1

    adapter = RecordingNotificationAdapter()
    assert NotificationService(seeded_db, reminders, adapter=adapter).check_and_notify(today=TODAY) >= 1

    # And a failed official check is recorded as failed rather than raising.
    from services.official_update_service import OfficialUpdateService

    result = OfficialUpdateService(seeded_db).sync_sgk()
    assert result["status"] == "FAILED"


# --------------------------------------------------------------------------- J
def test_backup_is_valid_and_openable(seeded_db, tmp_path):
    """J: the backup passes integrity_check and still contains the data."""
    from services.backup_service import BackupService

    companies = CompanyService(seeded_db)
    companies.create("YEDEK LTD.")

    backup_dir = tmp_path / "backups"
    service = BackupService(seeded_db.path, backup_dir, retention_days=3)
    target = service.create_backup(force=True)
    assert target is not None and target.exists()

    connection = sqlite3.connect(target)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        names = {row[0] for row in connection.execute("SELECT name FROM companies")}
        assert "YEDEK LTD." in names
        assert connection.execute("SELECT COUNT(*) FROM official_calendar_events").fetchone()[0] > 400
    finally:
        connection.close()


def test_backup_retention_keeps_the_configured_number(seeded_db, tmp_path):
    from services.backup_service import BackupService

    backup_dir = tmp_path / "backups"
    service = BackupService(seeded_db.path, backup_dir, retention_days=2)
    for _ in range(4):
        service.create_backup(force=True)
    assert len(service.list_backups()) == 2


# --------------------------------------------------------------------------- official revisions
def test_official_revision_is_actually_announced(seeded_db):
    """A date change must reach the user, not just the delivery log."""
    from services.official_update_service import OfficialUpdateService

    companies = CompanyService(seeded_db)
    company_id = companies.create("BİLDİRİM LTD.")
    companies.save_obligation_profile(
        company_id,
        obligation_ids(companies, "SGK_4A_PREMIUM"),
        sgk_wage_period="MONTHLY_1_END",
        enabled_from=date(2026, 1, 1),
    )

    from services.holiday_service import HolidayService
    from services.sgk_calendar_service import SgkCalendarService

    SgkCalendarService(seeded_db, HolidayService(seeded_db)).apply_official_override(
        "SGK_4A_2026_02_1END", date(2026, 4, 7), "SGK duyurusu", "https://www.sgk.gov.tr"
    )

    adapter = RecordingNotificationAdapter()
    notifier = NotificationService(seeded_db, ReminderService(seeded_db), adapter=adapter)
    service = OfficialUpdateService(seeded_db, notifier=notifier)

    assert service.announce_revisions(today=TODAY) == 1
    payload = adapter.shown[0]
    assert payload.title == "Resmî tarih değişti"
    assert "BİLDİRİM LTD." in payload.body
    assert "31 Mart" in payload.body and "7 Nisan" in payload.body
    assert "SGK" in payload.body

    # Announced once per company, then never again.
    assert service.announce_revisions(today=TODAY) == 0


def test_revision_toast_is_not_recorded_when_it_cannot_be_shown(seeded_db):
    from services.official_update_service import OfficialUpdateService
    from services.holiday_service import HolidayService
    from services.sgk_calendar_service import SgkCalendarService

    companies = CompanyService(seeded_db)
    company_id = companies.create("SESSİZ LTD.")
    companies.save_obligation_profile(
        company_id,
        obligation_ids(companies, "SGK_4A_PREMIUM"),
        sgk_wage_period="MONTHLY_1_END",
        enabled_from=date(2026, 1, 1),
    )
    SgkCalendarService(seeded_db, HolidayService(seeded_db)).apply_official_override(
        "SGK_4A_2026_02_1END", date(2026, 4, 7), "SGK duyurusu", "https://www.sgk.gov.tr"
    )

    from services.notification_service import IN_APP, WINDOWS

    def revision_rows(channel: str) -> int:
        with seeded_db.session() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM notification_deliveries "
                "WHERE notification_key LIKE 'REVISION_%' AND delivery_channel = ?",
                (channel,),
            ).fetchone()["c"]

    broken = RecordingNotificationAdapter(succeed=False)
    notifier = NotificationService(seeded_db, ReminderService(seeded_db), adapter=broken)
    service = OfficialUpdateService(seeded_db, notifier=notifier)

    # The date change still reaches the user through the inbox.
    assert service.announce_revisions(today=TODAY) == 1
    assert broken.shown == []
    assert notifier.unread_count() == 1
    assert revision_rows(IN_APP) == 1
    assert revision_rows(WINDOWS) == 0, "gösterilemeyen toast teslim edilmiş sayılmaz"

    # Once the channel works the toast is retried, without a second inbox entry.
    notifier.adapter = RecordingNotificationAdapter()
    assert service.announce_revisions(today=TODAY) == 0
    assert revision_rows(WINDOWS) == 1
    assert len(notifier.inbox.list_recent()) == 1


# --------------------------------------------------------------------------- onboarding window
def test_new_company_does_not_inherit_a_backlog_of_overdue_dates(seeded_db):
    """A company added in September is not late for January."""
    companies = CompanyService(seeded_db)
    reminders = ReminderService(seeded_db)

    company_id = companies.create("YENİ LTD.")
    companies.save_obligation_profile(
        company_id,
        obligation_ids(companies, "GIB_KDV", "SGK_4A_PREMIUM"),
        kdv_variants=["KDV_STANDARD_MONTHLY"],
        sgk_wage_period="MONTHLY_1_END",
    )

    overdue = reminders.list_overdue(today=TODAY, company_id=company_id)
    assert overdue == [], "onboarding öncesi resmî tarihler geciken sayılmaz"

    # The rest of the year is still tracked.
    upcoming = reminders.list_due(horizon_days=200, today=TODAY, company_id=company_id)
    assert len(upcoming) > 0
