from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from services.company_service import CompanyService
from services.date_phrases import describe
from services.reminder_service import DEFAULT_NOTIFICATION_OFFSETS, ReminderService
from ui.dialogs.base import FormDialog
from ui.theme import tokens
from ui.widgets import button, icon_button, label, style_calendar

logger = logging.getLogger(__name__)

CATEGORY_CHOICES: tuple[tuple[str, str], ...] = (
    ("GENERAL", "Genel"),
    ("VEHICLE_INSPECTION", "Araç Muayenesi"),
    ("TRAFFIC_INSURANCE", "Trafik Sigortası"),
    ("KASKO", "Kasko"),
    ("RENT", "Kira"),
    ("CONTRACT", "Sözleşme"),
    ("LICENSE", "Ruhsat"),
    ("SUBSCRIPTION", "Abonelik"),
    ("SPECIAL_PAYMENT", "Özel Ödeme"),
    ("PERSONNEL_DOC", "Personel Belgesi"),
    ("CUSTOM_REMINDER", "Serbest Hatırlatma"),
)

# Categories that describe a specific vehicle; for these the vehicle picker is
# the point of the reminder, so it is shown expanded and hinted as expected.
VEHICLE_CATEGORIES = {"VEHICLE_INSPECTION", "TRAFFIC_INSURANCE", "KASKO"}

RECURRENCE_CHOICES: tuple[tuple[str, str], ...] = (
    ("NONE", "Tekrar yok"),
    ("MONTHLY", "Her ay"),
    ("QUARTERLY", "3 ayda bir"),
    ("SEMIANNUAL", "6 ayda bir"),
    ("YEARLY", "Yılda bir"),
    ("CUSTOM", "Özel aralık"),
)

CUSTOM_UNITS = (("interval_months", "ay"), ("interval_days", "gün"))
MAX_OFFSET_DAYS = 365


class ReminderDialog(FormDialog):
    """Create or edit a manual reminder.

    Vehicle-linked reminders (inspection, insurance, kasko) are first-class: the
    picker lists the selected company's vehicles and the stored `vehicle_id`
    round-trips, so a notification can name the plate.
    """

    def __init__(
        self,
        reminder_service: ReminderService,
        company_service: CompanyService,
        parent: QWidget | None = None,
        existing=None,
        prefill: dict | None = None,
    ) -> None:
        super().__init__(
            "Hatırlatmayı Düzenle" if existing else "Yeni Hatırlatma",
            "Değişiklikleri Kaydet" if existing else "Hatırlatmayı Kaydet",
            parent,
            width=600,
        )
        self.reminder_service = reminder_service
        self.company_service = company_service
        self.existing = existing
        self._vehicle_available = False
        self._build()
        if existing is not None:
            self._load(existing)
        elif prefill:
            self._apply_prefill(prefill)
        self._sync_visibility()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        basics = self.add_section(
            "Temel Bilgiler",
            "Vergi ve SGK tarihleri buraya girilmez; onlar GİB/SGK takviminden otomatik gelir.",
        )

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Örn: Araç muayenesi")
        basics.add_row("Başlık", self.title_edit, required=True)

        self.category_combo = QComboBox()
        for code, text in CATEGORY_CHOICES:
            self.category_combo.addItem(text, code)
        basics.add_row("Kategori", self.category_combo)

        self.company_combo = QComboBox()
        self.company_combo.addItem("Şirketsiz (genel)", None)
        for company in self._companies():
            self.company_combo.addItem(company.name, company.id)
        basics.add_row("Şirket", self.company_combo)

        self.vehicle_combo = QComboBox()
        self.vehicle_row = basics.add_row(
            "Araç",
            self.vehicle_combo,
            hint="Araç seçildiğinde bildirimlerde plaka da gösterilir.",
        )

        timing = self.add_section("Tarih")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        style_calendar(self.date_edit.calendarWidget())
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setDate(QDate.currentDate().addDays(7))
        timing.add_row("Son tarih", self.date_edit, required=True)

        # Typing beats four clicks in a calendar popup, and the office types
        # dates all day. The picker stays; this only fills it in.
        quick_holder = QWidget()
        quick_layout = QVBoxLayout(quick_holder)
        quick_layout.setContentsMargins(0, 0, 0, 0)
        quick_layout.setSpacing(2)
        self.quick_date_edit = QLineEdit()
        self.quick_date_edit.setPlaceholderText(
            "yarın · 3 gün sonra · ayın son günü · 15 ekim · gelecek salı"
        )
        self.quick_date_edit.setClearButtonEnabled(True)
        quick_layout.addWidget(self.quick_date_edit)
        self.quick_date_hint = label("", "SubtleHint")
        quick_layout.addWidget(self.quick_date_hint)
        timing.add_row("Hızlı tarih", quick_holder)
        self.quick_date_edit.textChanged.connect(self._apply_quick_date)

        time_holder = QWidget()
        time_layout = QHBoxLayout(time_holder)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(8)
        self.time_check = QCheckBox("Saat belirt")
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setTime(QTime(9, 0))
        self.time_edit.setEnabled(False)
        self.time_check.toggled.connect(self.time_edit.setEnabled)
        time_layout.addWidget(self.time_check)
        time_layout.addWidget(self.time_edit)
        time_layout.addStretch()
        timing.add_row("Saat", time_holder)

        repeat = self.add_section("Tekrar")
        self.recurrence_combo = QComboBox()
        for code, text in RECURRENCE_CHOICES:
            self.recurrence_combo.addItem(text, code)
        repeat.add_row("Tekrar", self.recurrence_combo)

        custom_holder = QWidget()
        custom_layout = QHBoxLayout(custom_holder)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(8)
        self.custom_spin = QSpinBox()
        self.custom_spin.setRange(1, 60)
        self.custom_spin.setValue(2)
        self.custom_unit = QComboBox()
        for code, text in CUSTOM_UNITS:
            self.custom_unit.addItem(text, code)
        custom_layout.addWidget(label("Her", "FieldLabel"))
        custom_layout.addWidget(self.custom_spin)
        custom_layout.addWidget(self.custom_unit)
        custom_layout.addWidget(label("bir", "FieldLabel"))
        custom_layout.addStretch()
        self.custom_row = repeat.add_row("Aralık", custom_holder)
        self.repeat_hint = label(
            "Tamamlandığında bir sonraki tarih otomatik oluşturulur; yıllar öncesinden "
            "yüzlerce kayıt üretilmez.",
            "Caption",
            wrap=True,
        )
        repeat.add_full(self.repeat_hint)

        notify = self.add_section("Bildirim")
        self.offsets_edit = QLineEdit()
        self.offsets_edit.setPlaceholderText("14, 7, 3, 1, 0")
        notify.add_row(
            "Kaç gün önce",
            self.offsets_edit,
            hint=f"Virgülle ayrılmış gün sayıları, 0–{MAX_OFFSET_DAYS}. Boş bırakılırsa varsayılan "
            f"({', '.join(str(o) for o in DEFAULT_NOTIFICATION_OFFSETS)}) kullanılır.",
        )
        self.notify_time_check = QCheckBox("Belirli bir saatte bildir")
        self.notify_time_edit = QTimeEdit()
        self.notify_time_edit.setDisplayFormat("HH:mm")
        self.notify_time_edit.setTime(QTime(9, 0))
        self.notify_time_edit.setEnabled(False)
        self.notify_time_check.toggled.connect(self.notify_time_edit.setEnabled)
        notify_holder = QWidget()
        notify_layout = QHBoxLayout(notify_holder)
        notify_layout.setContentsMargins(0, 0, 0, 0)
        notify_layout.setSpacing(8)
        notify_layout.addWidget(self.notify_time_check)
        notify_layout.addWidget(self.notify_time_edit)
        notify_layout.addStretch()
        notify.add_row("Bildirim saati", notify_holder)

        notes = self.add_section("Notlar")
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("İsteğe bağlı not")
        self.notes_edit.setFixedHeight(84)
        notes.add_full(self.notes_edit)

        self._build_attachments()

        self.finish_body()

        self.company_combo.currentIndexChanged.connect(self._reload_vehicles)
        self.category_combo.currentIndexChanged.connect(self._sync_visibility)
        self.recurrence_combo.currentIndexChanged.connect(self._sync_visibility)
        self._reload_vehicles()

    def _apply_quick_date(self, text: str) -> None:
        """Fill the date picker from a typed phrase, and say what was read.

        Nothing is written when the phrase is not understood: silently landing
        on a date the user did not ask for is worse than leaving it alone.
        """
        from services.date_phrases import describe, parse_date_phrase

        typed = text.strip()
        if not typed:
            self.quick_date_hint.setText("")
            return

        parsed = parse_date_phrase(typed)
        if parsed is None:
            self.quick_date_hint.setText("Anlaşılamadı — tarihi elle seçebilirsiniz.")
            return

        self.quick_date_hint.setText(f"→ {describe(parsed)}")
        self.date_edit.setDate(QDate(parsed.year, parsed.month, parsed.day))

    # --------------------------------------------------------------- attachments
    def _build_attachments(self) -> None:
        """Files can only hang off a record that exists.

        A new reminder has no id yet, so instead of silently doing nothing the
        section says when attaching becomes possible.
        """
        section = self.add_section("Ekler")
        self.attachments_box = QVBoxLayout()
        self.attachments_box.setSpacing(tokens().space_xs)
        holder = QWidget()
        holder.setLayout(self.attachments_box)
        section.add_full(holder)

        if self.existing is None:
            self.attachments_box.addWidget(
                label(
                    "Dosya eklemek için önce hatırlatmayı kaydedin, "
                    "sonra düzenleyerek ekleyin.",
                    "SubtleHint",
                    wrap=True,
                )
            )
            return

        self.attach_button = button("Dosya Ekle", "subtle", "plus")
        self.attach_button.clicked.connect(self._pick_attachment)
        section.add_full(self.attach_button)
        self._reload_attachments()

    def _attachment_service(self):
        from services.attachment_service import AttachmentService

        return AttachmentService(self.reminder_service.database)

    def _reload_attachments(self) -> None:
        while self.attachments_box.count():
            entry = self.attachments_box.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        try:
            attachments = self._attachment_service().list_for("MANUAL", self.existing.id)
        except Exception:
            logger.warning("Ekler okunamadı", exc_info=True)
            attachments = []

        if not attachments:
            self.attachments_box.addWidget(
                label("Henüz dosya eklenmedi.", "SubtleHint", wrap=True)
            )
            return

        from services.attachment_service import human_size

        for attachment in attachments:
            row = QHBoxLayout()
            row.setSpacing(tokens().space_sm)
            name = label(attachment.display_name, "Muted")
            name.setToolTip(str(attachment.path))
            row.addWidget(name, 1)
            detail = "eksik dosya" if not attachment.exists else human_size(attachment.size)
            row.addWidget(label(detail, "Caption"))

            open_button = icon_button("external", "Aç", "ghost")
            open_button.setEnabled(attachment.exists)
            open_button.clicked.connect(
                lambda _c=False, a=attachment: self._open_attachment(a)
            )
            row.addWidget(open_button)

            remove_button = icon_button("trash", "Kaldır", "ghost")
            remove_button.clicked.connect(
                lambda _c=False, a=attachment: self._remove_attachment(a)
            )
            row.addWidget(remove_button)

            holder = QWidget()
            holder.setLayout(row)
            self.attachments_box.addWidget(holder)

    def _pick_attachment(self) -> None:
        from services.attachment_service import ALLOWED_SUFFIXES, AttachmentError

        patterns = " ".join(f"*{suffix}" for suffix in sorted(ALLOWED_SUFFIXES))
        path, _ = QFileDialog.getOpenFileName(
            self, "Eklenecek dosya", "", f"Belge ve görseller ({patterns})"
        )
        if not path:
            return
        try:
            self._attachment_service().attach("MANUAL", self.existing.id, Path(path))
        except AttachmentError as exc:
            QMessageBox.warning(self, "Dosya eklenemedi", str(exc))
            return
        except Exception as exc:
            logger.error("Ek eklenemedi", exc_info=True)
            QMessageBox.warning(self, "Dosya eklenemedi", str(exc))
            return
        self._reload_attachments()

    def _open_attachment(self, attachment) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        if not attachment.exists:
            QMessageBox.warning(
                self, "Dosya bulunamadı", "Ek dosyası veri klasöründen silinmiş görünüyor."
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(attachment.path)))

    def _remove_attachment(self, attachment) -> None:
        confirm = QMessageBox.question(
            self,
            "Eki kaldır",
            f"“{attachment.display_name}” bu hatırlatmadan kaldırılacak ve "
            "kopyası silinecek. Devam edilsin mi?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._attachment_service().remove(attachment.id)
        self._reload_attachments()

    def _companies(self) -> list:
        try:
            return self.company_service.list_active()
        except Exception:
            return []

    # ------------------------------------------------------------------ dynamic state
    def _reload_vehicles(self) -> None:
        company_id = self.company_combo.currentData()
        keep = self.vehicle_combo.currentData()
        self.vehicle_combo.blockSignals(True)
        self.vehicle_combo.clear()
        self.vehicle_combo.addItem("Araç seçilmedi", None)
        vehicles = []
        if company_id is not None:
            try:
                vehicles = self.company_service.list_vehicles(company_id=company_id, only_active=True)
            except Exception:
                vehicles = []
        for vehicle in vehicles:
            descriptor = " ".join(part for part in [vehicle.make, vehicle.model] if part)
            text = f"{vehicle.plate} — {descriptor}" if descriptor else vehicle.plate
            self.vehicle_combo.addItem(text, vehicle.id)
        index = self.vehicle_combo.findData(keep)
        if index >= 0:
            self.vehicle_combo.setCurrentIndex(index)
        self.vehicle_combo.blockSignals(False)

        has_company = company_id is not None
        self._vehicle_available = has_company and bool(vehicles)
        self.vehicle_combo.setEnabled(self._vehicle_available)
        if not has_company:
            self.vehicle_combo.setToolTip("Önce bir şirket seçin.")
        elif not vehicles:
            self.vehicle_combo.setToolTip("Bu şirkete kayıtlı aktif araç yok. Araçlar ekranından ekleyebilirsiniz.")
        else:
            self.vehicle_combo.setToolTip("")
        self._sync_visibility()

    def _sync_visibility(self) -> None:
        is_custom = self.recurrence_combo.currentData() == "CUSTOM"
        self.custom_row.setVisible(is_custom)
        self.repeat_hint.setVisible(self.recurrence_combo.currentData() != "NONE")

        wants_vehicle = self.category_combo.currentData() in VEHICLE_CATEGORIES
        self.vehicle_row.setVisible(wants_vehicle or self.vehicle_combo.currentData() is not None)
        self.vehicle_row.setEnabled(self._vehicle_available)

    # ------------------------------------------------------------------ load
    def _apply_prefill(self, prefill: dict) -> None:
        if "category" in prefill:
            index = self.category_combo.findData(prefill["category"])
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
        if "company_id" in prefill:
            index = self.company_combo.findData(prefill["company_id"])
            if index >= 0:
                self.company_combo.setCurrentIndex(index)
                self._reload_vehicles()
        if "vehicle_id" in prefill:
            index = self.vehicle_combo.findData(prefill["vehicle_id"])
            if index >= 0:
                self.vehicle_combo.setCurrentIndex(index)
        if prefill.get("title"):
            self.title_edit.setText(prefill["title"])
        if prefill.get("notes"):
            self.notes_edit.setPlainText(prefill["notes"])
        due = prefill.get("due_date")
        if due is not None:
            self.date_edit.setDate(QDate(due.year, due.month, due.day))
            # Show which words the date came from, so a wrong read is visible.
            phrase = prefill.get("date_phrase")
            if phrase:
                self.quick_date_hint.setText(f"“{phrase}” → {describe(due)}")

    def _load(self, record) -> None:
        self.title_edit.setText(record.title)

        index = self.category_combo.findData(record.category)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)

        index = self.company_combo.findData(record.company_id)
        self.company_combo.setCurrentIndex(index if index >= 0 else 0)
        self._reload_vehicles()

        index = self.vehicle_combo.findData(record.vehicle_id)
        if index >= 0:
            self.vehicle_combo.setCurrentIndex(index)

        try:
            due = date.fromisoformat(record.due_date)
            self.date_edit.setDate(QDate(due.year, due.month, due.day))
        except ValueError:
            pass

        if record.due_time:
            self.time_check.setChecked(True)
            hour, minute = _parse_time(record.due_time)
            self.time_edit.setTime(QTime(hour, minute))

        index = self.recurrence_combo.findData(record.recurrence_kind)
        if index >= 0:
            self.recurrence_combo.setCurrentIndex(index)
        payload = _load_json(record.recurrence_json)
        if "interval_days" in payload:
            self.custom_unit.setCurrentIndex(self.custom_unit.findData("interval_days"))
            self.custom_spin.setValue(max(1, int(payload["interval_days"])))
        elif "interval_months" in payload:
            self.custom_unit.setCurrentIndex(self.custom_unit.findData("interval_months"))
            self.custom_spin.setValue(max(1, int(payload["interval_months"])))
        elif record.recurrence_interval:
            self.custom_spin.setValue(record.recurrence_interval)

        self.notes_edit.setPlainText(record.notes or "")

        rules = self.reminder_service.notification_rules.list_for_source("MANUAL", record.id)
        if rules:
            self.offsets_edit.setText(", ".join(str(rule.offset_days) for rule in rules))
            notify_at = next((rule.notify_time for rule in rules if rule.notify_time), None)
            if notify_at:
                self.notify_time_check.setChecked(True)
                hour, minute = _parse_time(notify_at)
                self.notify_time_edit.setTime(QTime(hour, minute))

    # ------------------------------------------------------------------ validate / read
    def validate(self) -> bool:
        if not self.title_edit.text().strip():
            self.mark_invalid(self.title_edit, "Başlık zorunludur.")
            return False
        if self._parse_offsets() is False:
            self.mark_invalid(
                self.offsets_edit,
                f"Hatırlatma günleri virgülle ayrılmış 0–{MAX_OFFSET_DAYS} arası sayılar olmalıdır.",
            )
            return False
        return True

    def _parse_offsets(self):
        raw = self.offsets_edit.text().strip()
        if not raw:
            return None
        values: list[int] = []
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                value = int(part)
            except ValueError:
                return False
            if not 0 <= value <= MAX_OFFSET_DAYS:
                return False
            values.append(value)
        if not values:
            return None
        return sorted(set(values), reverse=True)

    def get_data(self) -> dict:
        qdate = self.date_edit.date()
        due = date(qdate.year(), qdate.month(), qdate.day())

        due_time = None
        if self.time_check.isChecked():
            value = self.time_edit.time()
            due_time = f"{value.hour():02d}:{value.minute():02d}"

        notify_time = None
        if self.notify_time_check.isChecked():
            value = self.notify_time_edit.time()
            notify_time = f"{value.hour():02d}:{value.minute():02d}"

        recurrence = self.recurrence_combo.currentData()
        interval = None
        recurrence_json = None
        if recurrence == "CUSTOM":
            interval = int(self.custom_spin.value())
            recurrence_json = json.dumps({self.custom_unit.currentData(): interval}, ensure_ascii=False)
        elif recurrence != "NONE":
            interval = {"MONTHLY": 1, "QUARTERLY": 3, "SEMIANNUAL": 6, "YEARLY": 12}[recurrence]

        company_id = self.company_combo.currentData()
        vehicle_id = self.vehicle_combo.currentData() if company_id is not None else None

        return {
            "title": self.title_edit.text().strip(),
            "due_date": due,
            "company_id": company_id,
            "vehicle_id": vehicle_id,
            "category": self.category_combo.currentData(),
            "due_time": due_time,
            "notes": self.notes_edit.toPlainText().strip() or None,
            "recurrence_kind": recurrence,
            "recurrence_interval": interval,
            "recurrence_json": recurrence_json,
            "notification_offsets": self._parse_offsets() or None,
            "notify_time": notify_time,
        }


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hour, minute = value.split(":")[:2]
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        return 9, 0


def _load_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
