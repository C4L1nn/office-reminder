"""A month laid out as a grid of days.

The lists answer "what is next"; this answers "when does the month get busy",
which is the question behind every staffing decision the office makes. Public
holidays are drawn here too: an accountant who can see that the 30th is a
holiday understands at a glance why a due date moved.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from services.formatting import TR_WEEKDAYS_SHORT, short_company_name
from ui.theme import tokens
from ui.widgets import ElidedLabel, label

#: Rows are always six so the grid does not jump height between months.
WEEKS = 6
#: Entries drawn inside a cell before it collapses into "+N".
CHIPS_PER_DAY = 3


class DayCell(QFrame):
    """One day: its number, a few of its obligations, and the overflow count."""

    clicked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DayCell")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(84)

        self.day: date | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(4)
        self.number = QLabel()
        self.number.setObjectName("DayNumber")
        head.addWidget(self.number)
        head.addStretch()
        # The count says how loaded the day is at a glance; a background tint
        # was invisible on the light theme.
        self.count = QLabel()
        self.count.setObjectName("DayCount")
        self.count.hide()
        head.addWidget(self.count)
        layout.addLayout(head)

        self.body = QVBoxLayout()
        self.body.setSpacing(2)
        layout.addLayout(self.body)
        layout.addStretch()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.day is not None:
            self.clicked.emit(self.day)
        super().mousePressEvent(event)

    def _clear(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            # Detaching from the layout is not enough: the label stays a child
            # of the cell until deleteLater actually runs, and keeps painting
            # over the day number. Reparenting removes it from the screen now.
            widget.setParent(None)
            widget.deleteLater()

    def set_day(
        self,
        day: date,
        items: list,
        *,
        in_month: bool,
        today: date,
        holiday: str | None,
        selected: bool,
    ) -> None:
        self.day = day
        self._clear()
        self.number.setText(str(day.day))

        # Properties drive the stylesheet; no colour is set from here.
        for name, value in (
            ("outside", not in_month),
            ("today", day == today),
            ("weekend", day.weekday() >= 5),
            ("holiday", holiday is not None),
            ("selected", selected),
            ("busy", len(items) >= 4),
        ):
            self.setProperty(name, value)
        self.number.setProperty("today", day == today)
        self.number.setProperty("outside", not in_month)

        tip = [day.strftime("%d.%m.%Y")]
        if holiday:
            tip.append(f"Resmî tatil: {holiday}")
            chip = label(holiday, "DayHoliday")
            chip.setToolTip(holiday)
            self.body.addWidget(chip)

        for item in items[:CHIPS_PER_DAY]:
            chip = ElidedLabel(short_company_name(item.company_name))
            chip.setObjectName("DayChip")
            chip.setProperty("official", item.source_kind == "OFFICIAL")
            chip.setToolTip(f"{item.title}\n{item.company_name or 'Genel'}")
            self.body.addWidget(chip)

        if items:
            tip.append(f"{len(items)} yükümlülük")
        # The badge only earns its place when the chips cannot show everything;
        # a "1" next to the single chip that is already there is noise.
        if len(items) > CHIPS_PER_DAY:
            self.count.setText(str(len(items)))
            self.count.setProperty("busy", True)
            self.count.show()
        else:
            self.count.hide()
        self.setToolTip(" · ".join(tip))

        # Qt does not restyle on a property change unless it is asked to.
        for widget in (self, self.number, self.count):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class MonthGrid(QWidget):
    """Weekday headings plus six weeks of `DayCell`."""

    day_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MonthGrid")
        self.selected: date | None = None

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)

        for column, name in enumerate(TR_WEEKDAYS_SHORT):
            heading = label(name, "DayHeading")
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading.setProperty("weekend", column >= 5)
            grid.addWidget(heading, 0, column)

        self.cells: list[DayCell] = []
        for index in range(WEEKS * 7):
            cell = DayCell()
            cell.clicked.connect(self._on_clicked)
            grid.addWidget(cell, 1 + index // 7, index % 7)
            self.cells.append(cell)
        for column in range(7):
            grid.setColumnStretch(column, 1)
        for row in range(1, WEEKS + 1):
            grid.setRowStretch(row, 1)

    def _on_clicked(self, day: date) -> None:
        self.selected = day
        self.day_selected.emit(day)

    def show_month(
        self,
        year: int,
        month: int,
        items_by_day: dict,
        holidays: dict,
        today: date | None = None,
    ) -> None:
        """Fill the grid; `items_by_day` and `holidays` are keyed by date."""
        today = today or date.today()
        first = date(year, month, 1)
        # Monday-first, matching the Turkish week and the weekday headings.
        start = first - timedelta(days=first.weekday())
        for index, cell in enumerate(self.cells):
            day = start + timedelta(days=index)
            cell.set_day(
                day,
                items_by_day.get(day, []),
                in_month=day.month == month and day.year == year,
                today=today,
                holiday=holidays.get(day),
                selected=day == self.selected,
            )


def month_title(year: int, month: int) -> str:
    """"Eylül 2026" — Python's locale month names are not reliable on Windows."""
    from services.formatting import TR_MONTHS

    return f"{TR_MONTHS[month - 1]} {year}"


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


__all__ = ["CHIPS_PER_DAY", "DayCell", "MonthGrid", "month_title", "shift_month"]
