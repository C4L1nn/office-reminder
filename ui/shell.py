"""Application shell: the navigation rail and the per-page header."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QSizePolicy,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui import icons
from ui.theme import tokens
from ui.widgets import Badge, label, status_dot


@dataclass(frozen=True, slots=True)
class NavItem:
    key: str
    title: str
    icon: str
    group: str = "main"


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("dashboard", "Ana Sayfa", "dashboard"),
    # The bell belongs to notifications; reminders are a checklist of dates.
    NavItem("reminders", "Hatırlatmalar", "calendar"),
    NavItem("calendar", "Takvim", "calendar_month"),
    NavItem("companies", "Şirketler", "building"),
    NavItem("vehicles", "Araçlar", "car"),
    NavItem("notes", "Notlar", "note"),
    NavItem("notifications", "Bildirimler", "bell", group="system"),
    NavItem("official", "Resmî Güncellemeler", "cloud", group="system"),
    NavItem("settings", "Ayarlar", "settings", group="system"),
)


class Sidebar(QFrame):
    """Vertical navigation with a selected state and a live status footer."""

    navigated = Signal(str)

    def __init__(self, version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Rail")
        self.setFixedWidth(212)
        t = tokens()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.space, t.space_lg, t.space, t.space)
        layout.setSpacing(2)

        # The app has its own mark; leaving the brand as bare text made the
        # rail look unfinished next to every other titled surface.
        brand = QHBoxLayout()
        brand.setSpacing(t.space_sm)
        brand.setContentsMargins(t.space_sm, t.space_sm, t.space_sm, t.space)
        mark = QLabel()
        mark.setPixmap(icons.app_icon().pixmap(22, 22))
        mark.setFixedSize(22, 22)
        brand.addWidget(mark)
        brand.addWidget(label("Office Reminder", "RailBrand"))
        brand.addStretch()
        layout.addLayout(brand)

        self._buttons: dict[str, QPushButton] = {}
        self._badges: dict[str, Badge] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for item in NAV_ITEMS:
            if item.group == "system" and not any(
                b.property("group") == "system" for b in self._buttons.values()
            ):
                layout.addSpacing(t.space_sm)
                line = QFrame()
                line.setObjectName("RailDivider")
                line.setFixedHeight(1)
                layout.addWidget(line)
                layout.addSpacing(t.space_sm)

            button = QPushButton(f"  {item.title}")
            button.setObjectName("RailItem")
            button.setProperty("group", item.group)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(icons.icon(item.icon))
            button.setIconSize(icons.ICON_SIZE)
            button.clicked.connect(lambda _checked=False, key=item.key: self.navigated.emit(key))
            self._group.addButton(button)
            self._buttons[item.key] = button

            # The nav entry carries its own unread counter so the badge is
            # visible from every screen, not only the inbox.
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.setSpacing(0)
            holder_layout.addWidget(button)
            badge = Badge("", "danger")
            badge.setParent(button)
            badge.hide()
            self._badges[item.key] = badge
            layout.addWidget(holder)

        layout.addStretch()

        footer = QVBoxLayout()
        footer.setSpacing(3)
        footer.setContentsMargins(t.space_sm, 0, t.space_sm, 0)
        self._status_row = QHBoxLayout()
        self._status_row.setSpacing(6)
        self._dot = status_dot("neutral")
        self._status = label("Resmî kaynaklar kontrol edilmedi", "RailFooter", wrap=True)
        self._status_row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignTop)
        self._status_row.addWidget(self._status, 1)
        footer.addLayout(self._status_row)
        footer.addWidget(label(f"Sürüm {version}", "RailFooter"))
        layout.addLayout(footer)

    def set_badge(self, key: str, count: int) -> None:
        """Show an unread counter on one navigation entry."""
        badge = self._badges.get(key)
        button = self._buttons.get(key)
        if badge is None or button is None:
            return
        if count <= 0:
            badge.hide()
            return
        badge.setText(str(count) if count < 100 else "99+")
        badge.adjustSize()
        badge.move(button.width() - badge.width() - 10, (button.height() - badge.height()) // 2)
        badge.show()
        badge.raise_()

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        for key, badge in self._badges.items():
            if badge.isVisible():
                self.set_badge(key, int(badge.text().replace("+", "") or 0))

    def select(self, key: str) -> None:
        button = self._buttons.get(key)
        if button and not button.isChecked():
            button.setChecked(True)

    def set_status(self, text: str, tone: str) -> None:
        t = tokens()
        colours = {
            "success": t.success,
            "warning": t.warning,
            "danger": t.danger,
            "neutral": t.text_faint,
        }
        self._status.setText(text)
        self._dot.setStyleSheet(f"color: {colours.get(tone, t.text_faint)};")


class PageHeader(QWidget):
    """Title, one-line purpose, and the page's primary actions."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageHeader")
        t = tokens()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(t.space_xl, t.space, t.space_xl, t.space_sm)
        layout.setSpacing(t.space)

        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = label(title, "PageTitle")
        self.subtitle = label(subtitle, "PageSubtitle", wrap=True)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        layout.addLayout(text, 1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(t.space_sm)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)


class Page(QWidget):
    """Base page: header on top, scroll-free content area below."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        parent: QWidget | None = None,
        *,
        scrollable: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Canvas")
        t = tokens()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = PageHeader(title, subtitle)
        outer.addWidget(self.header)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(t.space_xl, t.space, t.space_xl, t.space)
        self.content_layout.setSpacing(t.space_sm)

        if scrollable:
            # Long, stacked content must scroll rather than squeeze its cards
            # below their minimum height on a 1280x720 screen.
            from PySide6.QtWidgets import QScrollArea

            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(self.content)
            outer.addWidget(area, 1)
        else:
            outer.addWidget(self.content, 1)

    def notify(self, title: str, body: str = "", tone: str = "success") -> None:
        """Report a completed action without blocking the user.

        Success does not need a modal: the office clicks "OK" on a box that
        only says the thing it just asked for worked. Warnings and questions
        stay modal, because those need a decision.
        """
        window = self.window()
        area = getattr(window, "toasts", None)
        if area is None:
            return
        area.show_toast(title, body, tone)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self.content_layout.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self.content_layout.addLayout(layout)


class FilterBar(QFrame):
    """One compact, aligned row of filters plus an optional trailing summary."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        t = tokens()
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(t.space_sm)
        self._summary = label("", "Caption")
        self._stretch_added = False

    def add_field(self, caption: str, widget: QWidget, width: int | None = None) -> QWidget:
        """Add a filter control.

        The caption becomes placeholder/tooltip text rather than a label above
        the field: a stacked label doubled the height of the row and repeated
        what the control already said.
        """
        from PySide6.QtWidgets import QComboBox, QLineEdit

        if isinstance(widget, QLineEdit) and not widget.placeholderText():
            widget.setPlaceholderText(caption)
        widget.setToolTip(caption)
        if isinstance(widget, QComboBox) and widget.count():
            widget.setToolTip(f"{caption}: {widget.currentText()}")
            widget.currentTextChanged.connect(
                lambda text, w=widget, c=caption: w.setToolTip(f"{c}: {text}")
            )
        if width:
            # A preferred width, not a fixed one: at 125% scaling or on a
            # narrow window fixed widths overflowed the row and the controls
            # drew on top of each other.
            widget.setMaximumWidth(width)
            widget.setMinimumWidth(min(width, 108))
            widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, widget.sizePolicy().verticalPolicy()
            )
        self._layout.addWidget(widget, 1 if width else 0)
        return widget

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def finish(self) -> None:
        if not self._stretch_added:
            self._layout.addStretch()
            self._layout.addWidget(self._summary, 0, Qt.AlignmentFlag.AlignVCenter)
            self._stretch_added = True

    def set_summary(self, text: str) -> None:
        self._summary.setText(text)


def section_label(text: str) -> QLabel:
    return label(text, "SectionTitle")
