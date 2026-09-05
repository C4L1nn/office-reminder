from __future__ import annotations

import re

from PySide6.QtWidgets import QComboBox, QLineEdit, QSpinBox, QTextEdit, QWidget

from services.company_service import CompanyService
from ui.dialogs.base import FormDialog

# 34 ABC 123 / 34 AB 1234 / 06 A 1234 — spacing is normalised on save.
PLATE_PATTERN = re.compile(r"^\d{2}\s?[A-ZÇĞİÖŞÜ]{1,3}\s?\d{2,5}$")


class VehicleDialog(FormDialog):
    def __init__(
        self,
        company_service: CompanyService,
        parent: QWidget | None = None,
        existing=None,
        company_id: int | None = None,
    ) -> None:
        super().__init__(
            "Aracı Düzenle" if existing else "Yeni Araç",
            "Değişiklikleri Kaydet" if existing else "Aracı Kaydet",
            parent,
            width=520,
        )
        self.company_service = company_service
        self.existing = existing
        self._build()
        if existing is not None:
            self._load(existing)
        elif company_id is not None:
            index = self.company_combo.findData(company_id)
            if index >= 0:
                self.company_combo.setCurrentIndex(index)

    def _build(self) -> None:
        section = self.add_section(
            "Araç Bilgileri",
            "Araç bir şirkete aittir; muayene, trafik sigortası ve kasko hatırlatmaları bu araçla "
            "ilişkilendirilebilir.",
        )

        self.company_combo = QComboBox()
        try:
            companies = self.company_service.list_active()
        except Exception:
            companies = []
        for company in companies:
            self.company_combo.addItem(company.name, company.id)
        section.add_row("Şirket", self.company_combo, required=True)

        self.plate_edit = QLineEdit()
        self.plate_edit.setPlaceholderText("34 ABC 123")
        section.add_row("Plaka", self.plate_edit, required=True)

        self.make_edit = QLineEdit()
        self.make_edit.setPlaceholderText("Örn: Ford")
        section.add_row("Marka", self.make_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("Örn: Transit")
        section.add_row("Model", self.model_edit)

        self.year_spin = QSpinBox()
        self.year_spin.setRange(1949, 2100)
        self.year_spin.setSpecialValueText("Belirtilmedi")
        self.year_spin.setValue(1949)
        section.add_row("Model yılı", self.year_spin)

        notes = self.add_section("Notlar")
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("İsteğe bağlı not")
        self.notes_edit.setFixedHeight(80)
        notes.add_full(self.notes_edit)

        self.finish_body()

    def _load(self, record) -> None:
        index = self.company_combo.findData(record.company_id)
        if index >= 0:
            self.company_combo.setCurrentIndex(index)
        self.plate_edit.setText(record.plate)
        self.make_edit.setText(record.make or "")
        self.model_edit.setText(record.model or "")
        self.year_spin.setValue(record.model_year or 1949)
        self.notes_edit.setPlainText(record.notes or "")

    def validate(self) -> bool:
        if self.company_combo.currentData() is None:
            self.mark_invalid(
                self.company_combo,
                "Önce bir şirket ekleyin; araçlar bir şirkete bağlı tutulur.",
            )
            return False
        plate = self._normalised_plate()
        if not plate:
            self.mark_invalid(self.plate_edit, "Plaka zorunludur.")
            return False
        if not PLATE_PATTERN.match(plate):
            self.mark_invalid(self.plate_edit, "Plakayı “34 ABC 123” biçiminde girin.")
            return False
        return True

    def _normalised_plate(self) -> str:
        raw = self.plate_edit.text().strip().upper().replace("I", "İ")
        collapsed = re.sub(r"\s+", " ", raw)
        match = re.match(r"^(\d{2})\s?([A-ZÇĞİÖŞÜ]{1,3})\s?(\d{2,5})$", collapsed)
        return f"{match.group(1)} {match.group(2)} {match.group(3)}" if match else collapsed

    def get_data(self) -> dict:
        year = self.year_spin.value()
        return {
            "company_id": self.company_combo.currentData(),
            "plate": self._normalised_plate(),
            "make": self.make_edit.text().strip() or None,
            "model": self.model_edit.text().strip() or None,
            "model_year": year if year > 1949 else None,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
