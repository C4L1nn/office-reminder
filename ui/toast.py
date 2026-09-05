"""In-app notification banner.

Shown inside the window when new notifications arrive while it is open. It is
the visible half of the guaranteed channel: the inbox keeps the record, this
makes it noticeable without depending on the operating system's notification
setting. It never steals focus and never blocks work — it fades out on its own
and can be dismissed.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QVBoxLayout, QWidget

from ui import icons
from ui.theme import tokens
from ui.widgets import button, label

VISIBLE_MS = 9_000
FADE_MS = 260


class InAppToast(QFrame):
    """A single dismissable banner pinned to the bottom-right of its parent."""

    opened = Signal()

    def __init__(self, title: str, body: str, tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        t = tokens()
        accent = {
            "danger": t.danger,
            "warning": t.warning,
            "success": t.success,
            "accent": t.accent,
        }.get(tone, t.accent)
        self.setStyleSheet(f"#Card {{ border-left: 3px solid {accent}; }}")
        self.setFixedWidth(360)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(t.space, t.space, t.space_sm, t.space)
        outer.setSpacing(t.space_sm)

        glyph = label("")
        glyph.setPixmap(icons.pixmap("bell", 18, accent))
        glyph.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addWidget(glyph)

        column = QVBoxLayout()
        column.setSpacing(2)
        heading = label(title, "SectionTitle", wrap=True)
        column.addWidget(heading)
        column.addWidget(label(body, "Muted", wrap=True))
        open_button = button("Bildirimleri aç", "ghost")
        open_button.clicked.connect(self.opened.emit)
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.addWidget(open_button)
        row.addStretch()
        column.addLayout(row)
        outer.addLayout(column, 1)

        close = button("", "ghost")
        close.setIcon(icons.icon("close", color=t.text_faint))
        close.setFixedSize(26, 26)
        close.setToolTip("Kapat")
        close.clicked.connect(self.dismiss)
        outer.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    def present(self) -> None:
        self.show()
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(VISIBLE_MS)

    def dismiss(self) -> None:
        self._timer.stop()
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        try:
            self._fade.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._fade.finished.connect(self._finish)
        self._fade.start()

    def _finish(self) -> None:
        self.hide()
        self.setParent(None)
        self.deleteLater()


class ToastArea(QWidget):
    """Stacks banners in the bottom-right corner of the window."""

    opened = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens().space_sm)
        layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        self._layout = layout
        self.setFixedWidth(384)
        self.hide()

    def show_toast(self, title: str, body: str, tone: str = "neutral") -> None:
        toast = InAppToast(title, body, tone, self)
        toast.opened.connect(self.opened.emit)
        toast.destroyed.connect(self._reposition)
        self._layout.addWidget(toast)
        self.show()
        toast.present()
        self._reposition()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        margin = tokens().space_lg
        self.move(
            max(0, parent.width() - self.width() - margin),
            max(0, parent.height() - self.height() - margin),
        )
        self.raise_()
        if self._layout.count() == 0:
            self.hide()

    def reposition(self) -> None:
        self._reposition()
