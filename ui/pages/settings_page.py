from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.paths import get_backups_dir, get_database_path, get_logs_dir, get_runtime_root
from services.backup_service import BackupService
from services.settings_service import SettingsService
from services.startup_service import StartupService, StartupUnavailable
from ui.shell import Page
from ui.theme import tokens
from ui.widgets import Card, button, label, separator


class SettingsPage(Page):
    """Sectioned settings: general, notifications, startup, backup, system."""

    settings_changed = Signal()
    open_official = Signal()

    def __init__(
        self,
        settings_service: SettingsService,
        startup_service: StartupService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Ayarlar",
            "Uygulamanın nasıl çalışacağını ve verilerin nerede tutulduğunu yönetin.",
            parent,
            scrollable=True,
        )
        self.settings = settings_service
        self.startup = startup_service or StartupService()
        self._loading = False
        self._build()

    # ------------------------------------------------------------------ layout
    #: A settings form is text; stretching a checkbox row to 1100px makes it
    #: unreadable. Everything sits inside a fixed measure.
    MEASURE = 780

    def _build(self) -> None:
        column = QWidget()
        column.setObjectName("Measure")
        column.setMaximumWidth(self.MEASURE)
        inner = QVBoxLayout(column)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(tokens().space)
        inner.addWidget(self._general_card())
        inner.addWidget(self._backup_card())
        inner.addWidget(self._shortcuts_card())
        inner.addWidget(self._system_card())
        inner.addStretch()

        holder = QHBoxLayout()
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(column)
        holder.addStretch()
        self.content_layout.addLayout(holder)
        self.content_layout.addStretch()

    def _toggle_row(self, card: Card, text: str, hint: str) -> QCheckBox:
        check = QCheckBox(text)
        card.add(check)
        card.add(_indented(label(hint, "SubtleHint", wrap=True)))
        return check

    def _general_card(self) -> Card:
        card = Card("Genel")

        self.notifications_check = self._toggle_row(
            card,
            "Windows bildirimleri gönder",
            "Kapatıldığında hatırlatmalar ekranlarda görünmeye devam eder, bildirim gönderilmez.",
        )
        self.tray_check = self._toggle_row(
            card,
            "Pencere kapatılınca arka planda çalışmaya devam et",
            "Uygulama sistem tepsisinde kalır. Tamamen kapatmak için tepsi menüsünden Çıkış'ı kullanın.",
        )
        self.mini_counter_check = self._toggle_row(
            card,
            "Mini sayaç her zaman üstte dursun",
            "En acil işi küçük bir kartta gösterir. Tıklayınca ana pencere açılır.",
        )
        self.update_check = self._toggle_row(
            card,
            "Yeni sürümleri kendisi denetlesin",
            "Günde bir bakar ve yalnızca haber verir. Kurulum her zaman sizin onayınızla başlar.",
        )
        self.autostart_check = self._toggle_row(
            card,
            "Windows açıldığında başlat",
            "Yalnızca bu kullanıcı için ayarlanır, yönetici izni gerekmez.",
        )
        self.autostart_background_check = self._toggle_row(
            card,
            "Açılışta pencereyi gösterme (yalnızca tepside başlat)",
            "Windows ile başlat seçili olduğunda geçerlidir.",
        )
        # Says why the box is greyed out or unticked; hidden otherwise.
        self.autostart_note = label("", "SubtleHint", wrap=True)
        self._autostart_note_row = _indented(self.autostart_note)
        self._autostart_note_row.setHidden(True)
        card.add(self._autostart_note_row)

        card.add(separator())
        theme_row = QHBoxLayout()
        theme_row.setSpacing(tokens().space_sm)
        theme_row.addWidget(label("Görünüm", "FieldLabel"))
        self.theme_combo = QComboBox()
        self.theme_combo.setFixedWidth(190)
        for value, caption in (
            ("system", "Windows ile aynı"),
            ("light", "Açık tema"),
            ("dark", "Koyu tema"),
        ):
            self.theme_combo.addItem(caption, value)
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch()
        card.add_layout(theme_row)
        card.add(
            _indented(
                label(
                    "Değişiklik uygulama yeniden başlatıldığında geçerli olur.",
                    "SubtleHint",
                    wrap=True,
                )
            )
        )

        card.add(separator())
        interval_row = QHBoxLayout()
        interval_row.setSpacing(tokens().space_sm)
        interval_row.addWidget(label("Hatırlatma kontrol aralığı", "FieldLabel"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 720)
        self.interval_spin.setSuffix(" dakika")
        self.interval_spin.setFixedWidth(150)
        interval_row.addWidget(self.interval_spin)
        interval_row.addStretch()
        card.add_layout(interval_row)

        self.notifications_check.toggled.connect(self._save_general)
        self.tray_check.toggled.connect(self._save_general)
        self.mini_counter_check.toggled.connect(self._save_general)
        self.update_check.toggled.connect(self._save_general)
        self.autostart_check.toggled.connect(self._save_startup)
        self.autostart_background_check.toggled.connect(self._save_startup)
        self.interval_spin.valueChanged.connect(self._save_general)
        self.theme_combo.currentIndexChanged.connect(self._save_theme)
        return card

    def _backup_card(self) -> Card:
        card = Card("Yedekleme")
        self.backup_status = label("Son yedek: —", "Muted")
        card.add(self.backup_status)
        card.add(
            label(
                "Veritabanı günde bir kez otomatik yedeklenir ve her yedek açılabilirlik için "
                "doğrulanır. Eski yedekler saklama süresine göre silinir.",
                "SubtleHint",
                wrap=True,
            )
        )

        row = QHBoxLayout()
        row.setSpacing(tokens().space_sm)
        backup_now = button("Şimdi Yedekle", "subtle", "shield")
        backup_now.clicked.connect(self._backup_now)
        open_folder = button("Yedek Klasörünü Aç", "ghost", "folder")
        open_folder.clicked.connect(lambda: self._open(get_backups_dir()))
        row.addWidget(backup_now)
        row.addWidget(open_folder)
        row.addStretch()
        row.addWidget(label("Saklama", "FieldLabel"))
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 365)
        self.retention_spin.setSuffix(" yedek")
        self.retention_spin.setFixedWidth(130)
        self.retention_spin.valueChanged.connect(self._save_general)
        row.addWidget(self.retention_spin)
        card.add_layout(row)
        return card

    def _shortcuts_card(self) -> Card:
        """A shortcut nobody can discover is a shortcut nobody uses."""
        from ui.main_window import MainWindow

        card = Card("Klavye Kısayolları")
        rows = list(MainWindow.SHORTCUTS) + [
            ("Ctrl+1 … Ctrl+8", "", "Kenar çubuğundaki ekranlara geç"),
        ]
        for keys, _handler, description in rows:
            line = QHBoxLayout()
            line.setSpacing(tokens().space_sm)
            key_label = label(keys, "Mono")
            key_label.setFixedWidth(140)
            line.addWidget(key_label)
            line.addWidget(label(description, "Muted"), 1)
            holder = QWidget()
            holder.setLayout(line)
            card.add(holder)
        card.tighten()
        return card

    def _system_card(self) -> Card:
        card = Card("Sistem")
        self.paths_box = QVBoxLayout()
        self.paths_box.setSpacing(3)
        card.add_layout(self.paths_box)

        for caption, path in (
            ("Veri klasörü", get_runtime_root()),
            ("Veritabanı", get_database_path()),
            ("Günlükler", get_logs_dir()),
        ):
            row = QHBoxLayout()
            row.setSpacing(tokens().space_sm)
            name = label(caption, "FieldLabel")
            name.setFixedWidth(110)
            row.addWidget(name)
            value = label(str(path), "Mono", wrap=True)
            row.addWidget(value, 1)
            holder = QWidget()
            holder.setLayout(row)
            self.paths_box.addWidget(holder)

        row = QHBoxLayout()
        row.setSpacing(tokens().space_sm)
        data_button = button("Veri Klasörünü Aç", "subtle", "folder")
        data_button.clicked.connect(lambda: self._open(get_runtime_root()))
        log_button = button("Günlük Klasörünü Aç", "ghost", "folder")
        log_button.clicked.connect(lambda: self._open(get_logs_dir()))
        official_button = button("Resmî Kaynaklar", "ghost", "cloud")
        official_button.clicked.connect(self.open_official.emit)
        row.addWidget(data_button)
        row.addWidget(log_button)
        row.addWidget(official_button)
        row.addStretch()
        self.version_label = label("", "Caption")
        row.addWidget(self.version_label)
        card.add_layout(row)
        return card

    # ------------------------------------------------------------------ state
    def refresh(self) -> None:
        self._loading = True
        try:
            from services.settings_service import MINI_COUNTER_ENABLED, UPDATE_AUTO_CHECK

            values = self.settings.load()
            self.notifications_check.setChecked(values.notifications_enabled)
            self.tray_check.setChecked(values.minimize_to_tray)
            self.mini_counter_check.setChecked(self.settings.get_bool(MINI_COUNTER_ENABLED))
            self.update_check.setChecked(self.settings.get_bool(UPDATE_AUTO_CHECK))
            self.interval_spin.setValue(values.check_interval_minutes)
            self.retention_spin.setValue(values.backup_retention_days)
            self.autostart_background_check.setChecked(values.start_in_background)
            try:
                available = self.startup.available()
                enabled = self.startup.is_enabled()
                elsewhere = self.startup.points_elsewhere()
            except Exception:
                available, enabled, elsewhere = True, values.start_with_windows, None
            self.autostart_check.setChecked(enabled)
            self.autostart_check.setEnabled(available)
            self.autostart_background_check.setEnabled(available and enabled)
            self._show_autostart_note(available, elsewhere)
            index = self.theme_combo.findData(self.settings.get_theme())
            self.theme_combo.setCurrentIndex(max(index, 0))
        finally:
            self._loading = False

        self._refresh_backup_status()
        from app.version import APP_VERSION

        self.version_label.setText(f"Office Reminder {APP_VERSION}")

    def _show_autostart_note(self, available: bool, elsewhere: str | None) -> None:
        if not available:
            text = (
                "Kaynak koddan çalışırken Windows başlangıcına eklenmez. "
                "Bu ayarı paketlenmiş uygulamadan (OfficeReminder.exe) yapın."
            )
        elif elsewhere:
            text = (
                f"Başlangıç kaydı başka bir programı gösteriyor: {elsewhere} · "
                "İşaretlerseniz bu uygulamayı gösterecek şekilde düzeltilir."
            )
        else:
            text = ""
        self.autostart_note.setText(text)
        self._autostart_note_row.setHidden(not text)

    def _refresh_backup_status(self) -> None:
        try:
            service = BackupService(get_database_path(), get_backups_dir())
            last = service.get_last_backup_time()
            count = len(service.list_backups())
        except Exception:
            last, count = None, 0
        if last is None:
            self.backup_status.setText("Son yedek: henüz yok")
        else:
            self.backup_status.setText(
                f"Son yedek: {last.strftime('%d.%m.%Y %H:%M')} · toplam {count} yedek"
            )

    # ------------------------------------------------------------------ actions
    def _save_general(self) -> None:
        if self._loading:
            return
        try:
            from services.settings_service import MINI_COUNTER_ENABLED, UPDATE_AUTO_CHECK

            self.settings.set_notifications_enabled(self.notifications_check.isChecked())
            self.settings.set_minimize_to_tray(self.tray_check.isChecked())
            self.settings.set_bool(MINI_COUNTER_ENABLED, self.mini_counter_check.isChecked())
            self.settings.set_bool(UPDATE_AUTO_CHECK, self.update_check.isChecked())
            self.settings.set(
                "notifications.check_interval_minutes", str(self.interval_spin.value())
            )
            self.settings.set("backup.retention_days", str(self.retention_spin.value()))
        except Exception as exc:
            QMessageBox.warning(self, "Ayar kaydedilemedi", str(exc))
            return
        self.settings_changed.emit()

    def _save_theme(self) -> None:
        """Store the appearance choice; it is read at the next start.

        Re-theming a running window would leave icon tints, note papers and the
        calendar's text formats on the old palette, because those are resolved
        when each widget is built.
        """
        if self._loading:
            return
        choice = self.theme_combo.currentData()
        try:
            self.settings.set_theme(choice)
        except Exception as exc:
            QMessageBox.warning(self, "Ayar kaydedilemedi", str(exc))
            return
        self.notify(
            "Görünüm kaydedildi",
            "Uygulamayı kapatıp yeniden açtığınızda geçerli olur.",
            "accent",
        )
        self.settings_changed.emit()

    def _save_startup(self) -> None:
        if self._loading:
            return
        enabled = self.autostart_check.isChecked()
        background = self.autostart_background_check.isChecked()
        self.autostart_background_check.setEnabled(enabled)
        try:
            self.startup.set_enabled(enabled, background=background)
            self.settings.set_start_with_windows(enabled)
            self.settings.set_start_in_background(background)
        except StartupUnavailable as exc:
            QMessageBox.information(self, "Windows ile başlat", str(exc))
            self.refresh()
            return
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Başlangıç ayarı değiştirilemedi",
                f"Windows kayıt defterine yazılamadı.\n\n{exc}",
            )
            self.refresh()
            return
        self._show_autostart_note(self.startup.available(), self.startup.points_elsewhere())
        self.settings_changed.emit()

    def _backup_now(self) -> None:
        try:
            service = BackupService(
                get_database_path(), get_backups_dir(), retention_days=self.retention_spin.value()
            )
            target = service.create_backup(force=True)
        except Exception as exc:
            QMessageBox.warning(self, "Yedek alınamadı", str(exc))
            return
        self._refresh_backup_status()
        self.notify(
            "Yedek alındı",
            f"Oluşturuldu ve doğrulandı · {Path(target).name}"
            if target
            else "Yedek zaten güncel.",
        )

    def _open(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            QMessageBox.warning(self, "Klasör açılamadı", str(exc))


def _indented(widget: QWidget) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(24, 0, 0, 0)
    layout.addWidget(widget)
    return holder
