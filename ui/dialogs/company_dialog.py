from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLineEdit, QTextEdit, QWidget

from ui.dialogs.base import FormDialog


class CompanyDialog(FormDialog):
    def __init__(self, parent: QWidget | None = None, existing=None) -> None:
        super().__init__(
            "Şirketi Düzenle" if existing else "Yeni Şirket",
            "Değişiklikleri Kaydet" if existing else "Şirketi Kaydet",
            parent,
            width=520,
        )
        self.existing = existing
        self._build()
        if existing is not None:
            self._load(existing)

    def _build(self) -> None:
        section = self.add_section("Şirket Bilgileri")

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Örn: ABC Ticaret Ltd. Şti.")
        section.add_row("Unvan", self.name_edit, required=True)

        self.tax_edit = QLineEdit()
        self.tax_edit.setPlaceholderText("10 haneli vergi kimlik numarası")
        self.tax_edit.setMaxLength(11)
        section.add_row(
            "Vergi No",
            self.tax_edit,
            hint="İsteğe bağlı. Girilirse başka bir şirkette tekrar kullanılamaz.",
        )

        self.active_check = QCheckBox("Aktif olarak takip et")
        self.active_check.setChecked(True)
        section.add_row(
            "Durum",
            self.active_check,
            hint="Pasif şirketler için resmî tarihler ve bildirimler üretilmez.",
        )

        notes = self.add_section("Notlar")
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("İsteğe bağlı not")
        self.notes_edit.setFixedHeight(88)
        notes.add_full(self.notes_edit)

        self.finish_body()

    def _load(self, record) -> None:
        self.name_edit.setText(record.name)
        self.tax_edit.setText(record.tax_number or "")
        self.notes_edit.setPlainText(record.notes or "")
        self.active_check.setChecked(bool(record.is_active))

    def validate(self) -> bool:
        if not self.name_edit.text().strip():
            self.mark_invalid(self.name_edit, "Şirket unvanı zorunludur.")
            return False
        tax = self.tax_edit.text().strip()
        if tax and not tax.isdigit():
            self.mark_invalid(self.tax_edit, "Vergi numarası yalnızca rakamlardan oluşmalıdır.")
            return False
        if tax and len(tax) not in (10, 11):
            self.mark_invalid(self.tax_edit, "Vergi numarası 10 hane (T.C. kimlik için 11) olmalıdır.")
            return False
        return True

    def get_data(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "tax_number": self.tax_edit.text().strip() or None,
            "notes": self.notes_edit.toPlainText().strip() or None,
            "is_active": self.active_check.isChecked(),
        }
