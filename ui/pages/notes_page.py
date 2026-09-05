"""The Notes screen: sticky-note boards.

A note is not an obligation. Nothing here creates reminders, due dates or
notifications; it is the scratch pad that used to be a paper square on the
edge of the monitor.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QTabBar,
    QWidget,
)

from services.export_service import ExportError, default_name, write_board_pdf
from services.note_service import NoteService
from ui.notes.canvas import BOARD_WIDTH, NoteCanvas
from ui.notes.format_bar import FormatBar
from ui.shell import Page
from ui.theme import tokens
from ui.widgets import button, icon_button, label

logger = logging.getLogger(__name__)

#: Typing must not produce one UPDATE per keystroke, so edits are collected
#: and written once the user pauses.
SAVE_DELAY_MS = 600


class NotesPage(Page):
    #: Asks the window to open a new reminder prefilled from a note.
    reminder_requested = Signal(dict)

    def __init__(self, service: NoteService, parent: QWidget | None = None) -> None:
        super().__init__(
            "Notlar",
            "Yapışkan notlar. Sürükleyerek dizin, köşesinden boyutlandırın; "
            "vadesi olan işler için hatırlatma kullanın.",
            parent,
        )
        self.service = service
        self._board_id: int | None = None
        self._focused: int | None = None
        self._pending: dict[int, tuple[str, str]] = {}

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._flush_pending)

        self.export_button = icon_button("download", "Bu sayfayı PDF olarak kaydet", "subtle")
        self.export_button.clicked.connect(self._export_pdf)
        self.header.add_action(self.export_button)

        self.add_note_button = button("+ Yeni Not", "primary")
        self.add_note_button.clicked.connect(lambda: self._create_note())
        self.header.add_action(self.add_note_button)

        self._build()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        t = tokens()

        boards = QHBoxLayout()
        boards.setContentsMargins(0, 0, 0, 0)
        boards.setSpacing(t.space_sm)
        self.tabs = QTabBar()
        self.tabs.setObjectName("BoardTabs")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        # Renaming and deleting a page live on the tab's own context menu:
        # two permanent buttons for rare actions crowded the row.
        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._board_menu)
        self.tabs.currentChanged.connect(self._on_board_changed)
        boards.addWidget(self.tabs)

        add_board = icon_button("plus", "Yeni not sayfası", "subtle")
        add_board.clicked.connect(self._create_board)
        boards.addWidget(add_board)

        boards.addStretch()
        self.add_layout(boards)

        self.format_bar = FormatBar()
        self.format_bar.paper_chosen.connect(self._set_paper)
        self.add(self.format_bar)

        arrange = QHBoxLayout()
        arrange.setContentsMargins(0, 0, 0, 0)
        arrange.setSpacing(t.space_xs)
        arrange.addWidget(label("Diz", "FieldLabel"))
        for mode, glyph, tip in (
            ("rows", "tile_rows", "Yan yana diz"),
            ("column", "tile_column", "Alt alta diz"),
            ("cascade", "cascade", "Kaskat diz"),
        ):
            chip = icon_button(glyph, tip, "subtle")
            chip.clicked.connect(lambda _checked=False, m=mode: self._arrange(m))
            arrange.addWidget(chip)

        arrange.addSpacing(t.space_sm)

        self.snap_button = icon_button("grid", "Izgaraya yapış", "subtle")
        self.snap_button.setCheckable(True)
        self.snap_button.setChecked(True)
        self.snap_button.toggled.connect(self._toggle_snap)
        arrange.addWidget(self.snap_button)

        reset = icon_button("zoom_reset", "Yakınlaştırmayı sıfırla", "subtle")
        reset.clicked.connect(lambda: self.canvas.reset_zoom())
        arrange.addWidget(reset)

        arrange.addStretch()
        self.canvas_hint = label(
            "Not eklemek için boş alana çift tıklayın · "
            "Sayfayı yönetmek için sekmeye sağ tıklayın",
            "Caption",
        )
        arrange.addWidget(self.canvas_hint)
        self.add_layout(arrange)

        self.canvas = NoteCanvas()
        self.canvas.note_moved.connect(self._on_moved)
        self.canvas.note_edited.connect(self._on_edited)
        self.canvas.note_focused.connect(self._on_focused)
        self.canvas.note_deleted.connect(self._delete_note)
        self.canvas.raise_requested.connect(self._raise_note)
        self.canvas.lower_requested.connect(self._lower_note)
        self.canvas.create_requested.connect(self._create_note)
        self.canvas.reminder_requested.connect(self._reminder_from_note)
        self.add(self.canvas, 1)

    # ---------------------------------------------------------------- loading
    def refresh(self) -> None:
        boards = self.service.list_boards()
        current = self._board_id

        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for board in boards:
            self.tabs.addTab(board.name)
            self.tabs.setTabData(self.tabs.count() - 1, board.id)
        index = next(
            (i for i, b in enumerate(boards) if b.id == current), 0
        )
        self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)

        self._board_id = boards[index].id if boards else None
        self._load_notes()

    def _load_notes(self) -> None:
        if self._board_id is None:
            return
        self._flush_pending()
        self.canvas.load(self.service.list_notes(self._board_id))
        self._focused = None
        self.format_bar.set_editor(None)
        self.format_bar.set_paper("")

    def _on_board_changed(self, index: int) -> None:
        board_id = self.tabs.tabData(index)
        if board_id is None or board_id == self._board_id:
            return
        self._flush_pending()
        self._board_id = int(board_id)
        self._load_notes()

    def show_board(self, board_id: int) -> bool:
        """Switch to a board by id; used by the global search."""
        for index in range(self.tabs.count()):
            if self.tabs.tabData(index) == board_id:
                self.tabs.setCurrentIndex(index)
                return True
        return False

    # ----------------------------------------------------------------- boards
    def _create_board(self) -> None:
        name, ok = QInputDialog.getText(self, "Yeni sayfa", "Sayfa adı:")
        if not ok or not name.strip():
            return
        self._board_id = self.service.create_board(name)
        self.refresh()

    def _board_menu(self, point) -> None:
        index = self.tabs.tabAt(point)
        if index < 0:
            return
        self.tabs.setCurrentIndex(index)
        menu = QMenu(self)
        menu.addAction("Yeniden adlandır").triggered.connect(self._rename_board)
        delete = menu.addAction("Sayfayı sil")
        delete.triggered.connect(self._delete_board)
        # The last page cannot be deleted; show why instead of failing on click.
        delete.setEnabled(self.tabs.count() > 1)
        menu.exec(self.tabs.mapToGlobal(point))

    def _rename_board(self) -> None:
        if self._board_id is None:
            return
        current = self.tabs.tabText(self.tabs.currentIndex())
        name, ok = QInputDialog.getText(
            self, "Sayfayı yeniden adlandır", "Sayfa adı:", text=current
        )
        if not ok or not name.strip():
            return
        self.service.rename_board(self._board_id, name)
        self.refresh()

    def _delete_board(self) -> None:
        if self._board_id is None:
            return
        name = self.tabs.tabText(self.tabs.currentIndex())
        confirm = QMessageBox.question(
            self,
            "Sayfayı sil",
            f"“{name}” sayfası ve içindeki bütün notlar silinecek. Devam edilsin mi?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete_board(self._board_id)
        except ValueError as exc:
            QMessageBox.information(self, "Sayfa silinemedi", str(exc))
            return
        self._board_id = None
        self.refresh()

    # ------------------------------------------------------------------ notes
    def _create_note(self, x: float = 40.0, y: float = 40.0) -> None:
        if self._board_id is None:
            return
        colour = self._next_colour()
        note = self.service.create_note(self._board_id, x=x, y=y, colour=colour)
        item = self.canvas.add_note(note)
        item.setSelected(True)
        item.body.setFocus()
        self._on_focused(note.id)

    def _next_colour(self) -> str:
        """Cycle the palette so a new board does not become a wall of yellow."""
        from ui.theme import PAPER_ORDER

        if self._board_id is None:
            return PAPER_ORDER[0]
        used = len(self.service.list_notes(self._board_id))
        return PAPER_ORDER[used % len(PAPER_ORDER)]

    def _delete_note(self, note_id: int) -> None:
        self._pending.pop(note_id, None)
        self.service.delete_note(note_id)
        self.canvas.remove_note(note_id)
        if self._focused == note_id:
            self._focused = None
            self.format_bar.set_editor(None)

    def _raise_note(self, note_id: int) -> None:
        if self._board_id is None:
            return
        self.service.bring_to_front(self._board_id, note_id)
        self.canvas.apply_order(self.service.list_notes(self._board_id))

    def _lower_note(self, note_id: int) -> None:
        if self._board_id is None:
            return
        self.service.send_to_back(self._board_id, note_id)
        self.canvas.apply_order(self.service.list_notes(self._board_id))

    def _set_paper(self, key: str) -> None:
        if self._focused is None:
            return
        self.service.set_colour(self._focused, key)
        item = self.canvas.item(self._focused)
        if item is not None:
            item.apply_colour(key)
        self.format_bar.set_paper(key)

    # -------------------------------------------------------------- canvas io
    def _on_moved(
        self, note_id: int, x: float, y: float, width: float, height: float
    ) -> None:
        self.service.move_or_resize(note_id, x=x, y=y, width=width, height=height)

    def _on_edited(self, note_id: int, html: str, text: str) -> None:
        self._pending[note_id] = (html, text)
        self._save_timer.start()

    def _flush_pending(self) -> None:
        pending, self._pending = self._pending, {}
        for note_id, (html, text) in pending.items():
            try:
                self.service.set_content(note_id, html=html, text=text)
            except Exception:
                logger.warning("Not kaydedilemedi: %s", note_id, exc_info=True)

    def _on_focused(self, note_id: int) -> None:
        self._focused = note_id
        item = self.canvas.item(note_id)
        if item is None:
            return
        self.format_bar.set_editor(item.body)
        self.format_bar.set_paper(item.colour_key)

    def _reminder_from_note(self, note_id: int) -> None:
        """Turn a scribble into a tracked reminder.

        The first line becomes the title and the rest the note body, because
        that is how people write a sticky note. A date mentioned anywhere in
        the text is offered as the due date — the dialog echoes what it read,
        so a wrong guess is visible before saving.
        """
        from services.date_phrases import extract_date

        self._flush_pending()
        item = self.canvas.item(note_id)
        if item is None:
            return
        text = item.body.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Boş not", "Bu notta hatırlatmaya çevrilecek metin yok."
            )
            return

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        prefill: dict = {"title": lines[0][:120]}
        if len(lines) > 1:
            prefill["notes"] = "\n".join(lines[1:])
        found = extract_date(text)
        if found is not None:
            prefill["due_date"], prefill["date_phrase"] = found[0], found[1]
        self.reminder_requested.emit(prefill)

    # ---------------------------------------------------------------- export
    def _export_pdf(self) -> None:
        """Write the current board to a PDF, in board reading order."""
        if self._board_id is None:
            return
        self._flush_pending()
        notes = self.service.list_notes(self._board_id)
        if not notes:
            QMessageBox.information(
                self, "Dışa aktarma", "Bu sayfada dışa aktarılacak not yok."
            )
            return

        name = self.tabs.tabText(self.tabs.currentIndex()) or "notlar"
        safe = "".join(ch for ch in name if ch.isalnum() or ch in " -_").strip() or "notlar"
        suggested = str(Path.home() / default_name(safe.replace(" ", "_").lower(), "pdf"))
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF olarak kaydet", suggested, "PDF dosyası (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"

        rect = self.canvas.board_rect()
        try:
            write_board_pdf(
                self.canvas.render_board,
                (rect.width(), rect.height()),
                Path(path),
                f"Notlar · {name}",
            )
        except ExportError as exc:
            QMessageBox.warning(self, "Dışa aktarılamadı", str(exc))
            return
        except Exception as exc:
            logger.error("Not dışa aktarma başarısız", exc_info=True)
            QMessageBox.warning(self, "Dışa aktarılamadı", str(exc))
            return
        self.notify("Dışa aktarıldı", f"{len(notes)} not · {Path(path).name}")

    # ------------------------------------------------------------ arrangement
    def _arrange(self, mode: str) -> None:
        if self._board_id is None:
            return
        width = max(self.canvas.viewport().width() - 40, 400)
        self.service.arrange(self._board_id, mode, canvas_width=min(width, BOARD_WIDTH))
        self.canvas.apply_geometry(self.service.list_notes(self._board_id))

    def _toggle_snap(self, enabled: bool) -> None:
        self.canvas.snap_enabled = enabled
        self.canvas.viewport().update()

    # ------------------------------------------------------------------ close
    def hideEvent(self, event) -> None:  # noqa: N802
        """Leaving the page must not lose an in-flight edit."""
        self._flush_pending()
        super().hideEvent(event)
