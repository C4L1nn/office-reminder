"""Storage for the sticky-note canvas.

A note carries its own geometry, so the board looks exactly the way the user
left it after a restart. Nothing here knows about companies, reminders or due
dates — a note is deliberately not an obligation (PLAN.md § 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from database.connection import Database

#: Smallest note the canvas will store, mirrored by a trigger in migration 012.
MIN_WIDTH = 120.0
MIN_HEIGHT = 90.0

#: Paper colours are stored as palette keys, never as hex, so that light and
#: dark themes can each draw the same note with their own palette.
PAPER_COLOURS = ("yellow", "amber", "mint", "sky", "rose", "lilac", "slate")
DEFAULT_COLOUR = "yellow"


@dataclass(slots=True, frozen=True)
class Board:
    id: int
    name: str
    position: int


@dataclass(slots=True)
class Note:
    id: int
    board_id: int
    content_html: str
    content_text: str
    x: float
    y: float
    width: float
    height: float
    z: int
    colour: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NotesRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ------------------------------------------------------------------ boards
    def list_boards(self) -> list[Board]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT id, name, position FROM note_boards ORDER BY position, id"
            ).fetchall()
        return [Board(id=r["id"], name=r["name"], position=r["position"]) for r in rows]

    def create_board(self, name: str) -> int:
        name = " ".join(name.split()) or "Yeni sayfa"
        with self.database.session() as connection:
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM note_boards"
            ).fetchone()["p"]
            cursor = connection.execute(
                "INSERT INTO note_boards (name, position, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (name, position, _now(), _now()),
            )
            return int(cursor.lastrowid)

    def rename_board(self, board_id: int, name: str) -> None:
        name = " ".join(name.split())
        if not name:
            raise ValueError("Sayfa adı boş olamaz")
        with self.database.session() as connection:
            connection.execute(
                "UPDATE note_boards SET name = ?, updated_at = ? WHERE id = ?",
                (name, _now(), board_id),
            )

    def delete_board(self, board_id: int) -> None:
        """Remove a board and its notes. The last board is never removed.

        An empty Notes screen with no board at all would need a separate
        "create a board first" state; keeping one board makes that impossible.
        """
        with self.database.session() as connection:
            remaining = connection.execute(
                "SELECT COUNT(*) AS c FROM note_boards"
            ).fetchone()["c"]
            if remaining <= 1:
                raise ValueError("Son sayfa silinemez")
            connection.execute("DELETE FROM notes WHERE board_id = ?", (board_id,))
            connection.execute("DELETE FROM note_boards WHERE id = ?", (board_id,))

    # ------------------------------------------------------------------- notes
    def list_notes(self, board_id: int) -> list[Note]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT id, board_id, content_html, content_text, x, y, width, height,"
                "       z, colour, updated_at"
                "  FROM notes WHERE board_id = ? ORDER BY z, id",
                (board_id,),
            ).fetchall()
        return [Note(**dict(row)) for row in rows]

    def create_note(
        self,
        board_id: int,
        *,
        x: float,
        y: float,
        width: float = 240.0,
        height: float = 200.0,
        colour: str = DEFAULT_COLOUR,
        content_html: str = "",
        content_text: str = "",
    ) -> int:
        if colour not in PAPER_COLOURS:
            raise ValueError(f"Bilinmeyen kâğıt rengi: {colour}")
        width = max(float(width), MIN_WIDTH)
        height = max(float(height), MIN_HEIGHT)
        with self.database.session() as connection:
            top = connection.execute(
                "SELECT COALESCE(MAX(z), 0) + 1 AS z FROM notes WHERE board_id = ?",
                (board_id,),
            ).fetchone()["z"]
            cursor = connection.execute(
                "INSERT INTO notes (board_id, content_html, content_text, x, y,"
                "                   width, height, z, colour, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    board_id, content_html, content_text, float(x), float(y),
                    width, height, top, colour, _now(), _now(),
                ),
            )
            return int(cursor.lastrowid)

    def update_geometry(
        self, note_id: int, *, x: float, y: float, width: float, height: float
    ) -> None:
        with self.database.session() as connection:
            connection.execute(
                "UPDATE notes SET x = ?, y = ?, width = ?, height = ?, updated_at = ?"
                " WHERE id = ?",
                (
                    float(x), float(y),
                    max(float(width), MIN_WIDTH), max(float(height), MIN_HEIGHT),
                    _now(), note_id,
                ),
            )

    def update_content(self, note_id: int, *, html: str, text: str) -> None:
        with self.database.session() as connection:
            connection.execute(
                "UPDATE notes SET content_html = ?, content_text = ?, updated_at = ?"
                " WHERE id = ?",
                (html, text, _now(), note_id),
            )

    def update_colour(self, note_id: int, colour: str) -> None:
        if colour not in PAPER_COLOURS:
            raise ValueError(f"Bilinmeyen kâğıt rengi: {colour}")
        with self.database.session() as connection:
            connection.execute(
                "UPDATE notes SET colour = ?, updated_at = ? WHERE id = ?",
                (colour, _now(), note_id),
            )

    def set_z_order(self, order: list[int]) -> None:
        """Rewrite the stacking order in one session, front-most last."""
        with self.database.session() as connection:
            for index, note_id in enumerate(order):
                connection.execute(
                    "UPDATE notes SET z = ?, updated_at = ? WHERE id = ?",
                    (index, _now(), note_id),
                )

    def delete_note(self, note_id: int) -> None:
        with self.database.session() as connection:
            connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def all_content_html(self) -> list[str]:
        """Every note's markup, for working out which pictures are still used."""
        with self.database.session() as connection:
            rows = connection.execute("SELECT content_html FROM notes").fetchall()
        return [row["content_html"] or "" for row in rows]

    def search(self, term: str) -> list[Note]:
        """Plain-text search; the HTML is never matched against."""
        term = term.strip()
        if not term:
            return []
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT id, board_id, content_html, content_text, x, y, width, height,"
                "       z, colour, updated_at"
                "  FROM notes WHERE content_text LIKE ? ORDER BY updated_at DESC",
                (f"%{term}%",),
            ).fetchall()
        return [Note(**dict(row)) for row in rows]
