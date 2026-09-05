from __future__ import annotations

import logging

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTableWidgetItem,
    QWidget,
)

from PySide6.QtGui import QColor

from services.company_service import CompanyService
from services.formatting import (
    upper_tr,
    category_label,
    date_group,
    is_weekend,
    remaining_label,
    short_company_name,
    source_label,
    table_date,
    title_with_plate,
)
from services.reminder_service import ReminderService
from ui import icons
from ui.shell import FilterBar, Page
from ui.theme import tokens
from ui.widgets import (
    AccentRowDelegate,
    Badge,
    Card,
    DistributionStrip,
    MetricStrip,
    TableStack,
    add_group_row,
    button,
    cell_widget,
    align_headers,
    StickyGroupHeader,
    configure_columns,
)

VIEWS = (
    ("UPCOMING_30", "Önümüzdeki 30 gün"),
    ("TODAY", "Bugün"),
    ("UPCOMING_7", "Önümüzdeki 7 gün"),
    ("OVERDUE", "Gecikenler"),
    ("THIS_MONTH", "Bu ay"),
)

HEADERS = ["Tarih", "Şirket", "Yükümlülük", "Dönem / Kategori", "Durum"]


def status_tone(days: int) -> tuple[str, str]:
    if days < 0:
        return remaining_label(days), "danger"
    if days == 0:
        return "Bugün", "warning"
    if days <= 3:
        return remaining_label(days), "warning"
    return remaining_label(days), "neutral"


def source_tone(code: str) -> str:
    return {"GIB": "accent", "SGK": "info"}.get(code, "neutral")


def source_colour(code: str) -> str:
    t = tokens()
    return {"GIB": t.accent, "SGK": t.info}.get(code, t.text_faint)


def short_date_full(value) -> str:
    from services.formatting import long_date, weekday_short

    return f"{long_date(value)} {weekday_short(value)}"


logger = logging.getLogger(__name__)


class DashboardPage(Page):
    """Today's work and what is coming, for every company at a glance."""

    reminder_requested = Signal()
    navigate = Signal(str)

    def __init__(
        self,
        reminder_service: ReminderService,
        company_service: CompanyService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Ana Sayfa",
            "Bugün yapılması gerekenler ve yaklaşan resmî yükümlülükler.",
            parent,
        )
        self.reminder_service = reminder_service
        self.company_service = company_service
        self._items: list = []
        self._build()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        new_button = button("Hatırlatma Ekle", "primary", "plus")
        new_button.clicked.connect(self.reminder_requested.emit)
        self.header.add_action(new_button)

        self.metrics = MetricStrip()
        self.stat_today = self.metrics.add("today", "Bugün", "accent")
        self.stat_overdue = self.metrics.add("overdue", "Geciken")
        self.stat_upcoming = self.metrics.add("upcoming", "Yaklaşan 30 gün")
        self.stat_month = self.metrics.add("month", "Bu ay")
        self.stat_today.clicked.connect(lambda: self._select_view("TODAY"))
        self.stat_overdue.clicked.connect(lambda: self._select_view("OVERDUE"))
        self.stat_upcoming.clicked.connect(lambda: self._select_view("UPCOMING_30"))
        self.stat_month.clicked.connect(lambda: self._select_view("THIS_MONTH"))
        self.add(self.metrics)

        load_card = Card("Önümüzdeki 30 Gün")
        load_card.tighten()
        self.distribution = DistributionStrip()
        self.distribution.setToolTip(
            "Günlük yük. Bir çubuğun üzerine gelin: o günün tarihi ve kayıt sayısı."
        )
        load_card.add(self.distribution)
        self.add(load_card)

        card = Card()
        self.filters = FilterBar()
        self.view_combo = QComboBox()
        for key, text in VIEWS:
            self.view_combo.addItem(text, key)
        self.company_combo = QComboBox()
        self.company_combo.addItem("Tüm şirketler", None)
        self.source_combo = QComboBox()
        self.source_combo.addItem("Tüm kaynaklar", None)
        self.source_combo.addItem("Resmî (GİB / SGK)", "OFFICIAL")
        self.source_combo.addItem("Manuel", "MANUAL")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Başlık veya plaka ara")
        self.search_edit.setClearButtonEnabled(True)

        self.filters.add_field("Dönem", self.view_combo, 176)
        self.filters.add_field("Şirket", self.company_combo, 190)
        self.filters.add_field("Kaynak", self.source_combo, 168)
        self.filters.add_field("Başlık veya plaka ara", self.search_edit, 230)
        refresh = button("Yenile", "subtle", "refresh")
        refresh.clicked.connect(self.refresh)
        self.filters.finish()
        self.filters.add_widget(refresh)
        card.add(self.filters)

        self.stack = TableStack(
            HEADERS,
            "Yaklaşan yükümlülük yok",
            "Seçili filtrelerde gösterilecek kayıt bulunamadı. Filtreleri değiştirin "
            "veya yeni bir hatırlatma ekleyin.",
            "Hatırlatma Ekle",
            "calendar",
        )
        self.stack.empty.action_clicked.connect(self.reminder_requested.emit)
        self.table = self.stack.table
        # Date and status are predictable; company, title and period share the
        # rest so none of them collapses on a small screen.
        configure_columns(self.table, [92, 172, None, 200, 122])
        align_headers(self.table, center=(0, 4))
        self.sticky = StickyGroupHeader(self.table)
        self.accents = AccentRowDelegate(self.table)
        self.table.setItemDelegate(self.accents)
        self.table.setMouseTracking(True)
        self.table.entered.connect(lambda i: self.accents.set_hovered_row(i.row()))
        # Fires when the cursor is over the viewport but not over a row, which
        # is exactly when the highlight should go away.
        self.table.viewportEntered.connect(lambda: self.accents.set_hovered_row(-1))
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemDoubleClicked.connect(lambda _item: self._toggle_complete())
        card.add(self.stack)
        self.add(card, 1)

        for combo in (self.view_combo, self.company_combo, self.source_combo):
            combo.currentIndexChanged.connect(self.refresh)
        self.search_edit.textChanged.connect(self.refresh)

    # ------------------------------------------------------------------ data
    def _update_distribution(self, today: date) -> None:
        """How the next 30 days are loaded, one bar per day.

        Counted from every open record regardless of the screen's filters: the
        strip answers "when is it busy", not "what am I looking at".
        """
        from datetime import timedelta

        try:
            items = self.reminder_service.list_due(horizon_days=DistributionStrip.DAYS)
        except Exception:
            logger.warning("Dağılım okunamadı", exc_info=True)
            self.distribution.set_counts([])
            return

        tally: dict[date, int] = {}
        for item in items:
            tally[item.due_date] = tally.get(item.due_date, 0) + 1
        days = [today + timedelta(days=offset) for offset in range(DistributionStrip.DAYS)]
        self.distribution.set_counts([(day, tally.get(day, 0)) for day in days])

    def _select_view(self, key: str) -> None:
        index = self.view_combo.findData(key)
        if index >= 0:
            self.view_combo.setCurrentIndex(index)

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
        today = date.today()
        company_id = self.company_combo.currentData()
        source = self.source_combo.currentData()
        search = self.search_edit.text().strip() or None

        try:
            counts = self.reminder_service.get_dashboard_counts(today=today, company_id=company_id)
        except Exception:
            counts = {"today": 0, "upcoming": 0, "overdue": 0, "this_month": 0}
        self.stat_today.set_value(counts["today"])
        self.stat_upcoming.set_value(counts["upcoming"])
        self.stat_overdue.set_value(counts["overdue"], alert=counts["overdue"] > 0)
        self.stat_month.set_value(counts["this_month"])
        self._update_distribution(today)

        view = self.view_combo.currentData()
        if view == "TODAY":
            items = self.reminder_service.list_today(today=today, company_id=company_id)
        elif view == "UPCOMING_7":
            items = self.reminder_service.list_due(
                horizon_days=7, today=today, company_id=company_id, source_kind_filter=source, search=search
            )
        elif view == "OVERDUE":
            items = self.reminder_service.list_overdue(today=today, company_id=company_id)
        elif view == "THIS_MONTH":
            items = self.reminder_service.list_this_month(today=today, company_id=company_id)
        else:
            items = self.reminder_service.list_due(
                horizon_days=30, today=today, company_id=company_id, source_kind_filter=source, search=search
            )

        # Views computed by the service do not take the source/search filters, so
        # apply them here to keep every view consistent.
        if source:
            items = [item for item in items if item.source_kind == source]
        if search:
            needle = search.casefold()
            items = [
                item
                for item in items
                if needle in item.title.casefold() or needle in (item.plate or "").casefold()
            ]

        self._items = items
        self._populate(items, today)
        self.filters.set_summary(f"{len(items)} kayıt")
        self.stack.show_rows(len(items))

    def _populate(self, items: list, today: date) -> None:
        """Fill the table, grouped by how soon each item is due.

        A flat list of 70 dates makes the reader parse every row; the headings
        ("BUGÜN", "BU HAFTA", "EKİM 2026") let them jump straight to the part
        they care about.
        """
        self.table.setUpdatesEnabled(False)
        self.table.clearSpans()
        self.table.setRowCount(0)
        self._row_items = {}
        groups: dict[int, str] = {}
        accents: dict[int, str] = {}
        current_group = None

        for item in items:
            days = (item.due_date - today).days
            group = date_group(item.due_date, today)
            if group != current_group:
                groups[add_group_row(self.table, group)] = upper_tr(group)
                current_group = group

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setRowHeight(row, tokens().row_height)
            self._row_items[row] = item
            text, tone = status_tone(days)
            if tone in ("danger", "warning"):
                accents[row] = tone

            date_item = QTableWidgetItem(table_date(item.due_date))
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            date_item.setToolTip(short_date_full(item.due_date))
            if is_weekend(item.due_date):
                date_item.setForeground(QColor(tokens().warning))
            self.table.setItem(row, 0, date_item)

            company_item = QTableWidgetItem(short_company_name(item.company_name))
            company_item.setToolTip(item.company_name or "Şirkete bağlı olmayan kayıt")
            self.table.setItem(row, 1, company_item)

            title_item = QTableWidgetItem(title_with_plate(item.title, item.plate))
            tooltip = item.title
            if item.period_label:
                tooltip = f"{tooltip}\n{item.period_label}"
            if item.company_name:
                tooltip = f"{tooltip}\n{item.company_name}"
            title_item.setToolTip(tooltip)
            if item.source_kind == "OFFICIAL":
                title_item.setIcon(icons.icon("shield", 14, source_colour(item.source_label)))
            self.table.setItem(row, 2, title_item)

            detail = (
                category_label(item.category)
                if item.source_kind == "MANUAL"
                else f"{source_label(item.source_label)} · {item.period_label or '—'}"
            )
            detail_item = QTableWidgetItem(detail)
            detail_item.setToolTip(detail)
            self.table.setItem(row, 3, detail_item)

            self.table.setCellWidget(row, 4, cell_widget(Badge(text, tone)))

        self.accents.set_rows(accents)
        self.accents.set_spanned_rows(set(groups))
        self.sticky.set_groups(groups)
        self.table.setUpdatesEnabled(True)

    # ------------------------------------------------------------------ actions
    def _selected(self):
        return getattr(self, "_row_items", {}).get(self.table.currentRow())

    def _context_menu(self, position) -> None:
        item = self._selected()
        if item is None:
            return
        menu = QMenu(self)
        done = menu.addAction(icons.icon("check"), "Tamamlandı olarak işaretle")
        menu.addSeparator()
        goto = menu.addAction(icons.icon("bell"), "Hatırlatmalarda aç")
        action = menu.exec(self.table.viewport().mapToGlobal(position))
        if action == done:
            self._toggle_complete()
        elif action == goto:
            self.navigate.emit("reminders")

    def _toggle_complete(self) -> None:
        item = self._selected()
        if item is None:
            return
        try:
            if self.reminder_service.is_completed(item.source_kind, item.source_id, item.company_id):
                confirm = QMessageBox.question(
                    self,
                    "Geri al",
                    f"“{item.title}” tamamlandı olarak işaretli. Geri alınsın mı?",
                )
                if confirm == QMessageBox.StandardButton.Yes:
                    self.reminder_service.undo_complete(item.source_kind, item.source_id, item.company_id)
            else:
                self.reminder_service.complete(
                    source_kind=item.source_kind, source_id=item.source_id, company_id=item.company_id
                )
        except Exception as exc:
            QMessageBox.warning(self, "İşlem tamamlanamadı", str(exc))
            return
        self.refresh()
