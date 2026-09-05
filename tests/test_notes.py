"""Sticky-note board: storage, ordering and arrangement.

A note is not an obligation — it carries no due date and must never reach the
reminder or notification tables. These tests pin that boundary along with the
geometry rules the canvas depends on.
"""

from __future__ import annotations

import pytest

from database.repositories.notes import MIN_HEIGHT, MIN_WIDTH, NotesRepository
from services.note_service import ARRANGE_GAP, NoteService, snap


@pytest.fixture()
def notes(migrated_db) -> NoteService:
    return NoteService(migrated_db)


def test_migration_seeds_exactly_one_board(notes: NoteService) -> None:
    boards = notes.list_boards()
    assert len(boards) == 1
    assert boards[0].name == "Notlarım"


def test_note_round_trips_its_geometry(notes: NoteService, migrated_db) -> None:
    board = notes.list_boards()[0]
    note = notes.create_note(board.id, x=120, y=64)
    notes.move_or_resize(note.id, x=300, y=210, width=280, height=160)

    stored = notes.list_notes(board.id)[0]
    assert (stored.x, stored.y) == (300, 210)
    assert (stored.width, stored.height) == (280, 160)


def test_a_note_cannot_be_shrunk_out_of_existence(notes: NoteService) -> None:
    """A zero-width note would be invisible and unrecoverable on the canvas."""
    board = notes.list_boards()[0]
    note = notes.create_note(board.id)
    notes.move_or_resize(note.id, x=0, y=0, width=1, height=1)

    stored = notes.list_notes(board.id)[0]
    assert stored.width == MIN_WIDTH
    assert stored.height == MIN_HEIGHT


def test_colour_is_a_palette_key_not_a_hex(notes: NoteService) -> None:
    board = notes.list_boards()[0]
    note = notes.create_note(board.id)
    notes.set_colour(note.id, "mint")
    assert notes.list_notes(board.id)[0].colour == "mint"
    with pytest.raises(ValueError):
        notes.set_colour(note.id, "#ffcc00")


def test_bring_to_front_and_send_to_back(notes: NoteService) -> None:
    board = notes.list_boards()[0]
    first = notes.create_note(board.id, x=0, y=0)
    second = notes.create_note(board.id, x=20, y=20)
    third = notes.create_note(board.id, x=40, y=40)

    notes.bring_to_front(board.id, first.id)
    assert [n.id for n in notes.list_notes(board.id)] == [second.id, third.id, first.id]

    notes.send_to_back(board.id, third.id)
    assert [n.id for n in notes.list_notes(board.id)] == [third.id, second.id, first.id]


def test_arrange_rows_wraps_at_the_canvas_edge(notes: NoteService) -> None:
    board = notes.list_boards()[0]
    for _ in range(3):
        notes.create_note(board.id)

    notes.arrange(board.id, "rows", canvas_width=560)
    placed = notes.list_notes(board.id)
    # 240 wide plus a 16 gap: two fit on a row of 560, the third wraps.
    assert [n.y for n in placed] == [ARRANGE_GAP, ARRANGE_GAP, ARRANGE_GAP + 200 + ARRANGE_GAP]
    assert placed[0].x == ARRANGE_GAP
    assert placed[2].x == ARRANGE_GAP


def test_arrange_column_and_cascade(notes: NoteService) -> None:
    board = notes.list_boards()[0]
    for _ in range(3):
        notes.create_note(board.id)

    notes.arrange(board.id, "column")
    xs = {n.x for n in notes.list_notes(board.id)}
    assert xs == {ARRANGE_GAP}

    notes.arrange(board.id, "cascade")
    placed = notes.list_notes(board.id)
    offsets = [(n.x, n.y) for n in placed]
    assert offsets == sorted(offsets)
    assert len(set(offsets)) == 3


def test_unknown_arrangement_is_refused(notes: NoteService) -> None:
    board = notes.list_boards()[0]
    with pytest.raises(ValueError):
        notes.arrange(board.id, "spiral")


def test_deleting_a_board_takes_its_notes_but_never_the_last_one(
    notes: NoteService, migrated_db
) -> None:
    first = notes.list_boards()[0]
    second_id = notes.create_board("Ofis")
    notes.create_note(second_id)

    notes.delete_board(second_id)
    assert [b.id for b in notes.list_boards()] == [first.id]
    with migrated_db.session() as connection:
        left = connection.execute(
            "SELECT COUNT(*) c FROM notes WHERE board_id = ?", (second_id,)
        ).fetchone()["c"]
    assert left == 0

    with pytest.raises(ValueError):
        notes.delete_board(first.id)


def test_search_matches_plain_text_not_markup(notes: NoteService) -> None:
    board = notes.list_boards()[0]
    note = notes.create_note(board.id)
    notes.set_content(
        note.id,
        html="<p><span style=\"color:#ff0000\">Ahmet Bey'i ara</span></p>",
        text="Ahmet Bey'i ara",
    )
    assert [n.id for n in notes.search("Ahmet")] == [note.id]
    # The markup itself is not searchable content.
    assert notes.search("span") == []


def test_notes_never_reach_the_reminder_tables(notes: NoteService, migrated_db) -> None:
    board = notes.list_boards()[0]
    notes.create_note(board.id)
    with migrated_db.session() as connection:
        reminders = connection.execute(
            "SELECT COUNT(*) c FROM manual_reminders"
        ).fetchone()["c"]
        inbox = connection.execute(
            "SELECT COUNT(*) c FROM app_notifications"
        ).fetchone()["c"]
    assert reminders == 0
    assert inbox == 0


def test_snap_rounds_onto_the_grid() -> None:
    assert snap(0) == 0
    assert snap(11) == 8
    assert snap(13) == 16
    assert snap(13, enabled=False) == 13
