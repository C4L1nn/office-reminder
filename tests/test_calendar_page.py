"""The month view.

It is a second way of reading the same records, so the rule that matters is
that it never invents or loses one: what the month shows must be exactly what
the reminder queries return for that month.
"""

from __future__ import annotations

from datetime import date

import pytest

from services.company_service import CompanyService
from services.reminder_service import ReminderService
from ui.calendar_grid import CHIPS_PER_DAY, WEEKS, month_title, shift_month
from ui.pages.calendar_page import CalendarPage
from ui.theme import apply_theme

#: A real GİB title (30 Eylül 2026). Two lines and an ellipsis turned it into
#: "Taşınmaz ve / Motorlu Taşıt İla…".
LONG_OFFICIAL_TITLE = (
    "Taşınmaz ve Motorlu Taşıt İlanlarını Platformları Üzerinden Yayımlayanlar "
    "ile Günübirlik Konut Kiralama İşini Platformları Üzerinden Sağlayanların Bildirimi"
)


@pytest.fixture()
def page(qt_app, migrated_db):
    apply_theme(qt_app)
    companies = CompanyService(migrated_db)
    reminders = ReminderService(migrated_db)
    company_id = companies.create(name="TAKVİM LTD.", tax_number="3333333333")
    for day in (1, 15, 15, 15, 15, 15, 30):
        reminders.create_manual(
            title=f"Kayıt {day}",
            due_date=date(2026, 9, day),
            company_id=company_id,
            category="OTHER",
        )
    # Neighbouring months, to prove the window is exact.
    reminders.create_manual(
        title="Ağustos", due_date=date(2026, 8, 31), company_id=company_id, category="OTHER"
    )
    reminders.create_manual(
        title="Ekim", due_date=date(2026, 10, 1), company_id=company_id, category="OTHER"
    )
    widget = CalendarPage(reminders, companies)
    widget.year, widget.month = 2026, 9
    widget.refresh()
    yield widget
    widget.close()


def _day_titles(page) -> list:
    """Title labels of the rows currently in the day panel."""
    from PySide6.QtWidgets import QLabel, QWidget

    return [
        title
        for row in page.day_card.findChildren(QWidget, "DayRow")
        for title in row.findChildren(QLabel, "Muted")
    ]


def _settle(qt_app) -> None:
    # Height-for-width settles over two layout passes inside a scroll area.
    qt_app.processEvents()
    qt_app.processEvents()


def test_month_shows_only_its_own_days(page) -> None:
    days = page._items_by_day
    assert set(days) == {date(2026, 9, 1), date(2026, 9, 15), date(2026, 9, 30)}
    assert len(days[date(2026, 9, 15)]) == 5


def test_the_grid_is_always_six_weeks(page) -> None:
    """A grid that changes height between months makes the page jump."""
    assert len(page.grid.cells) == WEEKS * 7
    for month in range(1, 13):
        page.year, page.month = 2026, month
        page.refresh()
        assert sum(1 for cell in page.grid.cells if cell.day is not None) == WEEKS * 7


def test_days_outside_the_month_are_marked(page) -> None:
    inside = [c for c in page.grid.cells if c.property("outside") is False]
    assert len(inside) == 30, "Eylül 30 gün"
    assert all(c.day.month == 9 for c in inside)


def test_a_crowded_day_shows_its_total_in_the_corner(page) -> None:
    """Five records, three chips: the badge carries what the chips cannot."""
    cell = next(c for c in page.grid.cells if c.day == date(2026, 9, 15))
    assert cell.body.count() == CHIPS_PER_DAY
    # isVisible() is False for any child of a window that was never shown;
    # isHidden() is the explicit show/hide state, which is what is asserted.
    assert not cell.count.isHidden()
    assert cell.count.text() == "5"


def test_a_day_whose_chips_show_everything_has_no_badge(page) -> None:
    """A "1" beside the single chip that is already there is noise."""
    cell = next(c for c in page.grid.cells if c.day == date(2026, 9, 1))
    assert cell.body.count() == 1
    assert cell.count.isHidden()


def test_a_long_company_name_is_elided_not_chopped(page) -> None:
    from ui.widgets import ElidedLabel

    cell = next(c for c in page.grid.cells if c.day == date(2026, 9, 15))
    chip = cell.body.itemAt(0).widget()
    assert isinstance(chip, ElidedLabel), "çip kısaltılabilir etiket olmalı"
    assert chip.full_text(), "çip metni boş"


def test_day_detail_shows_the_full_title(page, qt_app) -> None:
    """The panel shows the whole obligation name, wrapped, never cut.

    Two lines and an ellipsis made 113- and 156-character GİB titles
    unreadable. The row grows instead and the list scrolls inside its card.
    """
    page.reminder_service.create_manual(
        title=LONG_OFFICIAL_TITLE, due_date=date(2026, 9, 15), category="OTHER"
    )
    page.refresh()
    page.show()
    page._show_day(date(2026, 9, 15))
    _settle(qt_app)

    target = next((t for t in _day_titles(page) if t.text() == LONG_OFFICIAL_TITLE), None)
    assert target is not None, "uzun başlık gün detayında tam hâliyle yok"
    assert target.wordWrap(), "başlık sarılmıyor, kesilir"
    assert target.height() >= target.heightForWidth(target.width()), "başlık satırına sığmıyor"
    assert LONG_OFFICIAL_TITLE in target.toolTip()


def test_crowded_day_rows_never_overlap(page, qt_app) -> None:
    """Many long records on one day: every row keeps its own band.

    Rows grow with their wrapped titles, so their heights differ. What must
    hold is that no row paints over another and no title is cut by its row.
    """
    from PySide6.QtWidgets import QWidget

    for index in range(6):
        page.reminder_service.create_manual(
            title=f"Uzun Başlıklı Kayıt Numara {index} " + "Ek Metin " * index,
            due_date=date(2026, 9, 15),
            category="OTHER",
        )
    page.refresh()
    page.show()
    _settle(qt_app)
    page._show_day(date(2026, 9, 15))
    _settle(qt_app)

    rows = page.day_card.findChildren(QWidget, "DayRow")
    # Exactly the day's records: rows from an earlier day must not linger as
    # hidden children of the panel.
    assert len(rows) == 11, f"beklenen 11 satır (5 + 6), bulunan {len(rows)}"
    for title in _day_titles(page):
        assert title.height() >= title.heightForWidth(title.width()), title.text()
    boxes = [row.geometry() for row in rows]
    for first in range(len(boxes)):
        for second in range(first + 1, len(boxes)):
            assert not boxes[first].intersects(boxes[second]), (first, second)


def test_repainting_does_not_pile_up_labels(page) -> None:
    """Stale chips stayed children of the cell and covered the day number."""
    from PySide6.QtWidgets import QLabel

    cell = next(c for c in page.grid.cells if c.day == date(2026, 9, 15))
    before = len(cell.findChildren(QLabel))
    for _ in range(5):
        page.refresh()
    assert len(cell.findChildren(QLabel)) == before
    assert cell.number.text() == "15"


def test_stepping_moves_a_month_at_a_time(page) -> None:
    page.year, page.month = 2026, 12
    page._step(1)
    assert (page.year, page.month) == (2027, 1)
    page._step(-1)
    assert (page.year, page.month) == (2026, 12)


def test_shift_month_crosses_the_year_boundary() -> None:
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert shift_month(2026, 1, -1) == (2025, 12)
    assert shift_month(2026, 6, 12) == (2027, 6)


def test_month_title_is_turkish() -> None:
    assert month_title(2026, 9) == "Eylül 2026"
    assert month_title(2027, 1) == "Ocak 2027"


def test_selecting_a_day_lists_it(page) -> None:
    page._show_day(date(2026, 9, 15))
    assert page.day_card.title_label.text().startswith("15")
    assert page.day_body.count() == 5


def test_an_empty_day_says_so(page) -> None:
    page._show_day(date(2026, 9, 2))
    assert page.day_body.count() == 1
    assert "yok" in page.day_body.itemAt(0).widget().text()


def test_public_holidays_are_marked(page) -> None:
    """A holiday on the grid explains why a due date moved."""
    page.year, page.month = 2026, 1
    page.refresh()
    new_year = next(c for c in page.grid.cells if c.day == date(2026, 1, 1))
    assert new_year.property("holiday") is True
    assert "tatil" in new_year.toolTip().lower()


def test_day_detail_titles_use_the_muted_tone(page, qt_app) -> None:
    """Wrapped titles still follow the theme, in both palettes."""
    from ui.theme import DARK, LIGHT, apply_theme

    for palette_tokens in (DARK, LIGHT):
        apply_theme(qt_app, palette_tokens)
        page._show_day(date(2026, 9, 15))
        titles = _day_titles(page)
        assert len(titles) == 5
        for title in titles:
            title.ensurePolished()
            assert title.palette().color(title.foregroundRole()).name() == palette_tokens.text_muted
