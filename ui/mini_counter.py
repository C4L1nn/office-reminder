"""Always-on-top mini counter: the single most urgent row, in one glance.

A small frameless card (260px) pinned above other windows. It shows the oldest
overdue item, else the nearest due item, plus "+N iş daha" — the same priority
every list uses, so the card can never disagree with the dashboard.
Click opens the main window; drag moves the card; close hides it (the setting
decides whether it comes back).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, Qt, QSettings, Signal
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QVBoxLayout, QWidget

from services.formatting import long_date, mini_counter_text, mini_counter_tone
from ui.theme import tokens
from ui.widgets import icon_button, label

logger = logging.getLogger("office_reminder.ui.mini_counter")

CARD_WIDTH = 268
CARD_HEIGHT = 66
SETTINGS_ORG = "OfficeReminder"
SETTINGS_KEY = "MiniCounter"


class MiniCounter(QFrame):
    """Frameless always-on-top card. Talks to services, never to SQL."""

    clicked = Signal()
    hide_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Never steal keystrokes from Excel/Chrome when the card appears.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("Açmak için tıklayın, taşımak için sürükleyin")
        self.setAccessibleName("Mini sayaç: en acil iş")

        t = tokens()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(t.space, t.space_sm, t.space_sm, t.space_sm)
        outer.setSpacing(t.space_sm)

        self._dot = label("●", "Dot")
        self._dot.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addWidget(self._dot)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        self._title = label("", "SectionTitle")
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        column.addWidget(self._title)
        self._subtitle = label("", "Muted")
        self._subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        column.addWidget(self._subtitle)
        outer.addLayout(column, 1)

        # A real button (not a clickable label): it accepts the press and grabs
        # the mouse, so closing can never fall through to the card's own
        # click-to-open handler underneath.
        close = icon_button("close", "Mini sayacı gizle")
        close.setFixedSize(24, 24)
        # The stylesheet draws an accent border around a focused button; on a
        # 66px card that reads as a permanent box around the X, so the button
        # stays click-only and never takes keyboard focus.
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self.hide_requested.emit)
        outer.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        self._drag_offset: QPoint | None = None
        self._press_pos: QPoint | None = None
        self._tone = "accent"
        self._apply_tone("accent")
        self._restore_position()

    # ------------------------------------------------------------------ content
    def refresh(self, title: str | None, days: int | None, extra: int, tooltip: str = "") -> None:
        """Render one snapshot. Pure presentation: the caller already chose."""
        heading, subline = mini_counter_text(title, days, extra)
        tone = mini_counter_tone(days)
        self._title.setText(heading)
        self._subtitle.setText(subline)
        self._title.setToolTip(heading)
        self._apply_tone(tone)
        base = "Açmak için tıklayın, taşımak için sürükleyin"
        self.setToolTip(f"{base}\n{tooltip}" if tooltip else base)
        self.setAccessibleName(f"Mini sayaç: {heading}, {subline}")

    def _apply_tone(self, tone: str) -> None:
        self._tone = tone
        t = tokens()
        accent = {
            "danger": t.danger,
            "warning": t.warning,
            "success": t.success,
            "accent": t.accent,
        }.get(tone, t.accent)
        # Same controlled exception as the in-app toast: token value resolved
        # here, because stylesheets cannot compute "left border only" by tone.
        self.setStyleSheet(f"#Card {{ border-left: 3px solid {accent}; }}")
        self._dot.setStyleSheet(f"color: {accent};")

    # ------------------------------------------------------------------ placement
    def _settings(self) -> QSettings:
        return QSettings(SETTINGS_ORG, SETTINGS_KEY)

    def _restore_position(self) -> None:
        try:
            saved = self._settings().value("pos")
            if saved is not None:
                point = QPoint(saved) if not isinstance(saved, QPoint) else saved
                if self._is_on_screen(point):
                    self.move(point)
                    return
        except Exception:
            logger.debug("Mini sayaç konumu okunamadı", exc_info=True)
        self._move_to_default()

    def _move_to_default(self) -> None:
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            area = screen.availableGeometry()
            self.move(
                area.right() - CARD_WIDTH - 16,
                area.bottom() - CARD_HEIGHT - 16,
            )
        except Exception:
            logger.debug("Mini sayaç varsayılan konuma alınamadı", exc_info=True)

    def _is_on_screen(self, point: QPoint) -> bool:
        try:
            for screen in QGuiApplication.screens():
                if screen.availableGeometry().contains(point):
                    return True
        except Exception:
            logger.debug("Ekran kontrolü başarısız", exc_info=True)
            return False
        return False

    def save_position(self) -> None:
        try:
            self._settings().setValue("pos", self.pos())
        except Exception:
            logger.debug("Mini sayaç konumu kaydedilemedi", exc_info=True)

    # ------------------------------------------------------------------ interaction
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            self._press_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt naming
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt naming
        moved = False
        if self._press_pos is not None:
            try:
                moved = (event.globalPosition().toPoint() - self._press_pos).manhattanLength() > 5
            except Exception:
                moved = True
        self._drag_offset = None
        self._press_pos = None
        if event.button() == Qt.MouseButton.LeftButton and not moved:
            # A drag must never open the window; only a clean click does.
            self.clicked.emit()
        else:
            self.save_position()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt naming
        menu = QMenu(self)
        open_action = menu.addAction("Ana pencereyi aç")
        hide_action = menu.addAction("Mini sayacı gizle")
        chosen = menu.exec(event.globalPos())
        if chosen == open_action:
            self.clicked.emit()
        elif chosen == hide_action:
            self.hide_requested.emit()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.save_position()
        super().hideEvent(event)


def tooltip_for(company_name: str | None, title: str, due) -> str:
    """Second tooltip line: company + long date, shared wording with lists."""
    head = title.strip() if title else "—"
    when = long_date(due) if due is not None else "—"
    if company_name:
        return f"{company_name} · {head} · {when}"
    return f"{head} · {when}"
