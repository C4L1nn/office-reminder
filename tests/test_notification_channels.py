"""Two-channel notification delivery.

Most people run Windows with Do Not Disturb / Focus Assist on, which silently
swallows the toast — the reminder was then never seen at all. Every
announcement now also lands in an in-app inbox that the operating system cannot
suppress, and the delivery ledger tracks each channel separately so a
suppressed toast is retried without duplicating the inbox entry.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.company_service import CompanyService
from services.notification_adapter import RecordingNotificationAdapter
from services.notification_service import IN_APP, WINDOWS, NotificationService
from services.reminder_service import ReminderService

TODAY = date(2026, 9, 3)
#: The revision fixture moves a due date from 31 Mart to 7 Nisan. Announcing
#: it only makes sense while 7 Nisan is still ahead.
REVISION_DAY = date(2026, 4, 1)


def deliveries(database, channel: str | None = None) -> int:
    query = "SELECT COUNT(*) AS c FROM notification_deliveries"
    args: tuple = ()
    if channel:
        query += " WHERE delivery_channel = ?"
        args = (channel,)
    with database.session() as connection:
        return connection.execute(query, args).fetchone()["c"]


def make_due_reminder(database, days: int = 3) -> ReminderService:
    service = ReminderService(database)
    service.create_manual(title="Araç Muayenesi", due_date=TODAY + timedelta(days=days))
    return service


# ------------------------------------------------------- inbox is guaranteed
def test_suppressed_toast_still_reaches_the_inbox(migrated_db):
    """The whole point: Focus Assist must not lose a reminder."""
    reminders = make_due_reminder(migrated_db)
    silenced = RecordingNotificationAdapter(succeed=False)
    service = NotificationService(migrated_db, reminders, adapter=silenced)

    announced = service.check_and_notify(today=TODAY)

    assert announced == 1, "Windows sussa da bildirim kullanıcıya ulaşmış sayılır"
    assert silenced.shown == [], "toast gerçekten gösterilemedi"

    inbox = service.inbox.list_recent()
    assert len(inbox) == 1
    assert inbox[0].title == "Araç Muayenesi"
    assert inbox[0].is_unread
    assert service.unread_count() == 1

    assert deliveries(migrated_db, IN_APP) == 1
    assert deliveries(migrated_db, WINDOWS) == 0, "gösterilemeyen toast teslim sayılmaz"


def test_suppressed_toast_is_retried_without_duplicating_the_inbox(migrated_db):
    reminders = make_due_reminder(migrated_db)
    service = NotificationService(migrated_db, reminders, adapter=RecordingNotificationAdapter(succeed=False))
    service.check_and_notify(today=TODAY)

    # Do Not Disturb turned off; the next check gets the toast through.
    working = RecordingNotificationAdapter(succeed=True)
    service.adapter = working
    again = service.check_and_notify(today=TODAY)

    assert again == 0, "kutuya zaten düştü, tekrar 'yeni' sayılmaz"
    assert len(working.shown) == 1, "Windows bildirimi bu turda gösterildi"
    assert len(service.inbox.list_recent()) == 1, "kutuda tek kayıt"
    assert deliveries(migrated_db, WINDOWS) == 1
    assert deliveries(migrated_db, IN_APP) == 1


def test_both_channels_deliver_when_windows_is_available(migrated_db):
    reminders = make_due_reminder(migrated_db)
    adapter = RecordingNotificationAdapter(succeed=True)
    service = NotificationService(migrated_db, reminders, adapter=adapter)

    assert service.check_and_notify(today=TODAY) == 1
    assert len(adapter.shown) == 1
    assert len(service.inbox.list_recent()) == 1
    assert deliveries(migrated_db, IN_APP) == 1
    assert deliveries(migrated_db, WINDOWS) == 1

    # And nothing repeats on the next pass.
    assert service.check_and_notify(today=TODAY) == 0
    assert len(adapter.shown) == 1
    assert len(service.inbox.list_recent()) == 1


def test_inbox_entry_carries_the_same_wording_as_the_toast(migrated_db):
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
    adapter = RecordingNotificationAdapter(succeed=True)
    service = NotificationService(migrated_db, reminders, adapter=adapter)
    service.check_and_notify(today=TODAY)

    toast = adapter.shown[0]
    entry = service.inbox.list_recent()[0]
    assert entry.title == toast.title
    assert entry.body == toast.body
    assert "35 ABC 123" in entry.body and "3 gün kaldı" in entry.body
    assert entry.company_name == "ABC LTD."


# ------------------------------------------------------------------ severity
@pytest.mark.parametrize(
    "days,kind,severity",
    [(5, "DUE", "INFO"), (0, "DUE", "WARNING"), (-2, "OVERDUE", "DANGER")],
)
def test_severity_reflects_urgency(migrated_db, days, kind, severity):
    reminders = ReminderService(migrated_db)
    reminders.create_manual(
        title="Kayıt", due_date=TODAY + timedelta(days=days), notification_offsets=[max(days, 0)]
    )
    service = NotificationService(migrated_db, reminders, adapter=RecordingNotificationAdapter())
    service.check_and_notify(today=TODAY)

    entry = service.inbox.list_recent()[0]
    assert entry.kind == kind
    assert entry.severity == severity


# ------------------------------------------------------------------ read state
def test_marking_read_clears_the_unread_count(migrated_db):
    reminders = make_due_reminder(migrated_db)
    service = NotificationService(migrated_db, reminders, adapter=RecordingNotificationAdapter())
    service.check_and_notify(today=TODAY)

    assert service.unread_count() == 1
    entry = service.inbox.list_recent()[0]

    assert service.inbox.mark_read(entry.id) is True
    assert service.unread_count() == 0
    assert service.inbox.mark_read(entry.id) is False, "ikinci kez okundu işaretlemek etkisiz"

    assert service.inbox.list_recent(unread_only=True) == []
    assert len(service.inbox.list_recent()) == 1, "okunan bildirim geçmişte kalır"


def test_mark_all_read(migrated_db):
    reminders = ReminderService(migrated_db)
    for offset in (0, 1, 3):
        reminders.create_manual(title=f"Kayıt {offset}", due_date=TODAY + timedelta(days=offset))
    service = NotificationService(migrated_db, reminders, adapter=RecordingNotificationAdapter())
    service.check_and_notify(today=TODAY)

    assert service.unread_count() == 3
    assert service.inbox.mark_all_read() == 3
    assert service.unread_count() == 0


# ------------------------------------------------------------------ revisions
def _revised_calendar(seeded_db, adapter):
    """A company subject to SGK 4/a whose February due date moved 31 Mart → 7 Nisan."""
    from services.holiday_service import HolidayService
    from services.official_update_service import OfficialUpdateService
    from services.sgk_calendar_service import SgkCalendarService

    companies = CompanyService(seeded_db)
    codes = {o.code: o.id for o in companies.list_obligation_types()}
    company_id = companies.create("BİLDİRİM LTD.")
    companies.save_obligation_profile(
        company_id, [codes["SGK_4A_PREMIUM"]], sgk_wage_period="MONTHLY_1_END",
        enabled_from=date(2026, 1, 1))
    SgkCalendarService(seeded_db, HolidayService(seeded_db)).apply_official_override(
        "SGK_4A_2026_02_1END", date(2026, 4, 7), "SGK duyurusu", "https://www.sgk.gov.tr")

    notifier = NotificationService(seeded_db, ReminderService(seeded_db), adapter=adapter)
    return OfficialUpdateService(seeded_db, notifier=notifier), notifier


def test_official_revision_also_lands_in_the_inbox(seeded_db):
    silenced = RecordingNotificationAdapter(succeed=False)
    service, notifier = _revised_calendar(seeded_db, silenced)

    assert service.announce_revisions(today=REVISION_DAY) == 1, "toast sussa da kullanıcıya ulaşır"
    entry = notifier.inbox.list_recent()[0]
    assert entry.kind == "OFFICIAL_REVISION"
    assert entry.title == "Resmî tarih değişti"
    assert "31 Mart" in entry.body and "7 Nisan" in entry.body
    assert notifier.unread_count() == 1

    assert service.announce_revisions(today=REVISION_DAY) == 0, "aynı revision iki kez kutuya düşmez"
    assert len(notifier.inbox.list_recent()) == 1


def test_revision_for_a_date_already_past_is_not_announced(seeded_db):
    """A new install's first sync must not announce last spring's changes.

    On 2026-09-05 the office received "31 Mart → 7 Nisan" and "1 Haziran →
    5 Haziran" as fresh news: the revisions were *detected* that day, but the
    dates had passed months earlier and there was nothing left to act on.
    """
    adapter = RecordingNotificationAdapter()
    service, notifier = _revised_calendar(seeded_db, adapter)

    assert service.announce_revisions(today=TODAY) == 0
    assert adapter.shown == []
    assert notifier.inbox.list_recent() == []


# ------------------------------------------------------------------ settings
def test_disabled_notifications_produce_nothing_at_all(migrated_db):
    from services.settings_service import SettingsService

    reminders = make_due_reminder(migrated_db)
    SettingsService(migrated_db).set_notifications_enabled(False)
    adapter = RecordingNotificationAdapter()
    service = NotificationService(migrated_db, reminders, adapter=adapter)

    assert service.check_and_notify(today=TODAY) == 0
    assert adapter.shown == []
    assert service.inbox.list_recent() == []


# ------------------------------------------------------------------ UI surface
def test_notifications_page_lists_and_marks(migrated_db, qt_app):
    from ui.pages.notifications_page import NotificationsPage

    reminders = make_due_reminder(migrated_db)
    service = NotificationService(migrated_db, reminders, adapter=RecordingNotificationAdapter(succeed=False))
    service.check_and_notify(today=TODAY)

    page = NotificationsPage(service)
    counts: list[int] = []
    page.unread_changed.connect(counts.append)
    page.refresh()

    assert counts and counts[-1] == 1
    assert page.mark_all_button.isEnabled()

    page._mark_all()
    assert service.unread_count() == 0
    assert counts[-1] == 0
    assert not page.mark_all_button.isEnabled()


def _inbox_with_one_read_one_unread(database) -> NotificationService:
    reminders = ReminderService(database)
    reminders.create_manual(title="Okunan", due_date=TODAY + timedelta(days=3))
    reminders.create_manual(title="Yeni gelen", due_date=TODAY + timedelta(days=1))
    service = NotificationService(database, reminders, adapter=RecordingNotificationAdapter())
    service.check_and_notify(today=TODAY)
    read = next(n for n in service.inbox.list_recent() if n.title == "Okunan")
    service.inbox.mark_read(read.id)
    return service


def _listed_titles(page) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [
        title.text()
        for title in page.list_host.findChildren(QLabel, "SectionTitle")
        if not page.empty.isAncestorOf(title)
    ]


def test_notifications_page_opens_on_unread_only(migrated_db, qt_app):
    from ui.pages.notifications_page import NotificationsPage

    page = NotificationsPage(_inbox_with_one_read_one_unread(migrated_db))
    page.refresh()

    assert page.filter_button.text() == "Eski bildirimler"
    assert not page.filter_button.isChecked()
    assert _listed_titles(page) == ["Yeni gelen"], "okunmuş bildirim varsayılan görünümde"


def test_old_notifications_button_brings_back_read_ones(migrated_db, qt_app):
    from ui.pages.notifications_page import NotificationsPage

    page = NotificationsPage(_inbox_with_one_read_one_unread(migrated_db))
    page.refresh()

    page.filter_button.setChecked(True)
    assert sorted(_listed_titles(page)) == ["Okunan", "Yeni gelen"]

    page.filter_button.setChecked(False)
    assert _listed_titles(page) == ["Yeni gelen"]


def test_empty_unread_view_says_where_the_rest_went(migrated_db, qt_app):
    """"Bildirim yok" over a list of read notifications reads like lost history."""
    from ui.pages.notifications_page import NO_UNREAD_TITLE, NotificationsPage

    service = _inbox_with_one_read_one_unread(migrated_db)
    service.inbox.mark_all_read()
    page = NotificationsPage(service)
    page.refresh()

    assert not page.empty.isHidden()
    assert page.empty._heading.text() == NO_UNREAD_TITLE
    assert "Eski bildirimler" in page.empty._body.text()


def test_empty_inbox_keeps_the_plain_message(migrated_db, qt_app):
    from ui.pages.notifications_page import EMPTY_TITLE, NotificationsPage

    service = NotificationService(migrated_db, ReminderService(migrated_db), adapter=RecordingNotificationAdapter())
    page = NotificationsPage(service)
    page.refresh()

    assert not page.empty.isHidden()
    assert page.empty._heading.text() == EMPTY_TITLE


def test_sidebar_shows_the_unread_badge(qt_app):
    from ui.shell import Sidebar

    sidebar = Sidebar("1.0.0")
    sidebar.resize(212, 700)
    sidebar.show()

    sidebar.set_badge("notifications", 4)
    badge = sidebar._badges["notifications"]
    assert badge.isVisible() and badge.text() == "4"

    sidebar.set_badge("notifications", 0)
    assert not badge.isVisible()

    sidebar.set_badge("notifications", 250)
    assert badge.text() == "99+"
    sidebar.close()


def test_tray_icon_badge_is_generated(qt_app):
    from ui import icons

    plain = icons.app_icon()
    badged = icons.app_icon_with_badge(3)
    assert badged.availableSizes(), "rozetli ikon üretildi"
    assert icons.app_icon_with_badge(0).availableSizes() == plain.availableSizes()
