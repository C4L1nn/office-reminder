from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
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

from services.formatting import short_company_name, table_date, title_with_plate
from services.company_service import CompanyService
from ui import icons
from ui.dialogs.company_dialog import CompanyDialog
from ui.dialogs.company_obligations_dialog import CompanyObligationsDialog
from ui.shell import Page
from ui.theme import tokens
from ui.widgets import (
    Badge,
    Card,
    EmptyState,
    button,
    data_row,
    fixed_cell,
    icon_button,
    set_list_placeholder,
    label,
    list_row,
    list_row_size,
    metric_row,
    separator,
)

KDV_LABELS = {
    "KDV_STANDARD_MONTHLY": "Aylık beyan",
    "KDV_STANDARD_QUARTERLY": "3 aylık beyan",
    "KDV_TEVKIFAT": "Tevkifat",
}
WAGE_LABELS = {
    "MONTHLY_1_END": "Ücret dönemi: 1 – ay sonu",
    "MONTHLY_15_14": "Ücret dönemi: 15 – takip eden ayın 14'ü",
}
def _status(days: int) -> tuple[str, str]:
    from ui.pages.dashboard_page import status_tone

    return status_tone(days)


CATEGORY_TITLES = {
    "TAX": "Vergi",
    "SGK": "SGK",
    "E_LEDGER": "e-Defter / e-Belge",
    "SYSTEM": "Bildirimler",
}


class CompaniesPage(Page):
    """Company list on the left, the selected company's profile on the right."""

    data_changed = Signal()

    def __init__(self, company_service: CompanyService, parent: QWidget | None = None) -> None:
        super().__init__(
            "Şirketler",
            "Her şirket için tabi olduğu vergi ve SGK yükümlülüklerini tanımlayın.",
            parent,
        )
        self.company_service = company_service
        self._companies: list = []
        self._build()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        new = button("Yeni Şirket", "primary", "plus")
        new.clicked.connect(self.create_company)
        self.header.add_action(new)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(tokens().space_sm)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Şirket adı veya vergi no")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_list)
        left_layout.addWidget(self.search_edit)

        self.list_widget = QListWidget()
        set_list_placeholder(
            self.list_widget,
            "Henüz şirket yok.\n“+ Yeni Şirket” ile ilkini ekleyin.",
        )
        self.list_widget.currentRowChanged.connect(self._show_selected)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._context_menu)
        self.list_widget.itemDoubleClicked.connect(lambda _i: self.edit_company())
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
        try:
            self._companies = self.company_service.list_all()
        except Exception as exc:
            QMessageBox.warning(self, "Şirketler yüklenemedi", str(exc))
            self._companies = []
        self._filter_list()

    def _filter_list(self) -> None:
        needle = self.search_edit.text().strip().casefold()
        visible = [
            company
            for company in self._companies
            if not needle
            or needle in company.name.casefold()
            or needle in (company.tax_number or "").casefold()
        ]
        previous = self._current_company_id()

        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self._visible = visible
        # One aggregate query instead of four per row.
        try:
            summaries = self.company_service.list_summaries()
        except Exception:
            summaries = {}

        for company in visible:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, company.id)
            item.setToolTip(f"{company.name}\n{company.tax_number or 'Vergi no yok'}")
            summary = summaries.get(company.id, {"obligations": 0, "vehicles": 0})
            details = [company.tax_number or "Vergi no yok",
                       f"{summary['obligations']} yükümlülük"]
            if summary.get("vehicles"):
                details.append(f"{summary['vehicles']} araç")
            widget = list_row(
                short_company_name(company.name),
                " · ".join(details),
                "" if company.is_active else "Pasif",
                muted=not company.is_active,
            )
            self.list_widget.addItem(item)
            item.setSizeHint(list_row_size())
            self.list_widget.setItemWidget(item, widget)
        self.list_widget.blockSignals(False)

        if visible:
            index = next((i for i, c in enumerate(visible) if c.id == previous), 0)
            self.list_widget.setCurrentRow(index)
        else:
            self._show_selected(-1)

    def _current_company_id(self) -> int | None:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected(self):
        company_id = self._current_company_id()
        return next((c for c in self._companies if c.id == company_id), None)

    # ------------------------------------------------------------------ detail pane
    def _clear_detail(self) -> None:
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _show_selected(self, _row: int = -1) -> None:
        self._clear_detail()
        company = self._selected()
        if company is None:
            empty = EmptyState(
                "Henüz şirket yok",
                "Takip edilecek ilk şirketi ekleyin; ardından tabi olduğu KDV, SGK ve diğer "
                "yükümlülükleri işaretleyin.",
                "building",
                "Yeni Şirket",
            )
            empty.action_clicked.connect(self.create_company)
            card = Card()
            card.add(empty)
            self.detail_layout.addWidget(card)
            self.detail_layout.addStretch()
            return

        self.detail_layout.addWidget(self._identity_card(company))
        self.detail_layout.addWidget(self._upcoming_card(company))
        self.detail_layout.addWidget(self._obligations_card(company))
        self.detail_layout.addStretch()

    def _identity_card(self, company) -> Card:
        card = Card(company.name)
        card.add_header_widget(Badge("Aktif" if company.is_active else "Pasif",
                                     "success" if company.is_active else "neutral"))
        edit = icon_button("pencil", "Şirketi düzenle")
        edit.clicked.connect(self.edit_company)
        card.add_header_widget(edit)

        try:
            summary = self.company_service.get_company_summary(company.id)
        except Exception:
            summary = {"obligations": 0, "vehicles": 0, "manual_open": 0, "official_active": 0}

        card.add(metric_row([
            ("Vergi no", company.tax_number or "—"),
            ("Yükümlülük", str(summary["obligations"])),
            ("Araç", str(summary["vehicles"])),
            ("Açık hatırlatma", str(summary["manual_open"])),
            ("Takipteki resmî tarih", str(summary["official_active"])),
        ]))

        if company.notes:
            card.add(separator())
            card.add(label(company.notes, "Muted", wrap=True))
        return card

    def _upcoming_card(self, company) -> Card:
        """What this company actually owes next — the reason the screen exists."""
        from datetime import date

        card = Card("Yaklaşan Tarihler")
        card.tighten()
        try:
            items = self.company_service.upcoming_for_company(company.id, limit=6)
        except Exception as exc:
            card.add(label(f"Okunamadı: {exc}", "Muted", wrap=True))
            return card

        if not items:
            card.add(label("Önümüzdeki 60 günde tarih yok.", "Muted", wrap=True))
            return card

        today = date.today()
        for item in items:
            text, tone = _status((item.due_date - today).days)
            date_label = label(table_date(item.due_date), "Mono")
            date_label.setFixedWidth(78)
            title = label(title_with_plate(item.title, item.plate))
            title.setToolTip(item.title)
            card.add(data_row([
                (date_label, 0),
                (title, 1),
                (fixed_cell(Badge(text, tone), 110), 0),
            ]))
        return card

    def _obligations_card(self, company) -> Card:
        card = Card("Yükümlülük Profili")
        manage = button("Düzenle", "subtle", "settings")
        manage.clicked.connect(self.edit_obligations)
        card.add_header_widget(manage)

        try:
            obligations = [o for o in self.company_service.get_company_obligations(company.id) if o.is_active]
            gaps = self.company_service.profile_gaps(company.id)
            kdv_variants = self.company_service.get_kdv_profile(company.id) or []
            wage_period = self.company_service.get_sgk_wage_period(company.id)
        except Exception as exc:
            card.add(label(f"Profil okunamadı: {exc}", "Muted", wrap=True))
            return card

        if not obligations:
            empty = EmptyState(
                "Yükümlülük seçilmedi",
                "Bu şirket için hiçbir resmî yükümlülük işaretlenmemiş; dashboard'da resmî "
                "tarih görünmez.",
                "shield",
                "Yükümlülük Seç",
            )
            empty.action_clicked.connect(self.edit_obligations)
            card.add(empty)
            return card

        if gaps:
            warning = Badge("Profil tamamlanmalı", "warning")
            missing = ", ".join(
                {"GIB_KDV": "KDV varyantı", "SGK_4A_PREMIUM": "SGK ücret dönemi"}.get(code, code)
                for code in gaps
            )
            row = QHBoxLayout()
            row.setSpacing(tokens().space_sm)
            row.addWidget(warning)
            row.addWidget(label(f"Eksik: {missing}. Seçilmeden ilgili resmî tarihler gösterilmez.",
                                "Muted", wrap=True), 1)
            card.add_layout(row)

        by_category: dict[str, list] = {}
        for obligation in obligations:
            by_category.setdefault(obligation.category, []).append(obligation)

        for category in sorted(by_category, key=lambda c: list(CATEGORY_TITLES).index(c)
                               if c in CATEGORY_TITLES else 99):
            card.add(label(CATEGORY_TITLES.get(category, category), "FieldLabel"))
            for obligation in by_category[category]:
                row = QHBoxLayout()
                row.setSpacing(tokens().space_sm)
                row.setContentsMargins(6, 0, 0, 0)
                tick = QWidget()
                tick_layout = QHBoxLayout(tick)
                tick_layout.setContentsMargins(0, 0, 0, 0)
                mark = label("")
                mark.setPixmap(icons.pixmap("check", 14, tokens().success))
                tick_layout.addWidget(mark)
                row.addWidget(tick)
                row.addWidget(label(obligation.name))

                detail = ""
                if obligation.code == "GIB_KDV" and kdv_variants:
                    detail = " · ".join(KDV_LABELS.get(v, v) for v in kdv_variants)
                elif obligation.code == "SGK_4A_PREMIUM" and wage_period:
                    detail = WAGE_LABELS.get(wage_period, wage_period)
                if detail:
                    row.addWidget(Badge(detail, "accent"))
                row.addStretch()
                holder = QWidget()
                holder.setLayout(row)
                card.add(holder)
        return card

    # ------------------------------------------------------------------ actions
    def create_company(self) -> None:
        dialog = CompanyDialog(self)
        if dialog.exec() != CompanyDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        try:
            company_id = self.company_service.create(data["name"], data["tax_number"], data["notes"])
            if not data["is_active"]:
                self.company_service.set_active(company_id, False)
        except Exception as exc:
            QMessageBox.warning(self, "Şirket eklenemedi", str(exc))
            return
        self.refresh()
        self._select_company(company_id)
        self.data_changed.emit()
        # A company with no obligation profile shows nothing, so offer the next
        # step instead of leaving an empty screen behind.
        if QMessageBox.question(
            self,
            "Yükümlülükler",
            f"“{data['name']}” eklendi.\n\nTabi olduğu vergi ve SGK yükümlülüklerini şimdi seçmek ister misiniz?",
        ) == QMessageBox.StandardButton.Yes:
            self.edit_obligations()

    def select_company(self, company_id: int) -> bool:
        """Bring a company into view; used by the global search."""
        for row in range(self.list_widget.count()):
            if self.list_widget.item(row).data(Qt.ItemDataRole.UserRole) == company_id:
                self.list_widget.setCurrentRow(row)
                return True
        return False

    def _select_company(self, company_id: int) -> None:
        self.select_company(company_id)

    def edit_company(self) -> None:
        company = self._selected()
        if company is None:
            return
        dialog = CompanyDialog(self, existing=company)
        if dialog.exec() != CompanyDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        try:
            self.company_service.update(
                company.id, name=data["name"], tax_number=data["tax_number"], notes=data["notes"]
            )
            self.company_service.set_active(company.id, data["is_active"])
        except Exception as exc:
            QMessageBox.warning(self, "Güncellenemedi", str(exc))
            return
        self.refresh()
        self.data_changed.emit()

    def edit_obligations(self) -> None:
        company = self._selected()
        if company is None:
            return
        dialog = CompanyObligationsDialog(self.company_service, company.id, company.name, self)
        if dialog.exec() != CompanyObligationsDialog.DialogCode.Accepted:
            return
        selection = dialog.get_selection()
        try:
            # Obligation set and profile are written together, in one transaction.
            self.company_service.save_obligation_profile(
                company.id,
                selection["obligation_type_ids"],
                kdv_variants=selection["kdv_variants"],
                sgk_wage_period=selection["sgk_wage_period"],
            )
        except Exception as exc:
            QMessageBox.warning(self, "Yükümlülükler kaydedilemedi", str(exc))
            return
        self._show_selected()
        self.data_changed.emit()

    def toggle_active(self) -> None:
        company = self._selected()
        if company is None:
            return
        try:
            self.company_service.set_active(company.id, not company.is_active)
        except Exception as exc:
            QMessageBox.warning(self, "Değiştirilemedi", str(exc))
            return
        self.refresh()
        self.data_changed.emit()

    def delete_company(self) -> None:
        company = self._selected()
        if company is None:
            return
        confirm = QMessageBox.question(
            self,
            "Şirketi sil",
            f"“{company.name}” ve ona bağlı araçlar, hatırlatmalar ve tamamlama geçmişi kalıcı "
            "olarak silinecek.\n\nBunun yerine şirketi pasife almayı düşünebilirsiniz.\n\nSilinsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.company_service.delete(company.id)
        except Exception as exc:
            QMessageBox.warning(self, "Silinemedi", str(exc))
            return
        self.refresh()
        self.data_changed.emit()

    def _context_menu(self, position) -> None:
        if self._selected() is None:
            return
        menu = QMenu(self)
        edit = menu.addAction(icons.icon("pencil"), "Düzenle")
        obligations = menu.addAction(icons.icon("shield"), "Yükümlülükler")
        toggle = menu.addAction("Aktif / Pasif")
        menu.addSeparator()
        remove = menu.addAction(icons.icon("trash"), "Sil")
        action = menu.exec(self.list_widget.viewport().mapToGlobal(position))
        if action == edit:
            self.edit_company()
        elif action == obligations:
            self.edit_obligations()
        elif action == toggle:
            self.toggle_active()
        elif action == remove:
            self.delete_company()
