"""Ctrl+K: type, arrow down, Enter.

A dialog rather than a bar wired into a page, because the point of it is that
you do not yet know which page the record is on.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from services.search_service import KIND_ORDER, MIN_TERM, SearchHit, SearchService
from ui import icons
from ui.theme import tokens
from ui.widgets import label, list_row, list_row_size

#: Typing is faster than querying four tables; wait for a pause.
DEBOUNCE_MS = 160


class SearchDialog(QDialog):
    """A single box over companies, vehicles, reminders and notes."""

    hit_chosen = Signal(object)

    def __init__(self, service: SearchService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setObjectName("SearchDialog")
        self.setWindowTitle("Ara")
        self.setModal(True)
        self.setMinimumWidth(540)

        t = tokens()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.space, t.space, t.space, t.space)
        layout.setSpacing(t.space_sm)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Şirket, plaka, hatırlatma veya not ara")
        self.input.setClearButtonEnabled(True)
        self.input.textChanged.connect(self._schedule)
        layout.addWidget(self.input)

        self.results = QListWidget()
        self.results.setMinimumHeight(320)
        self.results.itemActivated.connect(self._activate)
        self.results.itemClicked.connect(self._activate)
        layout.addWidget(self.results, 1)

        self.status = label("En az iki harf yazın.", "Caption")
        layout.addWidget(self.status)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._run)

    # ------------------------------------------------------------------ input
    def _schedule(self) -> None:
        self._timer.start()

    def _run(self) -> None:
        term = self.input.text()
        self.results.clear()
        if len(" ".join(term.split())) < MIN_TERM:
            self.status.setText("En az iki harf yazın.")
            return

        hits = self.service.search(term)
        if not hits:
            self.status.setText(f"“{term}” için sonuç yok.")
            return

        order = {kind: index for index, kind in enumerate(KIND_ORDER)}
        for hit in sorted(hits, key=lambda h: order.get(h.kind, 99)):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, hit)
            item.setSizeHint(list_row_size())
            self.results.addItem(item)
            widget = list_row(hit.title, hit.subtitle, hit.kind_label)
            self.results.setItemWidget(item, widget)
        self.results.setCurrentRow(0)
        self.status.setText(f"{len(hits)} sonuç · Enter ile aç")

    # --------------------------------------------------------------- keyboard
    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Arrows and Enter drive the list while the cursor stays in the box."""
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.results.currentRow()
            step = 1 if key == Qt.Key.Key_Down else -1
            count = self.results.count()
            if count:
                self.results.setCurrentRow((row + step) % count)
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.results.currentItem()
            if item is not None:
                self._activate(item)
            event.accept()
            return
        super().keyPressEvent(event)

    def _activate(self, item: QListWidgetItem) -> None:
        hit: SearchHit | None = item.data(Qt.ItemDataRole.UserRole)
        if hit is None:
            return
        self.hit_chosen.emit(hit)
        self.accept()

    def open_with(self, term: str = "") -> None:
        self.input.setText(term)
        self.input.selectAll()
        self.input.setFocus()
        self._run()
        self.show()


__all__ = ["SearchDialog"]
