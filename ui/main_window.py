from __future__ import annotations

import logging

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSettings,
    Qt,
    Signal,
)
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.version import APP_VERSION
from services.company_service import CompanyService
from services.official_update_service import OfficialUpdateService
from services.reminder_service import ReminderService
from services.settings_service import SettingsService
from services.startup_service import StartupService
from ui import icons
from ui.pages.companies_page import CompaniesPage
from ui.pages.dashboard_page import DashboardPage
from services.note_service import NoteService
from services.search_service import (
    COMPANY,
    NOTE,
    REMINDER,
    VEHICLE,
    SearchService,
)
from ui.dialogs.search_dialog import SearchDialog
from ui.update_banner import UpdateBanner
from ui.pages.calendar_page import CalendarPage
from ui.pages.notes_page import NotesPage
from ui.pages.notifications_page import NotificationsPage
from ui.pages.official_page import OfficialPage
from ui.pages.reminders_page import RemindersPage
from ui.pages.settings_page import SettingsPage
from ui.pages.vehicles_page import VehiclesPage
from ui.shell import Sidebar
from ui.toast import ToastArea

logger = logging.getLogger("office_reminder.ui")

PAGE_ORDER = (
    "dashboard", "reminders", "calendar", "companies", "vehicles", "notes",
    "notifications", "official", "settings",
)


class MainWindow(QMainWindow):
    """Sidebar shell hosting one page at a time."""

    sync_requested = Signal()
    quit_requested = Signal()
    unread_changed = Signal(int)
    #: A record somewhere in the app changed. Anything living outside the
    #: window — the tray badge, the always-on-top mini counter — listens here
    #: rather than re-reading on a timer and lagging behind the user.
    data_changed = Signal()

    def __init__(
        self,
        reminder_service: ReminderService,
        company_service: CompanyService,
        settings_service: SettingsService,
        official_service: OfficialUpdateService,
        startup_service: StartupService | None = None,
        notification_service=None,
        note_service: NoteService | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Office Reminder")
        self.setWindowIcon(icons.app_icon())
        # Comfortable on 1366x768 and up; still usable at 1280x720.
        self.setMinimumSize(1060, 660)
        self.resize(1280, 800)

        self.reminder_service = reminder_service
        self.company_service = company_service
        self.settings_service = settings_service
        self.official_service = official_service
        self.notification_service = notification_service

        self._tray_icon: QSystemTrayIcon | None = None
        self._minimize_to_tray = settings_service.load().minimize_to_tray
        self._tray_hint_shown = False

        central = QWidget()
        central.setObjectName("Canvas")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar(APP_VERSION)
        self.sidebar.navigated.connect(self.show_page)
        layout.addWidget(self.sidebar)

        # Sayfaların üstünde, kenar çubuğunun sağında: güncelleme şeridi
        # kabuğun sözü, sayfanın değil, ama sayfayı da örtmemeli.
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.update_banner = UpdateBanner()
        right_layout.addWidget(self.update_banner)
        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)
        layout.addWidget(right, 1)
        self.setCentralWidget(central)

        self.dashboard_page = DashboardPage(reminder_service, company_service)
        self.reminders_page = RemindersPage(reminder_service, company_service)
        self.companies_page = CompaniesPage(company_service)
        self.vehicles_page = VehiclesPage(company_service, reminder_service)
        self.calendar_page = CalendarPage(reminder_service, company_service)
        self.notes_page = NotesPage(note_service or NoteService(company_service.database))
        self.official_page = OfficialPage(official_service)
        self.settings_page = SettingsPage(settings_service, startup_service)
        self.notifications_page = (
            NotificationsPage(notification_service) if notification_service is not None else None
        )

        self._pages = {
            "dashboard": self.dashboard_page,
            "reminders": self.reminders_page,
            "calendar": self.calendar_page,
            "companies": self.companies_page,
            "vehicles": self.vehicles_page,
            "notes": self.notes_page,
            "official": self.official_page,
            "settings": self.settings_page,
        }
        if self.notifications_page is not None:
            self._pages["notifications"] = self.notifications_page
        for key in PAGE_ORDER:
            page = self._pages.get(key)
            if page is not None:
                self.stack.addWidget(page)

        self.dashboard_page.reminder_requested.connect(self._new_reminder)
        self.dashboard_page.navigate.connect(self.show_page)
        self.companies_page.data_changed.connect(self.refresh_all)
        self.vehicles_page.data_changed.connect(self.refresh_all)
        self.reminders_page.data_changed.connect(self.refresh_all)
        self.official_page.sync_requested.connect(self.sync_requested.emit)
        self.settings_page.open_official.connect(lambda: self.show_page("official"))
        self.settings_page.settings_changed.connect(self._settings_changed)
        self.notes_page.reminder_requested.connect(self._reminder_from_note)

        self._search_dialog: SearchDialog | None = None
        self._search_service = SearchService(company_service.database)
        self._install_shortcuts()

        # In-app banner: the visible half of the channel Do Not Disturb cannot mute.
        self.toasts = ToastArea(self)
        self.toasts.opened.connect(lambda: self.show_page("notifications"))

        if self.notifications_page is not None:
            self.notifications_page.unread_changed.connect(self._set_unread)
            self.notifications_page.open_item.connect(self._open_source)
        if notification_service is not None:
            notification_service.inbox_changed.connect(self.on_new_notifications)

        self._restore_geometry()
        self.show_page("dashboard")
        self.refresh_unread()

    # ------------------------------------------------------------------ navigation
    # --------------------------------------------------------------- shortcuts
    #: (keys, what it does, how it is described in Settings). Ctrl+1..8 are
    #: added on top of these, one per navigation entry.
    SHORTCUTS = (
        ("Ctrl+K", "open_search", "Her yerde ara"),
        ("Ctrl+N", "new_record", "Bulunduğun ekranda yeni kayıt"),
        ("Ctrl+F", "focus_filter", "Filtre kutusuna geç"),
        ("Ctrl+E", "export_current", "Listeyi dışa aktar"),
        ("F5", "refresh_current", "Ekranı yenile"),
        ("Ctrl+Shift+R", "sync_now", "Resmî kaynakları kontrol et"),
        ("Ctrl+Shift+V", "reminder_from_clipboard", "Panodaki metinden hatırlatma"),
    )

    def _install_shortcuts(self) -> None:
        """Keyboard access for the things done every day.

        An office tool that can only be driven with the mouse feels unfinished;
        these are the conventional Windows bindings, not invented ones.
        """
        for keys, handler, _description in self.SHORTCUTS:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(getattr(self, handler))

        # Numbered over the pages that exist, not over PAGE_ORDER: the
        # notifications page is only built when a notification service is
        # supplied, and a gap in Ctrl+1..8 would be a puzzle for the user.
        registered = [key for key in PAGE_ORDER if key in self._pages]
        for index, key in enumerate(registered, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(lambda k=key: self.show_page(k))

    def _current_page(self):
        return self.stack.currentWidget()

    def new_record(self) -> None:
        """Ctrl+N means "new thing on this screen", whatever that is here."""
        page = self._current_page()
        for method in ("create_reminder", "create_company", "create_vehicle", "_create_note"):
            action = getattr(page, method, None)
            if callable(action):
                action()
                return

    def focus_filter(self) -> None:
        page = self._current_page()
        for name in ("search_edit", "filter_edit", "input"):
            widget = getattr(page, name, None)
            if widget is not None and hasattr(widget, "setFocus"):
                widget.setFocus()
                widget.selectAll() if hasattr(widget, "selectAll") else None
                return

    def export_current(self) -> None:
        page = self._current_page()
        for method in ("_export_menu", "_export_pdf"):
            action = getattr(page, method, None)
            if callable(action):
                action()
                return

    def refresh_current(self) -> None:
        self._refresh(self._current_page())

    def sync_now(self) -> None:
        self.sync_requested.emit()

    # ------------------------------------------------------------------ search
    def open_search(self) -> None:
        """Ctrl+K: one box over companies, vehicles, reminders and notes."""
        if self._search_dialog is None:
            self._search_dialog = SearchDialog(self._search_service, self)
            self._search_dialog.hit_chosen.connect(self.reveal_hit)
        self._search_dialog.open_with("")

    def reveal_hit(self, hit) -> None:
        """Take the user to the record they picked.

        Each page knows how to bring one of its own records into view; when it
        cannot (the record was deleted meanwhile), showing the page is still
        better than doing nothing.
        """
        if hit.kind == COMPANY:
            self.show_page("companies")
            self.companies_page.refresh()
            self.companies_page.select_company(hit.record_id)
        elif hit.kind == VEHICLE:
            self.show_page("vehicles")
            self.vehicles_page.refresh()
            self.vehicles_page.select_vehicle(hit.record_id)
        elif hit.kind == REMINDER:
            self.show_page("reminders")
            self.reminders_page.reveal(hit.context or hit.title)
        elif hit.kind == NOTE:
            self.show_page("notes")
            self.notes_page.refresh()
            if hit.context.isdigit():
                self.notes_page.show_board(int(hit.context))

    #: Short enough to feel instant, long enough to read as a change of place.
    PAGE_FADE_MS = 130

    def _fade_in(self, page) -> None:
        """A brief fade when the screen changes.

        The effect is removed as soon as it finishes: leaving a permanent
        opacity effect on a page forces every later repaint through an offscreen
        pixmap, which the notes canvas in particular pays for.
        """
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(self.PAGE_FADE_MS)
        animation.setStartValue(0.35)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: page.setGraphicsEffect(None))
        self._page_animation = animation
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def show_page(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        changed = self.stack.currentWidget() is not page
        self.sidebar.select(key)
        self.stack.setCurrentWidget(page)
        if changed:
            self._fade_in(page)
        self._refresh(page)
        if key != "official":
            self.update_official_status()
        if key != "notifications":
            self.refresh_unread()

    def _refresh(self, page) -> None:
        refresh = getattr(page, "refresh", None)
        if refresh is None:
            return
        try:
            refresh()
        except Exception:
            logger.warning("Refreshing %s failed", type(page).__name__, exc_info=True)

    def refresh_all(self) -> None:
        self._refresh(self.stack.currentWidget())
        self.update_official_status()
        self.data_changed.emit()

    def update_official_status(self) -> None:
        try:
            text, tone = self.official_page.status_tone()
        except Exception:
            text, tone = "Resmî kaynak durumu okunamadı", "warning"
        self.sidebar.set_status(text, tone)

    def _new_reminder(self) -> None:
        # No refresh_all here: the page announces its own change, and calling
        # both would re-read the whole shell twice for one new record.
        self.reminders_page.create_reminder()

    def reminder_from_clipboard(self) -> None:
        """Make a reminder out of whatever is on the clipboard.

        A due date arrives as a line in an e-mail or a message far more often
        than as a form; this takes that line and fills in what it can, leaving
        the rest for the dialog. Nothing is saved without the user pressing
        save, so a bad read costs a glance, not a wrong record.
        """
        from PySide6.QtWidgets import QApplication, QMessageBox

        from services.date_phrases import extract_date

        text = (QApplication.clipboard().text() or "").strip()
        if not text:
            QMessageBox.information(
                self, "Pano boş", "Hatırlatmaya çevrilecek metin bulunamadı."
            )
            return

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            QMessageBox.information(
                self, "Pano boş", "Hatırlatmaya çevrilecek metin bulunamadı."
            )
            return

        prefill: dict = {"title": lines[0][:120]}
        if len(lines) > 1:
            prefill["notes"] = "\n".join(lines[1:])
        found = extract_date(text)
        if found is not None:
            prefill["due_date"], prefill["date_phrase"] = found

        self.show_page("reminders")
        self.reminders_page.create_reminder(prefill=prefill)

    def _reminder_from_note(self, prefill: dict) -> None:
        """A note asked to become a reminder; the reminders screen owns that."""
        self.show_page("reminders")
        self.reminders_page.create_reminder(prefill=prefill)

    def _settings_changed(self) -> None:
        self._minimize_to_tray = self.settings_service.load().minimize_to_tray

    # ------------------------------------------------------------------ notifications
    def refresh_unread(self) -> None:
        if self.notification_service is None:
            return
        self._set_unread(self.notification_service.unread_count())

    def _set_unread(self, count: int) -> None:
        self.sidebar.set_badge("notifications", count)
        self.unread_changed.emit(count)

    def on_new_notifications(self, unread: int) -> None:
        """New items reached the inbox: badge always, banner when visible."""
        self._set_unread(unread)
        if self.notifications_page is not None and self.stack.currentWidget() is self.notifications_page:
            self.notifications_page.refresh()
            return
        if not self.isVisible():
            return
        try:
            latest = self.notification_service.inbox.list_recent(limit=1, unread_only=True)
        except Exception:
            latest = []
        if not latest:
            return
        newest = latest[0]
        tone = {"DANGER": "danger", "WARNING": "warning"}.get(newest.severity, "accent")
        self.toasts.show_toast(newest.title, newest.body.replace("\n", " · "), tone)

    def _open_source(self, source_kind: str, _source_id: int) -> None:
        self.show_page("reminders")

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts.reposition()

    # ------------------------------------------------------------------ sync feedback
    def set_sync_busy(self, busy: bool) -> None:
        self.official_page.set_busy(busy)

    def sync_finished(self) -> None:
        self.official_page.set_busy(False)
        self.official_page.refresh()
        self.update_official_status()
        self._refresh(self.stack.currentWidget())

    # ------------------------------------------------------------------ window chrome
    def set_tray_icon(self, tray_icon: QSystemTrayIcon) -> None:
        self._tray_icon = tray_icon

    def _restore_geometry(self) -> None:
        try:
            settings = QSettings("OfficeReminder", "OfficeReminder")
            geometry = settings.value("window/geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except Exception:
            logger.debug("Could not restore window geometry", exc_info=True)

    def save_state(self) -> None:
        """Persist window chrome (geometry only; business data lives in SQLite)."""
        self._save_geometry()

    def _save_geometry(self) -> None:
        try:
            settings = QSettings("OfficeReminder", "OfficeReminder")
            settings.setValue("window/geometry", self.saveGeometry())
        except Exception:
            logger.debug("Could not save window geometry", exc_info=True)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        self._save_geometry()
        tray_available = self._tray_icon is not None and self._tray_icon.isVisible()
        if self._minimize_to_tray and tray_available:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                settings = QSettings("OfficeReminder", "OfficeReminder")
                if not settings.value("window/tray_hint_shown", False, type=bool):
                    settings.setValue("window/tray_hint_shown", True)
                    self._tray_icon.showMessage(
                        "Office Reminder arka planda",
                        "Hatırlatmalar çalışmaya devam ediyor. Tamamen kapatmak için "
                        "tepsi menüsünden Çıkış'ı seçin.",
                        QSystemTrayIcon.MessageIcon.Information,
                        6000,
                    )
            return
        event.accept()
        self.quit_requested.emit()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._refresh(self.stack.currentWidget())
