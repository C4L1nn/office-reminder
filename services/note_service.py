"""Board and note operations for the sticky-note canvas.

The UI asks this service for everything; it never touches the repository or
SQL directly. Arrangement (tile / stack / cascade) lives here rather than in
the canvas so the geometry it produces is the same geometry that gets stored.
"""

from __future__ import annotations

import logging

from database.connection import Database
from database.repositories.notes import (
    DEFAULT_COLOUR,
    MIN_HEIGHT,
    MIN_WIDTH,
    PAPER_COLOURS,
    Board,
    Note,
    NotesRepository,
)

#: Gap between notes when the user asks for an automatic arrangement.
ARRANGE_GAP = 16.0
#: Offset between notes in a cascade, big enough to leave the header visible.
CASCADE_STEP = 32.0
#: Grid step for snapping. A multiple of 8 keeps notes visually aligned with
#: the rest of the app's spacing scale.
GRID = 8.0


logger = logging.getLogger("office_reminder.notes")


class NoteService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = NotesRepository(database)

    # ------------------------------------------------------------------ boards
    def list_boards(self) -> list[Board]:
        boards = self.repository.list_boards()
        if not boards:
            # Migration 012 seeds one, but a database restored from an older
            # backup can arrive without it.
            self.repository.create_board("Notlarım")
            boards = self.repository.list_boards()
        return boards

    def create_board(self, name: str) -> int:
        return self.repository.create_board(name)

    def rename_board(self, board_id: int, name: str) -> None:
        self.repository.rename_board(board_id, name)

    def delete_board(self, board_id: int) -> None:
        self.repository.delete_board(board_id)
        self.prune_images()

    # ------------------------------------------------------------------- notes
    def list_notes(self, board_id: int) -> list[Note]:
        return self.repository.list_notes(board_id)

    def create_note(
        self,
        board_id: int,
        *,
        x: float = 40.0,
        y: float = 40.0,
        colour: str = DEFAULT_COLOUR,
    ) -> Note:
        note_id = self.repository.create_note(board_id, x=x, y=y, colour=colour)
        for note in self.repository.list_notes(board_id):
            if note.id == note_id:
                return note
        raise RuntimeError("Not oluşturuldu ama okunamadı")

    def move_or_resize(
        self, note_id: int, *, x: float, y: float, width: float, height: float
    ) -> None:
        self.repository.update_geometry(
            note_id, x=x, y=y, width=max(width, MIN_WIDTH), height=max(height, MIN_HEIGHT)
        )

    def set_content(self, note_id: int, *, html: str, text: str) -> None:
        self.repository.update_content(note_id, html=html, text=text)

    def set_colour(self, note_id: int, colour: str) -> None:
        self.repository.update_colour(note_id, colour)

    def delete_note(self, note_id: int) -> None:
        self.repository.delete_note(note_id)
        self.prune_images()

    def search(self, term: str) -> list[Note]:
        return self.repository.search(term)

    def prune_images(self) -> int:
        """Drop pasted pictures no note points at any more.

        They live outside the database, so deleting a note removes the markup
        that referenced them but never the file itself.
        """
        try:
            from services.note_images import NoteImageStore

            store = NoteImageStore()
            used: set[str] = set()
            for html in self.repository.all_content_html():
                used |= NoteImageStore.references(html)
            return store.prune(used)
        except Exception:
            logger.warning("Not görselleri temizlenemedi", exc_info=True)
            return 0

    # --------------------------------------------------------------- ordering
    def bring_to_front(self, board_id: int, note_id: int) -> None:
        order = [n.id for n in self.repository.list_notes(board_id) if n.id != note_id]
        order.append(note_id)
        self.repository.set_z_order(order)

    def send_to_back(self, board_id: int, note_id: int) -> None:
        order = [n.id for n in self.repository.list_notes(board_id) if n.id != note_id]
        self.repository.set_z_order([note_id, *order])

    # ------------------------------------------------------------ arrangement
    def arrange(self, board_id: int, mode: str, *, canvas_width: float = 1200.0) -> None:
        """Lay the board's notes out in rows, a column, or a cascade.

        Order is the order the user sees them stacked in, so an arrangement is
        predictable: what is at the back ends up first.
        """
        # Validate before reading the board: an unknown mode is a programming
        # error and must be refused whether or not the board happens to be empty.
        layouts = {
            "rows": lambda items: self._arrange_rows(items, canvas_width),
            "column": self._arrange_column,
            "cascade": self._arrange_cascade,
        }
        if mode not in layouts:
            raise ValueError(f"Bilinmeyen dizilim: {mode}")
        notes = self.repository.list_notes(board_id)
        if not notes:
            return
        layouts[mode](notes)

    def _arrange_rows(self, notes: list[Note], canvas_width: float) -> None:
        x = y = ARRANGE_GAP
        row_height = 0.0
        for note in notes:
            if x > ARRANGE_GAP and x + note.width > canvas_width:
                x = ARRANGE_GAP
                y += row_height + ARRANGE_GAP
                row_height = 0.0
            self.repository.update_geometry(
                note.id, x=x, y=y, width=note.width, height=note.height
            )
            x += note.width + ARRANGE_GAP
            row_height = max(row_height, note.height)

    def _arrange_column(self, notes: list[Note]) -> None:
        y = ARRANGE_GAP
        for note in notes:
            self.repository.update_geometry(
                note.id, x=ARRANGE_GAP, y=y, width=note.width, height=note.height
            )
            y += note.height + ARRANGE_GAP

    def _arrange_cascade(self, notes: list[Note]) -> None:
        for index, note in enumerate(notes):
            offset = ARRANGE_GAP + index * CASCADE_STEP
            self.repository.update_geometry(
                note.id, x=offset, y=offset, width=note.width, height=note.height
            )


def snap(value: float, enabled: bool = True) -> float:
    """Round a coordinate onto the grid when snapping is on."""
    if not enabled:
        return value
    return round(value / GRID) * GRID


__all__ = [
    "ARRANGE_GAP",
    "CASCADE_STEP",
    "GRID",
    "PAPER_COLOURS",
    "Board",
    "Note",
    "NoteService",
    "snap",
]
