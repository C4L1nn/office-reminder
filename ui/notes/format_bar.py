"""Rich-text controls that act on whichever note currently has focus.

One shared bar rather than a toolbar per note: seven notes on screen would
otherwise mean seven toolbars competing with the text they format.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextListFormat
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFontComboBox,
    QHBoxLayout,
    QTextEdit,
    QWidget,
)

from ui.theme import PAPER_ORDER, note_paper, tokens
from ui.widgets import icon_button, label, separator

FONT_SIZES = (9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36)


class PaperSwatch(QWidget):
    """A single colour chip in the paper palette."""

    clicked = Signal(str)

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(key)
        self._active = False

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QPainter, QPen

        paper = note_paper(self.key)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(paper.fill))
        painter.setPen(
            QPen(QColor(tokens().accent if self._active else paper.edge),
                 2 if self._active else 1)
        )
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 4, 4)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.key)


class FormatBar(QWidget):
    """Bold/italic/underline, font, size, colour, bullets and paper colour."""

    paper_chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FormatBar")
        self._editor: QTextEdit | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens().space_xs)

        self.bold = self._toggle("bold", "Kalın", QFont.Weight.Bold)
        self.italic = self._toggle("italic", "İtalik", italic=True)
        self.underline = self._toggle("underline", "Altı çizili", underline=True)
        for widget in (self.bold, self.italic, self.underline):
            row.addWidget(widget)

        row.addWidget(separator(horizontal=False))

        self.font_combo = QFontComboBox()
        self.font_combo.setMaximumWidth(180)
        self.font_combo.setToolTip("Yazı tipi")
        self.font_combo.currentFontChanged.connect(self._apply_family)
        row.addWidget(self.font_combo)

        self.size_combo = QComboBox()
        self.size_combo.setEditable(False)
        self.size_combo.setFixedWidth(68)
        self.size_combo.setToolTip("Punto")
        for size in FONT_SIZES:
            self.size_combo.addItem(str(size), size)
        self.size_combo.setCurrentText("11")
        self.size_combo.currentIndexChanged.connect(self._apply_size)
        row.addWidget(self.size_combo)

        self.ink = icon_button("text_colour", "Seçili metnin rengi", "subtle")
        self.ink.clicked.connect(self._apply_ink)
        row.addWidget(self.ink)

        self.bullets = icon_button("bullet_list", "Madde işaretli liste", "subtle")
        self.bullets.clicked.connect(self._apply_bullets)
        row.addWidget(self.bullets)

        row.addWidget(separator(horizontal=False))
        row.addWidget(label("Kâğıt", "FieldLabel"))

        self.swatches: list[PaperSwatch] = []
        for key in PAPER_ORDER:
            swatch = PaperSwatch(key)
            swatch.clicked.connect(self.paper_chosen)
            row.addWidget(swatch)
            self.swatches.append(swatch)

        row.addStretch()
        self.set_editor(None)

    # ------------------------------------------------------------------ state
    def set_editor(self, editor: QTextEdit | None) -> None:
        """Point the bar at a note, or disable it when nothing is focused."""
        self._editor = editor
        enabled = editor is not None
        for widget in (
            self.bold, self.italic, self.underline,
            self.font_combo, self.size_combo, self.ink, self.bullets,
        ):
            widget.setEnabled(enabled)
        if editor is not None:
            self._sync_from(editor)

    def set_paper(self, key: str) -> None:
        for swatch in self.swatches:
            swatch.set_active(swatch.key == key)

    def _sync_from(self, editor: QTextEdit) -> None:
        """Reflect the format at the cursor so the buttons are not lying."""
        fmt = editor.currentCharFormat()
        for widget, active in (
            (self.bold, fmt.fontWeight() >= QFont.Weight.Bold),
            (self.italic, fmt.fontItalic()),
            (self.underline, fmt.fontUnderline()),
        ):
            widget.blockSignals(True)
            widget.setChecked(bool(active))
            widget.blockSignals(False)

        size = int(fmt.fontPointSize()) or editor.font().pointSize()
        self.size_combo.blockSignals(True)
        index = self.size_combo.findData(size)
        if index >= 0:
            self.size_combo.setCurrentIndex(index)
        self.size_combo.blockSignals(False)

        family = fmt.fontFamilies()
        if family:
            self.font_combo.blockSignals(True)
            self.font_combo.setCurrentFont(QFont(family[0]))
            self.font_combo.blockSignals(False)

    # ---------------------------------------------------------------- actions
    def _toggle(self, glyph: str, tip: str, weight=None, italic=False, underline=False):
        """A checkable icon button. Lettered B/I/U were clipped by the button's
        own padding at this size, and the icon set is what the rest of the app
        uses anyway."""
        widget = icon_button(glyph, tip, "subtle")
        widget.setCheckable(True)
        widget.clicked.connect(
            lambda checked, w=weight, i=italic, u=underline: self._apply_style(
                checked, w, i, u
            )
        )
        return widget

    def _merge(self, fmt: QTextCharFormat) -> None:
        """Apply to the selection, or to what is typed next when there is none."""
        if self._editor is None:
            return
        cursor = self._editor.textCursor()
        cursor.mergeCharFormat(fmt)
        self._editor.mergeCurrentCharFormat(fmt)
        self._editor.setFocus()

    def _apply_style(self, checked: bool, weight, italic: bool, underline: bool) -> None:
        fmt = QTextCharFormat()
        if weight is not None:
            fmt.setFontWeight(QFont.Weight.Bold if checked else QFont.Weight.Normal)
        if italic:
            fmt.setFontItalic(checked)
        if underline:
            fmt.setFontUnderline(checked)
        self._merge(fmt)

    def _apply_family(self, font: QFont) -> None:
        fmt = QTextCharFormat()
        fmt.setFontFamilies([font.family()])
        self._merge(fmt)

    def _apply_size(self) -> None:
        size = self.size_combo.currentData()
        if not size:
            return
        fmt = QTextCharFormat()
        fmt.setFontPointSize(float(size))
        self._merge(fmt)

    def _apply_ink(self) -> None:
        if self._editor is None:
            return
        colour = QColorDialog.getColor(
            self._editor.textColor(), self, "Metin rengi"
        )
        if not colour.isValid():
            return
        fmt = QTextCharFormat()
        fmt.setForeground(colour)
        self._merge(fmt)

    def _apply_bullets(self) -> None:
        if self._editor is None:
            return
        cursor = self._editor.textCursor()
        if cursor.currentList() is not None:
            # Already a list: turn it back into ordinary paragraphs.
            block = cursor.blockFormat()
            block.setObjectIndex(-1)
            cursor.setBlockFormat(block)
        else:
            cursor.createList(QTextListFormat.Style.ListDisc)
        self._editor.setFocus()
