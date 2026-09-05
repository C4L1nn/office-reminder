"""The date picker popup has to be readable in both themes.

Regression: the pop-up calendar inherited the generic table styling, so the
selected day was painted with ``accent_soft`` — a dark navy square that was
almost invisible against the dark surface — and Qt's ISO week-number column
was left on, which nobody in the office uses and which stole a seventh of the
popup's width.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QCalendarWidget

from ui.theme import DARK, LIGHT, apply_theme
from ui.widgets import style_calendar


def test_week_number_column_is_hidden(qt_app):
    calendar = QCalendarWidget()
    style_calendar(calendar)
    assert (
        calendar.verticalHeaderFormat()
        == QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
    )
    assert calendar.firstDayOfWeek() == Qt.DayOfWeek.Monday


def test_selected_day_uses_the_accent_not_the_soft_tint(qt_app):
    for palette_tokens in (DARK, LIGHT):
        apply_theme(qt_app, palette_tokens)
        calendar = QCalendarWidget()
        style_calendar(calendar)
        view = calendar.findChild(QAbstractItemView)
        assert view is not None
        sheet = view.styleSheet()
        assert palette_tokens.accent in sheet
        assert palette_tokens.accent_soft not in sheet
        assert not view.alternatingRowColors()


def test_weekend_columns_are_distinguishable(qt_app):
    apply_theme(qt_app, DARK)
    calendar = QCalendarWidget()
    style_calendar(calendar)
    weekday = calendar.weekdayTextFormat(Qt.DayOfWeek.Wednesday).foreground().color()
    weekend = calendar.weekdayTextFormat(Qt.DayOfWeek.Sunday).foreground().color()
    assert weekday.name() == DARK.text
    assert weekend.name() == DARK.warning


def test_month_arrows_use_the_app_icon_set(qt_app):
    """Qt's built-in arrows ignore the theme; ours are the same SVG set.

    A themed calendar with two black system triangles in its header was the
    one place left where an icon did not come from `ui/icons.py`.
    """
    from PySide6.QtWidgets import QToolButton

    apply_theme(qt_app, DARK)
    calendar = QCalendarWidget()
    style_calendar(calendar)

    for name in ("qt_calendar_prevmonth", "qt_calendar_nextmonth"):
        nav = calendar.findChild(QToolButton, name)
        assert nav is not None, name
        assert not nav.icon().isNull(), name
        assert nav.iconSize().width() == 16


def test_year_editor_hugs_its_four_digits(qt_app):
    """Clicking the year must not open a long empty box.

    The styled size hint for the spin box was 156px for four digits, which left
    a wide gap between the year and its arrows and pushed the next-month arrow
    to the edge of the popup.
    """
    from PySide6.QtWidgets import QSpinBox, QToolButton

    apply_theme(qt_app, DARK)
    calendar = QCalendarWidget()
    style_calendar(calendar)
    calendar.show()

    year_edit = calendar.findChild(QSpinBox, "qt_calendar_yearedit")
    assert year_edit is not None

    digits = year_edit.fontMetrics().horizontalAdvance("0000")
    # Wide enough for the digits and the arrows, nowhere near the 156px hint.
    assert digits < year_edit.width() <= digits + 48

    calendar.findChild(QToolButton, "qt_calendar_yearbutton").click()
    assert year_edit.isVisible()
    calendar.close()


def test_selected_list_row_covers_its_whole_widget(qt_app):
    """The highlight must line up with the row, not sit above it.

    `QListWidget::item` carried 8px of vertical padding while the row widget's
    size hint was the row height, so the widget was drawn 9px below its own
    highlight and its second line fell outside the tinted block.
    """
    from PySide6.QtWidgets import QListWidget, QListWidgetItem

    from ui.widgets import list_row, list_row_size

    apply_theme(qt_app, DARK)
    listing = QListWidget()
    listing.resize(320, 200)
    for primary in ("BİR", "İKİ"):
        item = QListWidgetItem()
        listing.addItem(item)
        item.setSizeHint(list_row_size())
        listing.setItemWidget(item, list_row(primary, "ikinci satır"))
    listing.setCurrentRow(1)
    listing.show()

    item = listing.item(1)
    highlight = listing.visualItemRect(item)
    widget = listing.itemWidget(item).geometry()
    # Within the item's 1px margin, top and bottom must agree.
    assert abs(widget.top() - highlight.top()) <= 2
    assert abs(widget.bottom() - highlight.bottom()) <= 2
    listing.close()
