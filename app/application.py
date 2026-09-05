from __future__ import annotations

import logging
import sys
from datetime import datetime

from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from app.logging_config import setup_logging
from app.paths import (
    ensure_runtime_dirs,
    get_backups_dir,
    get_database_path,
    get_logs_dir,
    get_migrations_dir,
    get_seed_dir,
)
from app.single_instance import SingleInstanceGuard
from app.version import APP_NAME, APP_VERSION
from database.connection import Database
from database.migrations import MigrationRunner
from services.backup_service import BackupService
from services.company_service import CompanyService
from services.holiday_service import HolidayService
from services.note_service import NoteService
from services.notification_service import NotificationService
from services.official_calendar_service import OfficialCalendarSeedService
from services.official_update_service import OfficialUpdateService
from services.reminder_service import ReminderService
from services.settings_service import SettingsService
from services.sgk_calendar_service import SgkCalendarService
from services.startup_service import StartupService
from services.sync_worker import run_in_background
from ui import icons
from ui.main_window import MainWindow
from ui.theme import apply_theme, tokens_for

logger = logging.getLogger("office_reminder.app")

SYNC_INTERVAL_MS = 6 * 60 * 60 * 1000
FIRST_NOTIFICATION_DELAY_MS = 4_000
FIRST_SYNC_DELAY_MS = 12_000


class OfficeReminderApplication:
    """Wires the app together: storage, services, tray, window, timers.

    Order matters here. Nothing that touches the network happens on the Qt
    thread, and the window is only built after the database is known to be
    migrated, so a schema problem surfaces as a clear message rather than a
    half-drawn UI.
    """

    def __init__(self, background: bool = False) -> None:
        self.background = background
        self.qt_app = QApplication(sys.argv)
        self.qt_app.setApplicationName(APP_NAME)
        self.qt_app.setApplicationDisplayName(APP_NAME)
        self.qt_app.setApplicationVersion(APP_VERSION)
        self.qt_app.setOrganizationName("OfficeReminder")
        self.qt_app.setQuitOnLastWindowClosed(False)
        self._install_turkish_translation()

        self.theme = apply_theme(self.qt_app)
        self.qt_app.setWindowIcon(icons.app_icon())

        self._guard = SingleInstanceGuard()
        if not self._guard.try_acquire():
            QMessageBox.information(
                None,
                APP_NAME,
                "Office Reminder zaten çalışıyor.\n\nSistem tepsisindeki simgeye çift tıklayarak açabilirsiniz.",
            )
            raise SystemExit(0)

        ensure_runtime_dirs()
        setup_logging(get_logs_dir())
        logger.info("=== %s %s starting (background=%s) ===", APP_NAME, APP_VERSION, background)
        logger.info("Runtime root: %s", get_logs_dir().parent)

        self.database = Database(get_database_path())
        self._first_run = not get_database_path().exists()
        self._migrate()

        self.settings_service = SettingsService(self.database)
        # The first apply_theme above runs before the database exists, so that
        # an early error dialog is still themed. Now that the stored choice is
        # readable, honour it — still before any window is built.
        self.theme = apply_theme(
            self.qt_app, tokens_for(self.settings_service.get_theme(), self.qt_app)
        )
        self.qt_app.setWindowIcon(icons.app_icon())
        self.note_service = NoteService(self.database)
        self.reminder_service = ReminderService(self.database)
        self.company_service = CompanyService(self.database)
        self.startup_service = StartupService()

        self._load_official_baseline()
        self._daily_backup()

        self.tray_icon = self._build_tray()
        self.notification_service = NotificationService(
            self.database, self.reminder_service, self.tray_icon
        )
        self.official_service = OfficialUpdateService(
            self.database, notifier=self.notification_service
        )

        self.main_window = MainWindow(
            self.reminder_service,
            self.company_service,
            self.settings_service,
            self.official_service,
            self.startup_service,
            self.notification_service,
            self.note_service,
        )
        self.main_window.set_tray_icon(self.tray_icon)
        self.main_window.sync_requested.connect(self.run_sync)
        self.main_window.quit_requested.connect(self.quit)
        # The tray icon carries the unread count, so a suppressed toast still
        # leaves something visible in the taskbar.
        self.main_window.unread_changed.connect(self._update_tray_badge)
        self.main_window.refresh_unread()

        self._start_timers()
        logger.info("Startup complete")

    # ------------------------------------------------------------------ storage
    def _migrate(self) -> None:
        try:
            applied = MigrationRunner(self.database, get_migrations_dir()).run()
        except Exception as exc:
            logger.critical("Migration failed", exc_info=True)
            QMessageBox.critical(
                None,
                APP_NAME,
                "Veritabanı hazırlanamadı ve uygulama başlatılamıyor.\n\n"
                f"{exc}\n\nVerileriniz silinmedi. Günlük klasörü:\n{get_logs_dir()}",
            )
            raise SystemExit(1) from exc
        logger.info("Migrations applied: %s (first run: %s)", applied or "none", self._first_run)

    def _install_turkish_translation(self) -> None:
        """Translate Qt's own dialog buttons.

        Standard buttons ("Yes", "No", "Cancel") are drawn by Qt, not by us, so
        without this the office sees English words in the middle of a Turkish
        confirmation. The translator has to be kept alive for the life of the
        application or Qt drops it.
        """
        translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        self._translator = QTranslator()
        if self._translator.load("qtbase_tr", translations):
            self.qt_app.installTranslator(self._translator)
        else:
            logger.warning("Qt Türkçe çevirisi yüklenemedi: %s", translations)

    def _load_official_baseline(self) -> None:
        """Seed the bundled GİB calendar and generate SGK rule dates. Idempotent."""
        try:
            inserted = OfficialCalendarSeedService(self.database, get_seed_dir()).import_seed(
                "official_calendar_2026.json"
            )
            logger.info("GİB seed: %s new events", inserted)
        except Exception:
            logger.error("GİB seed import failed; existing calendar left untouched", exc_info=True)

        try:
            holidays = HolidayService(self.database)
            sgk = SgkCalendarService(self.database, holidays)
            now = datetime.now()  # business year is local, not UTC
            years = {2026, now.year}
            if now.month == 12:
                years.add(now.year + 1)
            for year in sorted(years):
                try:
                    count = sgk.generate_and_import(
                        year, wage_periods=["MONTHLY_1_END", "MONTHLY_15_14"]
                    )
                    logger.info("SGK %s: %s new events", year, count)
                except Exception:
                    logger.warning("SGK generation skipped for %s", year, exc_info=True)
        except Exception:
            logger.error("SGK calendar generation failed", exc_info=True)

    def _daily_backup(self) -> None:
        if self._first_run:
            logger.info("First run: backup deferred to next start")
            return
        try:
            settings = self.settings_service.load()
            if not settings.backup_enabled:
                return
            service = BackupService(
                get_database_path(), get_backups_dir(), retention_days=settings.backup_retention_days
            )
            created = service.create_backup_if_needed()
            logger.info("Backup: %s", created or "already taken today")
        except Exception:
            logger.warning("Daily backup failed (non-blocking)", exc_info=True)

    # ------------------------------------------------------------------ tray
    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(icons.app_icon(), self.qt_app)
        tray.setToolTip(f"{APP_NAME} {APP_VERSION}")

        menu = QMenu()
        self._menu = menu  # keep a reference; a garbage-collected menu breaks the tray

        open_action = QAction("Office Reminder'ı Aç", menu)
        open_action.triggered.connect(self.show_window)
        menu.addAction(open_action)

        today_action = QAction("Bugünkü İşler", menu)
        today_action.triggered.connect(self._show_today)
        menu.addAction(today_action)

        notifications_action = QAction("Bildirimler", menu)
        notifications_action.triggered.connect(self._show_notifications)
        menu.addAction(notifications_action)

        quick_action = QAction("Hızlı Hatırlatma…", menu)
        quick_action.triggered.connect(self._quick_add)
        menu.addAction(quick_action)

        menu.addSeparator()

        check_action = QAction("Hatırlatmaları Şimdi Kontrol Et", menu)
        check_action.triggered.connect(self.run_notification_check)
        menu.addAction(check_action)

        sync_action = QAction("Resmî Güncellemeleri Kontrol Et", menu)
        sync_action.triggered.connect(self.run_sync)
        menu.addAction(sync_action)

        menu.addSeparator()

        quit_action = QAction("Çıkış", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        return tray

    def _update_tray_badge(self, unread: int) -> None:
        try:
            self.tray_icon.setIcon(icons.app_icon_with_badge(unread))
            suffix = f" — {unread} okunmamış bildirim" if unread else ""
            self.tray_icon.setToolTip(f"{APP_NAME} {APP_VERSION}{suffix}")
        except Exception:
            logger.debug("Tray badge update failed", exc_info=True)

    def _show_notifications(self) -> None:
        self.show_window()
        self.main_window.show_page("notifications")

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self.show_window()

    def _show_today(self) -> None:
        self.show_window()
        self.main_window.show_page("dashboard")
        self.main_window.dashboard_page._select_view("TODAY")

    def _quick_add(self) -> None:
        from ui.dialogs.quick_add_dialog import QuickAddDialog

        self.show_window()
        dialog = QuickAddDialog(self.company_service, self.main_window)
        if dialog.exec() != QuickAddDialog.DialogCode.Accepted:
            return
        try:
            self.reminder_service.quick_add(**dialog.get_data())
        except Exception as exc:
            QMessageBox.warning(self.main_window, "Hatırlatma kaydedilemedi", str(exc))
            return
        self.main_window.refresh_all()

    # ------------------------------------------------------------------ timers
    def _start_timers(self) -> None:
        minutes = self.settings_service.load().check_interval_minutes
        self.notification_timer = QTimer(self.qt_app)
        self.notification_timer.setInterval(max(1, minutes) * 60 * 1000)
        self.notification_timer.timeout.connect(self.run_notification_check)
        self.notification_timer.start()
        QTimer.singleShot(FIRST_NOTIFICATION_DELAY_MS, self.run_notification_check)

        self.sync_timer = QTimer(self.qt_app)
        self.sync_timer.setInterval(SYNC_INTERVAL_MS)
        self.sync_timer.timeout.connect(self.run_sync)
        self.sync_timer.start()
        QTimer.singleShot(FIRST_SYNC_DELAY_MS, self.run_sync)

    def run_notification_check(self) -> None:
        try:
            delivered = self.notification_service.check_and_notify()
            if delivered:
                logger.info("Delivered %s notification(s)", delivered)
        except Exception:
            logger.error("Notification check failed", exc_info=True)

    def run_sync(self) -> None:
        """Check official sources off the Qt thread; never block the UI."""
        if getattr(self, "_sync_running", False):
            return
        self._sync_running = True
        self.main_window.set_sync_busy(True)

        database = self.database

        def work() -> dict:
            # A fresh service instance: SQLite connections are per-call, and the
            # worker must not share objects with the UI thread.
            return OfficialUpdateService(database).sync_all()

        def done(result: dict) -> None:
            self._sync_running = False
            logger.info("Official sync finished: %s", result)
            # Announcing runs on the Qt thread so the toast has a live tray icon.
            try:
                shown = self.official_service.announce_revisions()
                if shown:
                    logger.info("Announced %s official date change(s)", shown)
            except Exception:
                logger.warning("Announcing revisions failed", exc_info=True)
            self.main_window.sync_finished()

        def failed(message: str) -> None:
            self._sync_running = False
            # Offline is normal; the local calendar keeps working, so this is a
            # log line and a status row, never a modal.
            logger.warning("Official sync failed: %s", message)
            self.main_window.sync_finished()

        run_in_background(work, on_finished=done, on_error=failed)

    # ------------------------------------------------------------------ lifecycle
    def show_window(self) -> None:
        self.main_window.show()
        self.main_window.setWindowState(
            self.main_window.windowState() & ~self.main_window.windowState().WindowMinimized
        )
        self.main_window.raise_()
        self.main_window.activateWindow()

    def quit(self) -> None:
        """Leave for good: nothing here may prevent the process from exiting."""
        logger.info("Shutting down")
        for step in (self._save_window_state, self._hide_tray):
            try:
                step()
            except Exception:
                logger.debug("Shutdown step %s failed", step.__name__, exc_info=True)
        self._guard.unlock()
        self.qt_app.quit()

    def _save_window_state(self) -> None:
        self.main_window.save_state()

    def _hide_tray(self) -> None:
        # Without this the tray icon can linger as a ghost until hovered.
        self.tray_icon.hide()

    def run(self) -> int:
        if self.background:
            logger.info("Background start: tray only")
        else:
            self.show_window()
        return self.qt_app.exec()
