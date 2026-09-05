from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTableWidgetItem,
    QWidget,
)

from services.company_service import CompanyService
from services.formatting import (
    long_date,
    remaining_label,
    upper_tr,
    category_label,
    date_group,
    is_weekend,
    recurrence_label,
    short_company_name,
    source_label,
    table_date,
    title_with_plate,
)
from services.export_service import (
    ExportError,
    default_name,
    rows_from_items,
    write_pdf,
    write_xlsx,
)
from services.reminder_service import ReminderService
from ui import icons
from ui.dialogs.quick_add_dialog import QuickAddDialog
from ui.dialogs.reminder_dialog import CATEGORY_CHOICES, ReminderDialog
from ui.pages.dashboard_page import source_colour, source_tone, status_tone
from ui.shell import FilterBar, Page
from ui.theme import tokens
from ui.widgets import (
    AccentRowDelegate,
    Badge,
    Card,
    TableStack,
    add_group_row,
    align_headers,
    button,
    cell_widget,
    StickyGroupHeader,
    configure_columns,
    icon_button,
    label,
)

logger = logging.getLogger(__name__)

HEADERS = ["Tarih", "Şirket", "Başlık", "Dönem / Kategori", "Durum"]

STATUS_VIEWS = (
    ("ALL_OPEN", "Açık ve geciken"),
    ("OPEN", "Yalnızca açık"),
    ("OVERDUE", "Yalnızca geciken"),
    ("COMPLETED", "Tamamlananlar"),
)


class RemindersPage(Page):
    """Every obligation — official and manual — in one filterable list."""

    def __init__(
        self,
        reminder_service: ReminderService,
        company_service: CompanyService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Hatırlatmalar",
            "Resmî takvim kayıtları ile kendi eklediğiniz hatırlatmaları birlikte yönetin.",
            parent,
        )
        self.reminder_service = reminder_service
        self.company_service = company_service
        from services.holiday_service import HolidayService

        self._holidays = HolidayService(reminder_service.database)
        self._items: list = []
        self._build()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        self.export_button = icon_button("download", "Listeyi dışa aktar", "subtle")
        self.export_button.clicked.connect(self._export_menu)
        self.header.add_action(self.export_button)

        quick = button("Hızlı Ekle", "subtle")
        quick.clicked.connect(self._quick_add)
        new = button("Yeni Hatırlatma", "primary", "plus")
        new.clicked.connect(self.create_reminder)
        self.header.add_action(quick)
        self.header.add_action(new)

        card = Card()
        self.filters = FilterBar()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Başlık, not veya plaka")
        self.search_edit.setClearButtonEnabled(True)

        self.company_combo = QComboBox()
        self.company_combo.addItem("Tüm şirketler", None)

        self.source_combo = QComboBox()
        self.source_combo.addItem("Tüm kaynaklar", None)
        self.source_combo.addItem("Resmî (GİB / SGK)", "OFFICIAL")
        self.source_combo.addItem("Manuel", "MANUAL")

        self.category_combo = QComboBox()
        self.category_combo.addItem("Tüm kategoriler", None)
        for code, text in CATEGORY_CHOICES:
            self.category_combo.addItem(text, code)

        self.status_combo = QComboBox()
        for code, text in STATUS_VIEWS:
            self.status_combo.addItem(text, code)

        self.filters.add_field("Başlık, not veya plaka", self.search_edit, 226)
        self.filters.add_field("Şirket", self.company_combo, 178)
        self.filters.add_field("Kaynak", self.source_combo, 166)
        self.filters.add_field("Kategori", self.category_combo, 168)
        self.filters.add_field("Durum", self.status_combo, 164)
        self.filters.finish()
        card.add(self.filters)

        self.stack = TableStack(
            HEADERS,
            "Hiç hatırlatma yok",
            "Seçili filtrelerde kayıt bulunamadı. Araç muayenesi, kasko veya sözleşme gibi "
            "kendi hatırlatmalarınızı ekleyebilirsiniz.",
            "Yeni Hatırlatma",
            "bell",
        )
        self.stack.empty.action_clicked.connect(self.create_reminder)
        self.table = self.stack.table
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
        # Month-end means completing many rows at once, so the table allows a
        # multi-row selection; single-record actions still use the current row.
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.customContextMenuRequested.connect(self._context_menu)
        copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        copy_shortcut.activated.connect(self.copy_selected)
        # Dropping a receipt straight onto its row beats opening a dialog and
        # browsing back to the folder it came from.
        self.table.setAcceptDrops(True)
        self.table.viewport().setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.table.viewport().installEventFilter(self)
        self.table.itemDoubleClicked.connect(lambda _item: self.edit_selected())
        card.add(self.stack)

        self.bulk_bar = QWidget()
        bulk = QHBoxLayout(self.bulk_bar)
        bulk.setContentsMargins(0, 0, 0, 0)
        bulk.setSpacing(tokens().space_sm)
        self.bulk_label = label("", "Caption")
        bulk.addWidget(self.bulk_label)
        bulk.addStretch()
        self.bulk_complete_button = button("Seçilenleri tamamla", "subtle", "check")
        self.bulk_complete_button.clicked.connect(self._complete_selected)
        bulk.addWidget(self.bulk_complete_button)
        self.bulk_bar.hide()
        card.add(self.bulk_bar)

        self.add(card, 1)

        for combo in (self.company_combo, self.source_combo, self.category_combo, self.status_combo):
            combo.currentIndexChanged.connect(self.refresh)
        self.search_edit.textChanged.connect(self.refresh)

    # ------------------------------------------------------------------ data
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
        status = self.status_combo.currentData()
        source = self.source_combo.currentData()
        company_id = self.company_combo.currentData()
        category = self.category_combo.currentData()
        search = self.search_edit.text().strip() or None

        if status == "COMPLETED":
            items = self._completed_items(company_id, category, search, source)
        elif status == "OVERDUE":
            items = self.reminder_service.list_overdue(today=today, company_id=company_id)
            items = self._filter(items, source, category, search)
        else:
            items = self.reminder_service.list_due(
                horizon_days=365,
                today=today,
                company_id=company_id,
                include_overdue=(status == "ALL_OPEN"),
                category=category,
                search=search,
                source_kind_filter=source,
            )

        self._items = items
        self._populate(items, today, completed=(status == "COMPLETED"))
        self.filters.set_summary(f"{len(items)} kayıt")
        self.stack.show_rows(len(items))

    def _completed_items(self, company_id, category, search, source) -> list:
        from services.reminder_service import DueItem

        if source == "OFFICIAL":
            return []
        try:
            records = self.reminder_service.search_manual(
                status="COMPLETED", company_id=company_id, category=category, search=search, limit=300
            )
        except Exception:
            return []
        return [
            DueItem(
                source_kind="MANUAL",
                source_id=record.id,
                company_id=record.company_id,
                company_name=record.company_name,
                title=record.title,
                due_date=date.fromisoformat(record.due_date),
                source_label="MANUEL",
                category=record.category,
                due_time=record.due_time,
                recurrence_kind=record.recurrence_kind,
                vehicle_id=record.vehicle_id,
                plate=record.plate,
            )
            for record in records
        ]

    @staticmethod
    def _filter(items: list, source, category, search) -> list:
        result = items
        if source:
            result = [i for i in result if i.source_kind == source]
        if category:
            result = [i for i in result if (i.category or "") == category]
        if search:
            needle = search.casefold()
            result = [
                i for i in result if needle in i.title.casefold() or needle in (i.plate or "").casefold()
            ]
        return result

    def _populate(self, items: list, today: date, completed: bool) -> None:
        """Fill the table, grouped by due window, densest legible layout."""
        self.table.setUpdatesEnabled(False)
        self.table.clearSpans()
        self.table.setRowCount(0)
        self._row_items = {}
        groups: dict[int, str] = {}
        # One query for the whole table rather than one per row.
        try:
            from services.attachment_service import AttachmentService

            with_files = AttachmentService(
                self.reminder_service.database
            ).ids_with_attachments("MANUAL")
        except Exception:
            logger.warning("Ek göstergesi okunamadı", exc_info=True)
            with_files = set()
        accents: dict[int, str] = {}
        current_group = None

        for item in items:
            group = "TAMAMLANAN" if completed else date_group(item.due_date, today)
            if group != current_group:
                groups[add_group_row(self.table, group)] = upper_tr(group)
                current_group = group

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setRowHeight(row, tokens().row_height)
            self._row_items[row] = item

            date_item = QTableWidgetItem(table_date(item.due_date))
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            date_item.setToolTip(self._due_tooltip(item, today))
            if is_weekend(item.due_date) and not completed:
                date_item.setForeground(QColor(tokens().warning))
            self.table.setItem(row, 0, date_item)

            company_item = QTableWidgetItem(short_company_name(item.company_name))
            company_item.setToolTip(item.company_name or "Şirkete bağlı olmayan kayıt")
            self.table.setItem(row, 1, company_item)

            title_item = QTableWidgetItem(title_with_plate(item.title, item.plate))
            title_item.setToolTip(item.title)
            if item.source_kind == "OFFICIAL":
                title_item.setIcon(icons.icon("shield", 14, source_colour(item.source_label)))
            elif item.source_id in with_files:
                title_item.setIcon(icons.icon("paperclip", 14, tokens().text_faint))
                title_item.setToolTip(f"{item.title}\n(dosya eki var)")
            self.table.setItem(row, 2, title_item)

            if item.source_kind == "MANUAL":
                detail = category_label(item.category)
                repeat = recurrence_label(item.recurrence_kind)
                if repeat != "—":
                    detail = f"{detail} · {repeat}"
            else:
                detail = f"{source_label(item.source_label)} · {item.period_label or '—'}"
            detail_item = QTableWidgetItem(detail)
            detail_item.setToolTip(detail)
            self.table.setItem(row, 3, detail_item)

            if completed:
                self.table.setCellWidget(row, 4, cell_widget(Badge("Tamamlandı", "success")))
            else:
                text, tone = status_tone((item.due_date - today).days)
                if tone in ("danger", "warning"):
                    accents[row] = tone
                self.table.setCellWidget(row, 4, cell_widget(Badge(text, tone)))

        self.accents.set_rows(accents)
        self.accents.set_spanned_rows(set(groups))
        self.sticky.set_groups(groups)
        self.table.setUpdatesEnabled(True)

    # ------------------------------------------------------------------ actions
    def _selected(self):
        """The record under the cursor.

        Not `self._items[row]`: the table also holds date-group header rows, so
        a visual row number is not an index into the item list. Getting this
        wrong edited or completed the wrong record.
        """
        return getattr(self, "_row_items", {}).get(self.table.currentRow())

    def reveal(self, title: str) -> None:
        """Filter down to one record so the global search can land on it.

        Filtering rather than scrolling: the record may be completed or outside
        the current status view, in which case scrolling would find nothing.
        """
        self.status_combo.setCurrentIndex(0)
        self.search_edit.setText(title)
        self.refresh()
        if self._row_items:
            self.table.setCurrentCell(min(self._row_items), 0)

    # --------------------------------------------------------------- drop files
    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        """Accept files dropped onto a manual reminder's row."""
        if watched is not self.table.viewport():
            return super().eventFilter(watched, event)

        kind = event.type()
        if kind in (event.Type.DragEnter, event.Type.DragMove):
            item = self._row_at(event.position().toPoint())
            if item is not None and event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                event.ignore()
            return True
        if kind == event.Type.Drop:
            self._drop_files(event)
            return True
        return super().eventFilter(watched, event)

    def _row_at(self, point):
        """The record under a screen point, or None for a heading or empty row."""
        row = self.table.rowAt(point.y())
        item = getattr(self, "_row_items", {}).get(row)
        # Official dates are not ours to attach paperwork to.
        return item if item is not None and item.source_kind == "MANUAL" else None

    def _drop_files(self, event) -> None:
        from services.attachment_service import AttachmentError, AttachmentService

        item = self._row_at(event.position().toPoint())
        if item is None:
            event.ignore()
            return
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()

        service = AttachmentService(self.reminder_service.database)
        attached, failures = 0, []
        for path in paths:
            try:
                service.attach("MANUAL", item.source_id, path)
                attached += 1
            except AttachmentError as exc:
                failures.append(f"{path.name}: {exc}")
            except Exception as exc:
                logger.warning("Sürüklenen dosya eklenemedi", exc_info=True)
                failures.append(f"{path.name}: {exc}")

        if attached:
            self.notify("Dosya eklendi", f"{attached} dosya · {item.title}")
            self.refresh()
        if failures:
            QMessageBox.warning(
                self, "Bazı dosyalar eklenemedi", "\n".join(failures[:6])
            )

    def _due_tooltip(self, item, today: date) -> str:
        """Calendar days and working days: only the second one is workable.

        A deadline 24 days out can be 16 working days out once a bayram falls
        in between, and that is the number that decides whether the work fits.
        """
        parts = [long_date(item.due_date)]
        if item.due_time:
            parts.append(f"Saat {item.due_time}")
        days = (item.due_date - today).days
        if days > 0:
            working = self._holidays.working_days_between(today, item.due_date)
            parts.append(f"{days} gün · {working} iş günü")
        else:
            parts.append(remaining_label(days))
        return "\n".join(parts)

    def copy_selected(self) -> None:
        """Put the selected rows on the clipboard as plain text.

        The office retypes these lines into e-mails and messages all day; there
        is nothing to be gained by making them retype what is already on screen.
        """
        items = self._selected_items() or [self._selected()]
        items = [item for item in items if item is not None]
        if not items:
            return
        lines = [
            " · ".join(
                [
                    item.company_name or "Genel",
                    title_with_plate(item.title, item.plate),
                    item.due_date.strftime("%d.%m.%Y"),
                ]
            )
            for item in items
        ]
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText("\n".join(lines))
        self.notify("Panoya kopyalandı", f"{len(lines)} satır")

    def _selected_items(self) -> list:
        """Every selected data row, in table order. Group headings are skipped."""
        mapping = getattr(self, "_row_items", {})
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return [mapping[row] for row in rows if row in mapping]

    def _selection_changed(self) -> None:
        items = self._selected_items()
        if len(items) < 2:
            self.bulk_bar.hide()
            return
        self.bulk_label.setText(f"{len(items)} kayıt seçildi")
        self.bulk_complete_button.setText(f"Seçilenleri tamamla ({len(items)})")
        self.bulk_bar.show()

    def _complete_selected(self) -> None:
        """Complete every selected record, one atomic call each.

        The loop deliberately reuses the single-record path: a recurring
        reminder still produces its next occurrence, and one failure does not
        roll back the records that already succeeded.
        """
        items = self._selected_items()
        if not items:
            return
        confirm = QMessageBox.question(
            self,
            "Seçilenleri tamamla",
            f"{len(items)} kayıt tamamlandı olarak işaretlenecek. Devam edilsin mi?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        done = 0
        failures: list[str] = []
        for item in items:
            try:
                if not self.reminder_service.is_completed(
                    item.source_kind, item.source_id, item.company_id
                ):
                    self.reminder_service.complete(
                        source_kind=item.source_kind,
                        source_id=item.source_id,
                        company_id=item.company_id,
                    )
                done += 1
            except Exception as exc:
                logger.warning("Toplu tamamlama başarısız: %s", item.title, exc_info=True)
                failures.append(f"{item.title}: {exc}")

        self.refresh()
        if failures:
            QMessageBox.warning(
                self,
                "Bazı kayıtlar tamamlanamadı",
                f"{done} kayıt tamamlandı, {len(failures)} kayıt tamamlanamadı:\n\n"
                + "\n".join(failures[:8]),
            )

    # ------------------------------------------------------------------ export
    def _export_menu(self) -> None:
        menu = QMenu(self)
        excel = menu.addAction("Excel (.xlsx) olarak kaydet")
        pdf = menu.addAction("PDF olarak kaydet")
        action = menu.exec(self.export_button.mapToGlobal(self.export_button.rect().bottomLeft()))
        if action == excel:
            self._export("xlsx")
        elif action == pdf:
            self._export("pdf")

    def _export(self, kind: str) -> None:
        """Write out exactly the rows currently on screen."""
        if not self._items:
            QMessageBox.information(
                self, "Dışa aktarma", "Listede dışa aktarılacak kayıt yok."
            )
            return

        completed = self.status_combo.currentData() == "COMPLETED"
        rows = rows_from_items(self._items, date.today(), completed=completed)
        caption = "Excel dosyası" if kind == "xlsx" else "PDF dosyası"
        suggested = str(Path.home() / default_name("hatirlatmalar", kind))
        path, _ = QFileDialog.getSaveFileName(
            self, f"{caption} olarak kaydet", suggested, f"{caption} (*.{kind})"
        )
        if not path:
            return
        if not path.lower().endswith(f".{kind}"):
            path = f"{path}.{kind}"

        title = f"Hatırlatmalar · {self.status_combo.currentText()}"
        try:
            writer = write_xlsx if kind == "xlsx" else write_pdf
            writer(rows, Path(path), title)
        except ExportError as exc:
            QMessageBox.warning(self, "Dışa aktarılamadı", str(exc))
            return
        except Exception as exc:
            logger.error("Dışa aktarma başarısız", exc_info=True)
            QMessageBox.warning(self, "Dışa aktarılamadı", str(exc))
            return
        self.notify("Dışa aktarıldı", f"{len(rows)} kayıt · {Path(path).name}")

    def create_reminder(self, *, prefill: dict | None = None) -> None:
        dialog = ReminderDialog(self.reminder_service, self.company_service, self, prefill=prefill)
        if dialog.exec() != ReminderDialog.DialogCode.Accepted:
            return
        try:
            self.reminder_service.create_manual(**dialog.get_data())
        except Exception as exc:
            QMessageBox.warning(self, "Hatırlatma kaydedilemedi", str(exc))
            return
        self.refresh()

    def _quick_add(self) -> None:
        dialog = QuickAddDialog(self.company_service, self)
        if dialog.exec() != QuickAddDialog.DialogCode.Accepted:
            return
        try:
            self.reminder_service.quick_add(**dialog.get_data())
        except Exception as exc:
            QMessageBox.warning(self, "Hatırlatma kaydedilemedi", str(exc))
            return
        self.refresh()

    def edit_selected(self) -> None:
        item = self._selected()
        if item is None:
            return
        if item.source_kind == "OFFICIAL":
            QMessageBox.information(
                self,
                "Resmî kayıt",
                "Bu tarih GİB/SGK resmî takviminden gelir ve elle değiştirilemez.\n\n"
                "Resmî bir süre uzatımı yayımlandığında uygulama tarihi kendisi günceller ve "
                "değişikliği “Resmî Güncellemeler” ekranında geçmişiyle birlikte gösterir.",
            )
            return
        record = self.reminder_service.get_manual(item.source_id)
        if record is None:
            QMessageBox.warning(self, "Bulunamadı", "Kayıt silinmiş olabilir.")
            self.refresh()
            return
        dialog = ReminderDialog(self.reminder_service, self.company_service, self, existing=record)
        if dialog.exec() != ReminderDialog.DialogCode.Accepted:
            return
        try:
            self.reminder_service.update_manual(record.id, **dialog.get_data())
        except Exception as exc:
            QMessageBox.warning(self, "Güncellenemedi", str(exc))
            return
        self.refresh()

    def delete_selected(self) -> None:
        item = self._selected()
        if item is None:
            return
        if item.source_kind == "OFFICIAL":
            QMessageBox.information(self, "Resmî kayıt", "Resmî yükümlülükler silinemez.")
            return
        confirm = QMessageBox.question(self, "Sil", f"“{item.title}” silinsin mi?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.reminder_service.delete_manual(item.source_id)
        except Exception as exc:
            QMessageBox.warning(self, "Silinemedi", str(exc))
            return
        self.refresh()

    def toggle_complete(self) -> None:
        item = self._selected()
        if item is None:
            return
        try:
            if self.reminder_service.is_completed(item.source_kind, item.source_id, item.company_id):
                self.reminder_service.undo_complete(item.source_kind, item.source_id, item.company_id)
            else:
                self.reminder_service.complete(
                    source_kind=item.source_kind, source_id=item.source_id, company_id=item.company_id
                )
        except Exception as exc:
            QMessageBox.warning(self, "İşlem tamamlanamadı", str(exc))
            return
        self.refresh()

    def _context_menu(self, position) -> None:
        item = self._selected()
        if item is None:
            return
        menu = QMenu(self)
        official = item.source_kind == "OFFICIAL"
        done = menu.addAction(icons.icon("check"), "Tamamlandı / geri al")
        edit = menu.addAction(icons.icon("pencil"), "Düzenle")
        edit.setEnabled(not official)
        menu.addSeparator()
        menu.addAction(icons.icon("list"), "Metin olarak kopyala").triggered.connect(
            self.copy_selected
        )
        remove = menu.addAction(icons.icon("trash"), "Sil")
        remove.setEnabled(not official)

        action = menu.exec(self.table.viewport().mapToGlobal(position))
        if action == done:
            self.toggle_complete()
        elif action == edit:
            self.edit_selected()
        elif action == remove:
            self.delete_selected()
