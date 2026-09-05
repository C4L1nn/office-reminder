from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from database.repositories.notifications import AppNotification
from services.notification_service import NotificationService
from ui import icons
from ui.shell import Page
from ui.theme import tokens
from ui.widgets import Badge, Card, EmptyState, button, label, separator

KIND_LABELS = {
    "DUE": "Yaklaşan",
    "OVERDUE": "Geciken",
    "OFFICIAL_REVISION": "Resmî değişiklik",
}
SEVERITY_TONE = {"INFO": "neutral", "WARNING": "warning", "DANGER": "danger"}
SEVERITY_ICON = {"INFO": "bell", "WARNING": "clock", "DANGER": "alert"}


def when(stamp: str | None) -> str:
    if not stamp:
        return ""
    try:
        value = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return str(stamp)[:16]
    if value.tzinfo is not None:
        value = value.astimezone()
    delta = datetime.now() - value.replace(tzinfo=None)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "az önce"
    if minutes < 60:
        return f"{minutes} dakika önce"
    if minutes < 24 * 60:
        return f"{minutes // 60} saat önce"
    return value.strftime("%d.%m.%Y %H:%M")


class NotificationsPage(Page):
    """The inbox that Do Not Disturb cannot silence.

    Every announcement lands here and stays unread until the user opens this
    screen, so a suppressed Windows toast no longer means a missed deadline.
    """

    unread_changed = Signal(int)
    open_item = Signal(str, int)  # source_kind, source_id

    def __init__(self, notification_service: NotificationService, parent: QWidget | None = None) -> None:
        super().__init__(
            "Bildirimler",
            "Gönderilen tüm hatırlatmalar. Windows bildirimi görünmese de buraya düşer.",
            parent,
        )
        self.service = notification_service
        self._show_unread_only = False
        self._build()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        self.filter_button = button("Yalnızca okunmayanlar", "subtle", "filter")
        self.filter_button.setCheckable(True)
        self.filter_button.toggled.connect(self._on_filter)
        self.mark_all_button = button("Tümünü okundu işaretle", "subtle", "check")
        self.mark_all_button.clicked.connect(self._mark_all)
        self.header.add_action(self.filter_button)
        self.header.add_action(self.mark_all_button)

        self.card = Card()
        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_area.setWidget(self.list_host)
        self.card.add(self.list_area)
        self.add(self.card, 1)

        self.empty = EmptyState(
            "Bildirim yok",
            "Bir hatırlatmanın tarihi yaklaştığında ya da resmî bir tarih değiştiğinde "
            "bildirim burada birikir.",
            "bell",
        )
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        for index in reversed(range(self.list_layout.count())):
            item = self.list_layout.itemAt(index)
            widget = item.widget()
            if widget is not None and widget is not self.empty:
                widget.setParent(None)
                widget.deleteLater()

        try:
            notifications = self.service.inbox.list_recent(
                limit=200, unread_only=self._show_unread_only)
            unread = self.service.unread_count()
        except Exception:
            notifications, unread = [], 0

        self.empty.setVisible(not notifications)
        for position, notification in enumerate(notifications):
            if position:
                self.list_layout.insertWidget(self.list_layout.count() - 1, separator())
            self.list_layout.insertWidget(self.list_layout.count() - 1, self._row(notification))

        self.mark_all_button.setEnabled(unread > 0)
        self.unread_changed.emit(unread)

    def _row(self, notification: AppNotification) -> QWidget:
        t = tokens()
        row = QWidget()
        outer = QHBoxLayout(row)
        outer.setContentsMargins(4, t.space_sm, 4, t.space_sm)
        outer.setSpacing(t.space)

        tone = SEVERITY_TONE.get(notification.severity, "neutral")
        colour = {"danger": t.danger, "warning": t.warning}.get(tone, t.text_faint)
        glyph = label("")
        glyph.setPixmap(icons.pixmap(SEVERITY_ICON.get(notification.severity, "bell"), 18, colour))
        glyph.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addWidget(glyph)

        column = QVBoxLayout()
        column.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(t.space_sm)
        title = label(notification.title, "SectionTitle")
        if notification.is_unread:
            font = title.font()
            font.setBold(True)
            title.setFont(font)
        top.addWidget(title)
        top.addWidget(Badge(KIND_LABELS.get(notification.kind, notification.kind), tone))
        if notification.is_unread:
            top.addWidget(Badge("Yeni", "accent"))
        top.addStretch()
        top.addWidget(label(when(notification.created_at), "Caption"))
        column.addLayout(top)

        body = label(notification.body.replace("\n", " · "), "Muted", wrap=True)
        column.addWidget(body)

        actions = QHBoxLayout()
        actions.setSpacing(t.space_sm)
        if notification.is_unread:
            read = button("Okundu", "ghost", "check")
            read.clicked.connect(lambda _c=False, n=notification.id: self._mark_read(n))
            actions.addWidget(read)
        goto = button("Hatırlatmalarda aç", "ghost", "external")
        goto.clicked.connect(
            lambda _c=False, k=notification.source_kind, i=notification.source_id: self.open_item.emit(k, i)
        )
        actions.addWidget(goto)
        actions.addStretch()
        column.addLayout(actions)

        outer.addLayout(column, 1)
        return row

    # ------------------------------------------------------------------ actions
    def _on_filter(self, checked: bool) -> None:
        self._show_unread_only = checked
        self.refresh()

    def _mark_read(self, notification_id: int) -> None:
        self.service.inbox.mark_read(notification_id)
        self.refresh()

    def _mark_all(self) -> None:
        self.service.inbox.mark_all_read()
        self.refresh()
