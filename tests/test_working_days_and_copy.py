"""Two small touches on the reminders list.

A deadline is only as close as the working days left before it, and the office
retypes rows into e-mails all day.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.company_service import CompanyService
from services.holiday_service import HolidayService
from services.reminder_service import ReminderService
from ui.pages.reminders_page import RemindersPage
from ui.theme import apply_theme


# ------------------------------------------------------------- working days
def test_working_days_skip_weekends(migrated_db) -> None:
    holidays = HolidayService(migrated_db)
    # Friday to the following Friday: seven calendar days, five working ones.
    assert holidays.working_days_between(date(2026, 9, 4), date(2026, 9, 11)) == 5


def test_working_days_skip_public_holidays(migrated_db) -> None:
    """1 Ocak is a holiday, so the first week of the year is short."""
    holidays = HolidayService(migrated_db)
    plain = holidays.working_days_between(date(2026, 12, 28), date(2027, 1, 4))
    assert plain < 5


def test_working_days_are_never_negative(migrated_db) -> None:
    holidays = HolidayService(migrated_db)
    assert holidays.working_days_between(date(2026, 9, 10), date(2026, 9, 4)) == 0
    assert holidays.working_days_between(date(2026, 9, 4), date(2026, 9, 4)) == 0


def test_the_count_is_smaller_than_the_calendar_gap(migrated_db) -> None:
    holidays = HolidayService(migrated_db)
    start, end = date(2026, 9, 4), date(2026, 9, 28)
    assert holidays.working_days_between(start, end) < (end - start).days


# ------------------------------------------------------------------- page
@pytest.fixture()
def page(qt_app, seeded_db):
    apply_theme(qt_app)
    companies = CompanyService(seeded_db)
    reminders = ReminderService(seeded_db)
    company_id = companies.create(name="KOPYA LTD.", tax_number="5555555555")
    today = date.today()
    for offset, title in ((20, "Uzak iş"), (2, "Yakın iş")):
        reminders.create_manual(
            title=title,
            due_date=today + timedelta(days=offset),
            company_id=company_id,
            category="OTHER",
        )
    widget = RemindersPage(reminders, companies)
    widget.refresh()
    yield widget
    widget.close()


def test_the_date_tooltip_names_both_counts(page) -> None:
    item = next(i for i in page._row_items.values() if i.title == "Uzak iş")
    tooltip = page._due_tooltip(item, date.today())
    assert "iş günü" in tooltip
    assert "gün ·" in tooltip


def test_an_overdue_row_says_so_instead(page) -> None:
    item = next(iter(page._row_items.values()))
    tooltip = page._due_tooltip(item, item.due_date + timedelta(days=3))
    assert "gecikti" in tooltip
    assert "iş günü" not in tooltip


# ------------------------------------------------------------------- copy
def test_copying_a_row_puts_readable_text_on_the_clipboard(page, qt_app) -> None:
    from PySide6.QtWidgets import QApplication, QTableWidgetSelectionRange

    row = next(iter(page._row_items))
    page.table.clearSelection()
    page.table.setRangeSelected(
        QTableWidgetSelectionRange(row, 0, row, page.table.columnCount() - 1), True
    )
    page.copy_selected()

    text = QApplication.clipboard().text()
    item = page._row_items[row]
    assert item.title in text
    assert item.due_date.strftime("%d.%m.%Y") in text
    assert " · " in text


def test_copying_several_rows_gives_one_line_each(page, qt_app) -> None:
    from PySide6.QtWidgets import QApplication, QTableWidgetSelectionRange

    rows = list(page._row_items)[:2]
    page.table.clearSelection()
    for row in rows:
        page.table.setRangeSelected(
            QTableWidgetSelectionRange(row, 0, row, page.table.columnCount() - 1), True
        )
    page.copy_selected()

    assert len(QApplication.clipboard().text().splitlines()) == len(rows)


def test_copying_nothing_does_nothing(page, qt_app) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.clipboard().setText("dokunma")
    page.table.clearSelection()
    page.table.setCurrentCell(-1, -1)
    page.copy_selected()
    assert QApplication.clipboard().text() == "dokunma"
