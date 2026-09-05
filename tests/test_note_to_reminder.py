"""Turning a scribble into a tracked reminder.

The notes canvas is deliberately not part of the obligation system, so this is
the one bridge between them — and it must not invent anything the note did not
say.
"""

from __future__ import annotations

from datetime import date

import pytest

from services.company_service import CompanyService
from services.date_phrases import extract_date
from services.note_service import NoteService
from services.reminder_service import ReminderService
from ui.pages.notes_page import NotesPage
from ui.theme import apply_theme


@pytest.fixture()
def page(qt_app, migrated_db):
    apply_theme(qt_app)
    widget = NotesPage(NoteService(migrated_db))
    widget.resize(900, 500)
    widget.show()
    for _ in range(3):
        qt_app.processEvents()
    yield widget
    widget.close()


def _note_with(page, qt_app, text: str) -> int:
    service = page.service
    board = service.list_boards()[0]
    note_id = service.repository.create_note(board.id, x=20, y=20)
    page.refresh()
    for _ in range(3):
        qt_app.processEvents()
    page.canvas.item(note_id).body.setPlainText(text)
    for _ in range(2):
        qt_app.processEvents()
    return note_id


def test_the_first_line_becomes_the_title(page, qt_app) -> None:
    captured: list[dict] = []
    page.reminder_requested.connect(captured.append)

    note_id = _note_with(page, qt_app, "Kasko yenileme\nAcente: Ahmet Bey\n0212 000 00 00")
    page._reminder_from_note(note_id)

    assert captured, "sinyal gelmedi"
    prefill = captured[0]
    assert prefill["title"] == "Kasko yenileme"
    assert prefill["notes"] == "Acente: Ahmet Bey\n0212 000 00 00"


def test_a_date_in_the_note_is_offered(page, qt_app) -> None:
    captured: list[dict] = []
    page.reminder_requested.connect(captured.append)

    note_id = _note_with(page, qt_app, "Kasko yenileme 15 ekim 2027")
    page._reminder_from_note(note_id)

    prefill = captured[0]
    assert prefill["due_date"] == date(2027, 10, 15)
    # The words the date came from are carried through so the dialog can echo
    # them; a wrong read has to be visible before saving.
    assert prefill["date_phrase"] == "15 ekim 2027"


def test_a_note_without_a_date_offers_none(page, qt_app) -> None:
    captured: list[dict] = []
    page.reminder_requested.connect(captured.append)

    note_id = _note_with(page, qt_app, "Fatura listesi eksik, 15 kalem")
    page._reminder_from_note(note_id)

    assert "due_date" not in captured[0]


def test_a_single_line_note_carries_no_body(page, qt_app) -> None:
    captured: list[dict] = []
    page.reminder_requested.connect(captured.append)

    note_id = _note_with(page, qt_app, "Ahmet Bey'i ara")
    page._reminder_from_note(note_id)

    assert captured[0]["title"] == "Ahmet Bey'i ara"
    assert "notes" not in captured[0]


def test_an_empty_note_is_refused(page, qt_app, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[1]))
    )
    captured: list[dict] = []
    page.reminder_requested.connect(captured.append)

    note_id = _note_with(page, qt_app, "   ")
    page._reminder_from_note(note_id)

    assert captured == []
    assert shown, "boş notta uyarı verilmedi"


def test_a_very_long_first_line_is_trimmed(page, qt_app) -> None:
    captured: list[dict] = []
    page.reminder_requested.connect(captured.append)

    note_id = _note_with(page, qt_app, "x" * 400)
    page._reminder_from_note(note_id)

    assert len(captured[0]["title"]) <= 120


# ------------------------------------------------------------------ dialog
def test_the_dialog_shows_which_words_gave_the_date(qt_app, migrated_db) -> None:
    from ui.dialogs.reminder_dialog import ReminderDialog

    apply_theme(qt_app)
    found = extract_date("Kasko yenileme 15 ekim 2027")
    assert found is not None
    due, phrase = found

    dialog = ReminderDialog(
        ReminderService(migrated_db),
        CompanyService(migrated_db),
        prefill={"title": "Kasko yenileme", "due_date": due, "date_phrase": phrase},
    )
    assert dialog.date_edit.date().toPython() == due
    assert phrase in dialog.quick_date_hint.text()
    assert dialog.title_edit.text() == "Kasko yenileme"
    dialog.close()
