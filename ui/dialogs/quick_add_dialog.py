from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QComboBox, QDateEdit, QLineEdit, QWidget

from services.company_service import CompanyService
from ui.dialogs.base import FormDialog
from ui.widgets import style_calendar

logger = logging.getLogger("office_reminder.ui")


class QuickAddDialog(FormDialog):
    """Three fields only — for jotting something down without breaking flow."""

    def __init__(self, company_service: CompanyService, parent: QWidget | None = None) -> None:
        super().__init__("Hızlı Hatırlatma", "Ekle", parent, width=460)
        self.company_service = company_service
        self._build()

    def _build(self) -> None:
        section = self.add_section("Hızlı Ekle", "Ayrıntıları sonra düzenleyebilirsiniz.")

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Ne hatırlatılsın?")
        section.add_row("Başlık", self.title_edit, required=True)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        style_calendar(self.date_edit.calendarWidget())
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setDate(QDate.currentDate().addDays(7))
        section.add_row("Son tarih", self.date_edit, required=True)

        self.company_combo = QComboBox()
        self.company_combo.addItem("Şirketsiz (genel)", None)
        try:
            for company in self.company_service.list_active():
                self.company_combo.addItem(company.name, company.id)
        except Exception:
            # The dialog stays usable without a company; the reminder is general.
            logger.warning("Company list unavailable for quick add", exc_info=True)
        section.add_row("Şirket", self.company_combo)

        self.finish_body()
        self.title_edit.setFocus()

    def validate(self) -> bool:
        if not self.title_edit.text().strip():
            self.mark_invalid(self.title_edit, "Başlık zorunludur.")
            return False
        return True

    def get_data(self) -> dict:
        value = self.date_edit.date()
        return {
            "title": self.title_edit.text().strip(),
            "due_date": date(value.year(), value.month(), value.day()),
            "company_id": self.company_combo.currentData(),
        }
