"""The month view.

Same records as the lists, arranged by date instead of by urgency. Nothing is
created or completed here; picking a day opens that day's records, and acting
on one is still the reminder screen's job.
"""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from services.company_service import CompanyService
from services.formatting import long_date, title_with_plate
from services.holiday_service import HolidayService
from services.reminder_service import ReminderService
from ui.calendar_grid import MonthGrid, month_title, shift_month
from ui.shell import FilterBar, Page
from ui.theme import tokens
from ui.widgets import Badge, Card, fixed_cell, icon_button, label

logger = logging.getLogger(__name__)


def _day_row(children: list[tuple[QWidget, int]]) -> QWidget:
    """A day-detail row whose height follows its wrapped title.

    No fixed or minimum height: the layout asks the title for its
    height-for-width, so a 156-character GİB name gets every line it needs.
    Children sit at the top, so the badge lines up with the first line of a
    long title. The list scrolls inside its card, so a long day never pushes
    the grid around.
    """
    holder = QWidget()
    holder.setObjectName("DayRow")
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(tokens().space_sm)
    for widget, stretch in children:
        layout.addWidget(widget, stretch, Qt.AlignmentFlag.AlignTop)
    return holder


class CalendarPage(Page):
    """A month of obligations, with the day's detail beside it."""

    def __init__(
        self,
        reminder_service: ReminderService,
        company_service: CompanyService,
        holiday_service: HolidayService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Takvim",
            "Yükümlülüklerin aya yayılışı. Bir güne tıklayın, o günün kayıtları yanda açılır.",
            parent,
        )
        self.reminder_service = reminder_service
        self.company_service = company_service
        self.holidays = holiday_service or HolidayService(company_service.database)

        today = date.today()
        self.year, self.month = today.year, today.month
        self._items_by_day: dict[date, list] = {}
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        t = tokens()

        self.previous_button = icon_button("chevron_left", "Önceki ay", "subtle")
        self.previous_button.clicked.connect(lambda: self._step(-1))
        self.today_button = icon_button("calendar", "Bu aya dön", "subtle")
        self.today_button.clicked.connect(self._go_today)
        self.next_button = icon_button("chevron_right", "Sonraki ay", "subtle")
        self.next_button.clicked.connect(lambda: self._step(1))
        for widget in (self.previous_button, self.today_button, self.next_button):
            self.header.add_action(widget)

        bar = FilterBar()
        self.title_label = label("", "SectionTitle")
        self.title_label.setMinimumWidth(150)
        bar.add_widget(self.title_label)

        self.company_combo = QComboBox()
        self.company_combo.addItem("Tüm şirketler", None)
        self.source_combo = QComboBox()
        self.source_combo.addItem("Tüm kaynaklar", None)
        self.source_combo.addItem("Resmî (GİB / SGK)", "OFFICIAL")
        self.source_combo.addItem("Manuel", "MANUAL")
        bar.add_field("Şirket", self.company_combo, 200)
        bar.add_field("Kaynak", self.source_combo, 180)
        bar.finish()
        self.filters = bar
        self.add(bar)

        columns = QHBoxLayout()
        columns.setSpacing(t.space)

        grid_card = Card()
        self.grid = MonthGrid()
        self.grid.day_selected.connect(self._show_day)
        grid_card.add(self.grid)
        columns.addWidget(grid_card, 4)

        self.day_card = Card("Gün")
        self.day_body = QVBoxLayout()
        self.day_body.setContentsMargins(0, 0, 0, 0)
        self.day_body.setSpacing(t.space_xs)
        inner = QWidget()
        # The scroll area stretches its widget to the viewport height, which
        # would share the spare space out among the rows and blow a six-row day
        # up to 100px per row. The trailing stretch absorbs it instead, and it
        # lives out here so `day_body` stays one item per record.
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        inner_layout.addLayout(self.day_body)
        inner_layout.addStretch(1)
        # Busy days hold more rows than fit beside the grid; only this list
        # scrolls, so the grid never changes size and the page never jumps.
        self._day_scroll = QScrollArea()
        self._day_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._day_scroll.setWidgetResizable(True)
        self._day_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._day_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._day_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._day_scroll.setWidget(inner)
        self.day_card.add(self._day_scroll)
        side = QWidget()
        # Wide enough for a two-line obligation name beside its badge: at the
        # old 280px the title column came out 88px, which cut "Elektronik
        # Defter …" down to six letters.
        side.setMinimumWidth(320)
        side.setMaximumWidth(372)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(self.day_card)
        columns.addWidget(side, 1)

        self.add_layout(columns)
        self.content_layout.setStretch(self.content_layout.count() - 1, 1)

        for combo in (self.company_combo, self.source_combo):
            combo.currentIndexChanged.connect(self.refresh)

    # -------------------------------------------------------------------- data
    def _load_companies(self) -> None:
        try:
            companies = self.company_service.list_active()
        except Exception:
            companies = []
        current = self.company_combo.currentData()
        self.company_combo.blockSignals(True)
        self.company_combo.clear()
        self.company_combo.addItem("Tüm şirketler", None)
        for company in companies:
            self.company_combo.addItem(company.name, company.id)
        if current is not None:
            index = self.company_combo.findData(current)
            if index >= 0:
                self.company_combo.setCurrentIndex(index)
        self.company_combo.blockSignals(False)

    def refresh(self) -> None:
        self._load_companies()
        self.title_label.setText(month_title(self.year, self.month))

        try:
            items = self.reminder_service.list_month(
                self.year,
                self.month,
                company_id=self.company_combo.currentData(),
                source_kind_filter=self.source_combo.currentData(),
            )
        except Exception:
            logger.warning("Takvim ayı okunamadı", exc_info=True)
            items = []

        by_day: dict[date, list] = {}
        for item in items:
            by_day.setdefault(item.due_date, []).append(item)
        for day_items in by_day.values():
            day_items.sort(key=lambda i: (i.source_kind != "OFFICIAL", i.title))
        self._items_by_day = by_day

        # _show_day repaints the grid with the selection, so painting it here
        # as well only doubles the work.
        self._show_day(self.grid.selected or self._default_day())

    def _holidays(self) -> dict:
        """Official holidays in view, so a moved due date explains itself."""
        found: dict[date, str] = {}
        for year in {self.year, self.year + (1 if self.month == 12 else 0)}:
            try:
                for row in self.holidays.list_holidays(year=year):
                    found[date.fromisoformat(row["holiday_date"])] = row["name"]
            except Exception:
                logger.warning("Tatil verisi okunamadı: %s", year, exc_info=True)
        return found

    def _default_day(self) -> date:
        today = date.today()
        if (today.year, today.month) == (self.year, self.month):
            return today
        return date(self.year, self.month, 1)

    # ---------------------------------------------------------------- movement
    def _step(self, delta: int) -> None:
        self.year, self.month = shift_month(self.year, self.month, delta)
        self.grid.selected = None
        self.refresh()

    def _go_today(self) -> None:
        today = date.today()
        self.year, self.month = today.year, today.month
        self.grid.selected = today
        self.refresh()

    # ------------------------------------------------------------- day detail
    def _show_day(self, day: date) -> None:
        self.grid.selected = day
        self.grid.show_month(self.year, self.month, self._items_by_day, self._holidays())

        while self.day_body.count():
            entry = self.day_body.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                # As in DayCell._clear: deleteLater alone leaves the old row a
                # child of the panel until the event loop reaches it, so it
                # still paints and is still found by findChildren.
                widget.setParent(None)
                widget.deleteLater()

        self.day_card.title_label.setText(long_date(day))
        holiday = self._holidays().get(day)
        if holiday:
            self.day_body.addWidget(Badge(holiday, "warning"))

        items = self._items_by_day.get(day, [])
        if not items:
            self.day_body.addWidget(
                label("Bu günde yükümlülük yok.", "Muted", wrap=True)
            )
            return

        today = date.today()
        for item in items:
            days = (item.due_date - today).days
            from ui.pages.dashboard_page import status_tone

            text, tone = status_tone(days)
            # The whole name, wrapped: GİB titles run to 156 characters, and two
            # lines with an ellipsis left them unreadable. The row grows to fit
            # (see _day_row); the tooltip adds the company.
            title = label(title_with_plate(item.title, item.plate), "Muted", wrap=True)
            title.setToolTip(f"{item.title}\n{item.company_name or 'Genel'}")
            # No per-row date: every record in this panel falls on the day in
            # the card's own title, so the column repeated one date down the
            # list while squeezing the titles it sat next to.
            self.day_body.addWidget(
                _day_row([(title, 1), (fixed_cell(Badge(text, tone), 88), 0)])
            )
