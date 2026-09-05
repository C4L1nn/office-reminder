from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from services.company_service import CompanyService
from services.formatting import category_label, short_company_name, table_date
from services.reminder_service import ReminderService
from ui import icons
from ui.dialogs.reminder_dialog import ReminderDialog
from ui.dialogs.vehicle_dialog import VehicleDialog
from ui.pages.dashboard_page import status_tone
from ui.shell import Page
from ui.theme import tokens
from ui.widgets import (
    Badge,
    Card,
    EmptyState,
    button,
    icon_button,
    set_list_placeholder,
    data_row,
    fixed_cell,
    label,
    list_row,
    list_row_size,
    metric_row,
    separator,
)

# The reminder kinds a vehicle normally carries; offered as one-click templates.
VEHICLE_TEMPLATES = (
    ("VEHICLE_INSPECTION", "Araç Muayenesi", 365),
    ("TRAFFIC_INSURANCE", "Trafik Sigortası", 365),
    ("KASKO", "Kasko", 365),
    ("GENERAL", "Periyodik Bakım", 180),
)


class VehiclesPage(Page):
    """Vehicles per company, with the reminders attached to each one."""

    data_changed = Signal()

    def __init__(
        self,
        company_service: CompanyService,
        reminder_service: ReminderService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Araçlar",
            "Plaka bazında araç takibi; muayene, sigorta ve kasko hatırlatmaları araca bağlanır.",
            parent,
        )
        self.company_service = company_service
        self.reminder_service = reminder_service
        self._vehicles: list = []
        self._build()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        new = button("Yeni Araç", "primary", "plus")
        new.clicked.connect(self.create_vehicle)
        self.header.add_action(new)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(tokens().space_sm)

        self.company_filter = QComboBox()
        self.company_filter.addItem("Tüm şirketler", None)
        self.company_filter.currentIndexChanged.connect(self.refresh)
        left_layout.addWidget(self.company_filter)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Plaka, marka veya model")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_list)
        left_layout.addWidget(self.search_edit)

        self.list_widget = QListWidget()
        set_list_placeholder(
            self.list_widget,
            "Henüz araç yok.\n“+ Yeni Araç” ile ilkini ekleyin.",
        )
        self.list_widget.currentRowChanged.connect(self._show_selected)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._context_menu)
        self.list_widget.itemDoubleClicked.connect(lambda _i: self.edit_vehicle())
        left_layout.addWidget(self.list_widget, 1)
        splitter.addWidget(left)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_host = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_host)
        self.detail_layout.setContentsMargins(tokens().space, 0, 0, 0)
        self.detail_layout.setSpacing(tokens().space)
        self.detail_scroll.setWidget(self.detail_host)
        splitter.addWidget(self.detail_scroll)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 720])
        self.add(splitter, 1)

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self._load_companies()
        company_id = self.company_filter.currentData()
        try:
            self._vehicles = self.company_service.list_vehicles(company_id=company_id)
        except Exception as exc:
            QMessageBox.warning(self, "Araçlar yüklenemedi", str(exc))
            self._vehicles = []
        self._filter_list()

    def _load_companies(self) -> None:
        try:
            companies = self.company_service.list_active()
        except Exception:
            companies = []
        current = self.company_filter.currentData()
        self.company_filter.blockSignals(True)
        self.company_filter.clear()
        self.company_filter.addItem("Tüm şirketler", None)
        for company in companies:
            self.company_filter.addItem(company.name, company.id)
        if current is not None:
            index = self.company_filter.findData(current)
            if index >= 0:
                self.company_filter.setCurrentIndex(index)
        self.company_filter.blockSignals(False)

    def _filter_list(self) -> None:
        needle = self.search_edit.text().strip().casefold()
        visible = [
            vehicle
            for vehicle in self._vehicles
            if not needle
            or needle in vehicle.plate.casefold()
            or needle in (vehicle.make or "").casefold()
            or needle in (vehicle.model or "").casefold()
        ]
        previous = self._current_vehicle_id()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for vehicle in visible:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, vehicle.id)
            item.setToolTip(f"{vehicle.plate}\n{vehicle.company_name or '—'}")
            descriptor = " ".join(p for p in [vehicle.make, vehicle.model] if p)
            secondary = " · ".join(
                p for p in [descriptor, short_company_name(vehicle.company_name)] if p
            )
            widget = list_row(
                vehicle.plate, secondary,
                "" if vehicle.is_active else "Pasif",
                muted=not vehicle.is_active,
            )
            self.list_widget.addItem(item)
            item.setSizeHint(list_row_size())
            self.list_widget.setItemWidget(item, widget)
        self.list_widget.blockSignals(False)

        if visible:
            index = next((i for i, v in enumerate(visible) if v.id == previous), 0)
            self.list_widget.setCurrentRow(index)
        else:
            self._show_selected(-1)

    def select_vehicle(self, vehicle_id: int) -> bool:
        """Bring a vehicle into view; used by the global search."""
        for row in range(self.list_widget.count()):
            if self.list_widget.item(row).data(Qt.ItemDataRole.UserRole) == vehicle_id:
                self.list_widget.setCurrentRow(row)
                return True
        return False

    def _current_vehicle_id(self) -> int | None:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected(self):
        vehicle_id = self._current_vehicle_id()
        return next((v for v in self._vehicles if v.id == vehicle_id), None)

    # ------------------------------------------------------------------ detail
    def _clear_detail(self) -> None:
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _show_selected(self, _row: int = -1) -> None:
        self._clear_detail()
        vehicle = self._selected()
        if vehicle is None:
            empty = EmptyState(
                "Araç kaydı yok",
                "Araç ekleyin; muayene, trafik sigortası ve kasko tarihlerini plakayla birlikte "
                "takip edin.",
                "car",
                "Yeni Araç",
            )
            empty.action_clicked.connect(self.create_vehicle)
            card = Card()
            card.add(empty)
            self.detail_layout.addWidget(card)
            self.detail_layout.addStretch()
            return

        self.detail_layout.addWidget(self._identity_card(vehicle))
        self.detail_layout.addWidget(self._reminders_card(vehicle))
        self.detail_layout.addStretch()

    def _identity_card(self, vehicle) -> Card:
        card = Card(vehicle.plate)
        card.add_header_widget(
            Badge("Aktif" if vehicle.is_active else "Pasif", "success" if vehicle.is_active else "neutral")
        )
        edit = icon_button("pencil", "Aracı düzenle")
        edit.clicked.connect(self.edit_vehicle)
        card.add_header_widget(edit)

        card.add(metric_row([
            ("Şirket", short_company_name(vehicle.company_name)),
            ("Marka", vehicle.make or "—"),
            ("Model", vehicle.model or "—"),
            ("Model yılı", str(vehicle.model_year) if vehicle.model_year else "—"),
        ]))

        if vehicle.notes:
            card.add(separator())
            card.add(label(vehicle.notes, "Muted", wrap=True))
        return card

    def _reminders_card(self, vehicle) -> Card:
        card = Card("Araç Hatırlatmaları")
        add = button("Hatırlatma Ekle", "subtle", "plus")
        add.clicked.connect(lambda: self.add_reminder(vehicle))
        card.add_header_widget(add)

        try:
            records = self.reminder_service.search_manual(limit=200)
            records = [r for r in records if r.vehicle_id == vehicle.id]
        except Exception:
            records = []

        if not records:
            card.add(label("Bu araç için henüz hatırlatma yok.", "Muted", wrap=True))
            card.add(self._templates(vehicle))
            return card

        card.tighten()
        today = date.today()
        for record in sorted(records, key=lambda r: r.due_date):
            due = date.fromisoformat(record.due_date)

            glyph = label("")
            glyph.setPixmap(icons.pixmap("calendar", 15, tokens().text_faint))

            date_label = label(table_date(due), "Mono")
            date_label.setFixedWidth(78)

            if record.status == "COMPLETED":
                status = Badge("Tamamlandı", "success")
            else:
                text, tone = status_tone((due - today).days)
                status = Badge(text, tone)

            card.add(data_row([
                (glyph, 0),
                (date_label, 0),
                (label(record.title), 1),
                (fixed_cell(Badge(category_label(record.category), "neutral"), 140), 0),
                (fixed_cell(status, 110), 0),
            ]))

        card.add(separator())
        card.add(self._templates(vehicle))
        return card

    def _templates(self, vehicle) -> QWidget:
        """One-click starting points for the reminders a vehicle always needs."""
        templates = QHBoxLayout()
        templates.setContentsMargins(0, 0, 0, 0)
        templates.setSpacing(tokens().space_sm)
        templates.addWidget(label("Hızlı ekle:", "FieldLabel"))
        for code, title, _days in VEHICLE_TEMPLATES:
            chip = button(title, "subtle")
            chip.clicked.connect(
                lambda _checked=False, c=code, t=title: self.add_reminder(vehicle, category=c, title=t)
            )
            templates.addWidget(chip)
        templates.addStretch()
        holder = QWidget()
        holder.setLayout(templates)
        return holder

    # ------------------------------------------------------------------ actions
    def create_vehicle(self) -> None:
        if not self.company_service.list_active():
            QMessageBox.information(
                self,
                "Önce şirket ekleyin",
                "Araçlar bir şirkete bağlı tutulur. Şirketler ekranından en az bir şirket ekleyin.",
            )
            return
        dialog = VehicleDialog(self.company_service, self, company_id=self.company_filter.currentData())
        if dialog.exec() != VehicleDialog.DialogCode.Accepted:
            return
        try:
            self.company_service.create_vehicle(**dialog.get_data())
        except Exception as exc:
            QMessageBox.warning(self, "Araç eklenemedi", self._friendly(exc))
            return
        self.refresh()
        self.data_changed.emit()

    def edit_vehicle(self) -> None:
        vehicle = self._selected()
        if vehicle is None:
            return
        dialog = VehicleDialog(self.company_service, self, existing=vehicle)
        if dialog.exec() != VehicleDialog.DialogCode.Accepted:
            return
        try:
            self.company_service.update_vehicle(vehicle.id, **dialog.get_data())
        except Exception as exc:
            QMessageBox.warning(self, "Güncellenemedi", self._friendly(exc))
            return
        self.refresh()
        self.data_changed.emit()

    def add_reminder(self, vehicle, category: str = "VEHICLE_INSPECTION", title: str = "") -> None:
        prefill = {
            "company_id": vehicle.company_id,
            "vehicle_id": vehicle.id,
            "category": category,
            "title": f"{title} — {vehicle.plate}" if title else "",
        }
        dialog = ReminderDialog(self.reminder_service, self.company_service, self, prefill=prefill)
        if dialog.exec() != ReminderDialog.DialogCode.Accepted:
            return
        try:
            self.reminder_service.create_manual(**dialog.get_data())
        except Exception as exc:
            QMessageBox.warning(self, "Hatırlatma kaydedilemedi", str(exc))
            return
        self._show_selected()
        self.data_changed.emit()

    def toggle_active(self) -> None:
        vehicle = self._selected()
        if vehicle is None:
            return
        try:
            self.company_service.set_vehicle_active(vehicle.id, not vehicle.is_active)
        except Exception as exc:
            QMessageBox.warning(self, "Değiştirilemedi", str(exc))
            return
        self.refresh()

    def delete_vehicle(self) -> None:
        vehicle = self._selected()
        if vehicle is None:
            return
        confirm = QMessageBox.question(
            self,
            "Aracı sil",
            f"“{vehicle.plate}” silinsin mi?\n\nBu araca bağlı hatırlatmalar silinmez, "
            "araç bağlantıları kaldırılır.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.company_service.delete_vehicle(vehicle.id)
        except Exception as exc:
            QMessageBox.warning(self, "Silinemedi", str(exc))
            return
        self.refresh()
        self.data_changed.emit()

    @staticmethod
    def _friendly(exc: Exception) -> str:
        text = str(exc)
        if "UNIQUE" in text.upper() and "plate" in text.lower():
            return "Bu plaka başka bir araçta kayıtlı."
        return text

    def _context_menu(self, position) -> None:
        vehicle = self._selected()
        if vehicle is None:
            return
        menu = QMenu(self)
        edit = menu.addAction(icons.icon("pencil"), "Düzenle")
        reminder = menu.addAction(icons.icon("bell"), "Hatırlatma ekle")
        toggle = menu.addAction("Aktif / Pasif")
        menu.addSeparator()
        remove = menu.addAction(icons.icon("trash"), "Sil")
        action = menu.exec(self.list_widget.viewport().mapToGlobal(position))
        if action == edit:
            self.edit_vehicle()
        elif action == reminder:
            self.add_reminder(vehicle)
        elif action == toggle:
            self.toggle_active()
        elif action == remove:
            self.delete_vehicle()
