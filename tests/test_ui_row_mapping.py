"""A visual row number is not an index into the item list.

Both tables group their rows under date headings ("GECİKEN", "BU AY"), which
are extra rows in the widget. `_selected()` used to index `self._items` by the
current row, so every group heading above the cursor shifted the answer by one
and the wrong record was edited, completed or deleted.
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
    company_id = companies.create(name="TEST LTD.", tax_number="1111111111")

    today = date.today()
    # One overdue and two future records, so the table gets several groups.
    for title, offset in (
        ("Geciken kayıt", -3),
        ("Bugünkü kayıt", 0),
        ("Gelecek kayıt", 20),
    ):
        reminders.create_manual(
            title=title,
            due_date=today + timedelta(days=offset),
            company_id=company_id,
            category="OTHER",
        )
    widget = RemindersPage(reminders, companies)
    widget.refresh()
    return widget


def test_every_data_row_maps_to_its_own_record(page):
    table = page.table
    mapping = page._row_items
    assert mapping, "hiç veri satırı yok"

    for row, item in mapping.items():
        # A mapped row must be a data row, and its date cell must be the
        # record's own date — not a neighbour's.
        cell = table.item(row, 0)
        assert cell is not None
        assert item.due_date.strftime("%d.%m") in cell.text()


def test_selection_returns_the_row_that_was_clicked(page):
    table = page.table
    for row, item in page._row_items.items():
        table.setCurrentCell(row, 0)
        assert page._selected() is item, f"satır {row} yanlış kayda çözümlendi"


def test_group_heading_rows_resolve_to_nothing(page):
    """Clicking a heading must not act on the record that follows it."""
    table = page.table
    heading_rows = [
        row for row in range(table.rowCount()) if row not in page._row_items
    ]
    assert heading_rows, "grup başlığı satırı bulunamadı"
    for row in heading_rows:
        table.setCurrentCell(row, 0)
        assert page._selected() is None
