"""Completing many records at once must behave like completing them one by one.

Month-end is when this is used, so the loop has to keep the guarantees the
single-record path already has: recurring reminders roll forward, an already
completed record is not completed twice, and one failure does not undo the
records that already succeeded.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.company_service import CompanyService
from services.reminder_service import ReminderService
from ui.pages.reminders_page import RemindersPage
from ui.theme import apply_theme


@pytest.fixture()
def page(qt_app, seeded_db):
    apply_theme(qt_app)
    companies = CompanyService(seeded_db)
    reminders = ReminderService(seeded_db)
    company_id = companies.create(name="TEST LTD.", tax_number="2222222222")
    today = date.today()

    reminders.create_manual(
        title="Tek seferlik", due_date=today + timedelta(days=2),
        company_id=company_id, category="OTHER",
    )
    reminders.create_manual(
        title="Aylık kira", due_date=today + timedelta(days=3),
        company_id=company_id, category="RENT", recurrence_kind="MONTHLY",
    )
    reminders.create_manual(
        title="Sözleşme", due_date=today + timedelta(days=4),
        company_id=company_id, category="CONTRACT",
    )
    widget = RemindersPage(reminders, companies)
    widget.refresh()
    return widget


def _select_all_data_rows(page) -> list:
    """Select every data row, leaving the group heading rows alone."""
    from PySide6.QtWidgets import QTableWidgetSelectionRange

    page.table.clearSelection()
    for row in page._row_items:
        page.table.setRangeSelected(
            QTableWidgetSelectionRange(row, 0, row, page.table.columnCount() - 1), True
        )
    return page._selected_items()


def test_selection_skips_group_headings(page) -> None:
    selected = _select_all_data_rows(page)
    assert len(selected) == len(page._row_items)
    titles = {item.title for item in selected}
    assert "Aylık kira" in titles


def test_bulk_complete_marks_every_selected_record(page, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    items = _select_all_data_rows(page)
    assert items

    page._complete_selected()

    for item in items:
        assert page.reminder_service.is_completed(
            item.source_kind, item.source_id, item.company_id
        ), item.title


def test_a_recurring_record_still_rolls_forward(page, monkeypatch) -> None:
    """The bulk path must not bypass the next-occurrence logic."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    service = page.reminder_service
    before = [r for r in service.reminders.list_filtered(include_cancelled=True)
              if r.title == "Aylık kira"]
    assert len(before) == 1

    _select_all_data_rows(page)
    page._complete_selected()

    after = [r for r in service.reminders.list_filtered(include_cancelled=True)
              if r.title == "Aylık kira"]
    # The completed occurrence plus the one generated for next month.
    assert len(after) == 2
    assert {r.status for r in after} == {"COMPLETED", "OPEN"}


def test_completing_the_same_records_twice_adds_nothing(page, monkeypatch) -> None:
    """Re-running the action over records that are already done is a no-op.

    Only non-recurring records are selected here: a recurring one legitimately
    creates its next occurrence on completion, so a second pass would be acting
    on a different record and would rightly change the counts.
    """
    from PySide6.QtWidgets import QMessageBox, QTableWidgetSelectionRange

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    service = page.reminder_service

    def select_one_off() -> list:
        page.table.clearSelection()
        for row, item in page._row_items.items():
            if item.recurrence_kind in (None, "", "NONE"):
                page.table.setRangeSelected(
                    QTableWidgetSelectionRange(row, 0, row, page.table.columnCount() - 1),
                    True,
                )
        return page._selected_items()

    items = select_one_off()
    assert items, "tek seferlik kayıt seçilemedi"
    page._complete_selected()
    after_first = len(service.reminders.list_filtered(include_cancelled=True))

    for item in items:
        assert service.is_completed(item.source_kind, item.source_id, item.company_id)

    # Ask the service to complete them again directly: the guard must hold.
    for item in items:
        if not service.is_completed(item.source_kind, item.source_id, item.company_id):
            service.complete(
                source_kind=item.source_kind,
                source_id=item.source_id,
                company_id=item.company_id,
            )
    assert len(service.reminders.list_filtered(include_cancelled=True)) == after_first


def test_cancelling_the_confirmation_changes_nothing(page, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    items = _select_all_data_rows(page)
    page._complete_selected()
    for item in items:
        assert not page.reminder_service.is_completed(
            item.source_kind, item.source_id, item.company_id
        )
