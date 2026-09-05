"""Shared dialog chrome: sectioned form, inline validation, fixed footer."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.theme import tokens
from ui.widgets import button, label, restyle


class FormDialog(QDialog):
    """A dialog whose body is a stack of titled sections.

    The footer keeps Cancel on the left and the confirming action on the right,
    always with the same wording pattern, so the default action is never in
    doubt. Validation messages appear next to the field, not in a message box.
    """

    def __init__(
        self,
        title: str,
        submit_text: str,
        parent: QWidget | None = None,
        width: int = 560,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        t = tokens()
        self.setMinimumWidth(width)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(t.space_xl, t.space_lg, t.space_xl, t.space_lg)
        self._body.setSpacing(t.space_lg)
        self._scroll.setWidget(body)
        outer.addWidget(self._scroll, 1)

        footer = QFrame()
        footer.setObjectName("DialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(t.space_xl, t.space, t.space_xl, t.space)
        footer_layout.setSpacing(t.space_sm)
        self.error_label = label("", "Caption", wrap=True)
        self.error_label.setStyleSheet(f"color: {t.danger};")
        footer_layout.addWidget(self.error_label, 1)
        self.cancel_button = button("İptal", "subtle")
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button = button(submit_text, "primary")
        self.submit_button.setDefault(True)
        self.submit_button.setAutoDefault(True)
        self.submit_button.clicked.connect(self._on_submit)
        footer_layout.addWidget(self.cancel_button)
        footer_layout.addWidget(self.submit_button)
        outer.addWidget(footer)

        self._invalid: list[QWidget] = []

    # ------------------------------------------------------------------ sections
    def add_section(self, title: str, hint: str = "") -> "FormSection":
        section = FormSection(title, hint)
        self._body.addWidget(section)
        return section

    def add_widget(self, widget: QWidget) -> None:
        self._body.addWidget(widget)

    def finish_body(self) -> None:
        self._body.addStretch()

    # ------------------------------------------------------------------ validation
    def mark_invalid(self, widget: QWidget, message: str) -> None:
        widget.setProperty("state", "invalid")
        restyle(widget)
        self._invalid.append(widget)
        self.error_label.setText(message)
        widget.setFocus()

    def clear_validation(self) -> None:
        for widget in self._invalid:
            widget.setProperty("state", "")
            restyle(widget)
        self._invalid.clear()
        self.error_label.setText("")

    def validate(self) -> bool:
        """Subclasses override; return False after calling mark_invalid."""
        return True

    def _on_submit(self) -> None:
        self.clear_validation()
        if self.validate():
            self.accept()


class FormRow:
    """Handle for one label/field pair, so a row hides as a unit.

    Hiding only the field would leave its label behind — the reason the
    "Aralık" caption used to linger when recurrence was set back to none.
    """

    __slots__ = ("label", "field", "hint")

    def __init__(self, label_widget: QWidget, field: QWidget, hint: QWidget | None) -> None:
        self.label = label_widget
        self.field = field
        self.hint = hint

    def setVisible(self, visible: bool) -> None:  # noqa: N802 - mirrors QWidget
        self.label.setVisible(visible)
        self.field.setVisible(visible)
        if self.hint is not None:
            self.hint.setVisible(visible)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - mirrors QWidget
        self.field.setEnabled(enabled)


class FormSection(QFrame):
    """Titled group of label/field rows."""

    def __init__(self, title: str, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        t = tokens()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(t.space_sm)

        outer.addWidget(label(title, "SectionTitle"))
        if hint:
            outer.addWidget(label(hint, "Caption", wrap=True))

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 2, 0, 0)
        self.grid.setHorizontalSpacing(t.space)
        self.grid.setVerticalSpacing(t.space_sm)
        self.grid.setColumnStretch(1, 1)
        outer.addLayout(self.grid)
        self._row = 0

    def add_row(self, caption: str, widget: QWidget, *, required: bool = False, hint: str = "") -> "FormRow":
        text = f"{caption} *" if required else caption
        name = label(text, "FieldLabel")
        name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        name.setMinimumWidth(112)
        self.grid.addWidget(name, self._row, 0)
        self.grid.addWidget(widget, self._row, 1)
        self._row += 1
        hint_label = None
        if hint:
            hint_label = label(hint, "Caption", wrap=True)
            self.grid.addWidget(hint_label, self._row, 1)
            self._row += 1
        return FormRow(name, widget, hint_label)

    def add_full(self, widget: QWidget) -> QWidget:
        self.grid.addWidget(widget, self._row, 0, 1, 2)
        self._row += 1
        return widget
