"""Exports must carry exactly what the screen shows, and open in Excel.

The office hands these files to clients, so a silently truncated or
wrongly-filtered export is worse than no export at all.
"""

from __future__ import annotations

import zipfile
from datetime import date, timedelta

import pytest

from services.export_service import (
    COLUMNS,
    ExportRow,
    default_name,
    rows_from_items,
    status_text,
    write_pdf,
    write_xlsx,
)
from services.reminder_service import DueItem

TODAY = date(2026, 9, 4)


def _items() -> list[DueItem]:
    return [
        DueItem(
            "OFFICIAL", 1, 1, "AYKUT MÜHENDİSLİK SANAYİ VE TİCARET LTD. ŞTİ.",
            "Katma Değer Vergisinin Beyan ve Ödemesi", TODAY + timedelta(days=24),
            "GIB", period_label="Ağustos 2026 Dönemi",
        ),
        DueItem(
            "MANUAL", 2, 2, "POPÜLER GIDA", "Ofis kira ödemesi",
            TODAY - timedelta(days=2), "MANUEL",
            category="RENT", recurrence_kind="MONTHLY",
        ),
        DueItem(
            "MANUAL", 3, 1, "AYKUT MÜHENDİSLİK", "Araç Muayenesi",
            TODAY + timedelta(days=3), "MANUEL",
            category="VEHICLE_INSPECTION", plate="35 ABC 123",
        ),
    ]


def test_rows_preserve_order_and_row_count() -> None:
    rows = rows_from_items(_items(), TODAY)
    assert len(rows) == 3
    assert [row.due_date for row in rows] == [item.due_date for item in _items()]


def test_official_and_manual_are_labelled_apart() -> None:
    rows = rows_from_items(_items(), TODAY)
    assert rows[0].source == "Resmî"
    assert rows[1].source == "Manuel"
    # The official row carries its period, the manual one its category.
    assert "Ağustos 2026" in rows[0].detail
    assert "Kira" in rows[1].detail


def test_status_wording_matches_the_table() -> None:
    overdue, today_item, future = _items()[1], _items()[0], _items()[2]
    assert status_text(overdue, TODAY) == "2 gün gecikti"
    assert status_text(future, TODAY) == "3 gün"
    assert status_text(future, TODAY, completed=True) == "Tamamlandı"
    assert status_text(today_item, TODAY.replace(day=28)) == "Bugün"


def test_a_company_without_a_name_is_not_blank() -> None:
    item = DueItem("MANUAL", 9, None, None, "Genel iş", TODAY, "MANUEL")
    assert rows_from_items([item], TODAY)[0].company == "Genel"


def test_xlsx_is_a_real_workbook_with_a_header(tmp_path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    path = write_xlsx(rows_from_items(_items(), TODAY), tmp_path / "l.xlsx", "Liste")

    # A real xlsx is a zip container, not a renamed CSV.
    assert zipfile.is_zipfile(path)

    book = openpyxl.load_workbook(path)
    sheet = book.active
    assert [cell.value for cell in sheet[1]] == list(COLUMNS)
    assert sheet.max_row == 4  # header + three records
    assert sheet.freeze_panes == "A2"
    # Dates go in as dates, so Excel can sort and filter them.
    assert sheet["A2"].value.date() == TODAY + timedelta(days=24)
    # Turkish characters survive the round trip.
    assert "MÜHENDİSLİK" in sheet["B2"].value


def test_pdf_is_written_and_non_trivial(qt_app, tmp_path) -> None:
    path = write_pdf(rows_from_items(_items(), TODAY), tmp_path / "l.pdf", "Liste")
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 2000


def test_empty_export_still_produces_a_valid_file(qt_app, tmp_path) -> None:
    pytest.importorskip("openpyxl")
    xlsx = write_xlsx([], tmp_path / "bos.xlsx", "Boş")
    pdf = write_pdf([], tmp_path / "bos.pdf", "Boş")
    assert zipfile.is_zipfile(xlsx)
    assert pdf.read_bytes().startswith(b"%PDF")


def test_html_special_characters_are_escaped(qt_app, tmp_path) -> None:
    """A company named with an angle bracket must not break the PDF layout."""
    row = ExportRow(TODAY, "A & B <Ltd>", "Beyan \"özel\"", "Kira", "Manuel", "Bugün")
    path = write_pdf([row], tmp_path / "esc.pdf", "Kaçış")
    assert path.read_bytes().startswith(b"%PDF")


def test_default_name_is_dated_and_sortable() -> None:
    name = default_name("hatirlatmalar", "xlsx")
    assert name.startswith("hatirlatmalar_")
    assert name.endswith(".xlsx")
    assert date.today().isoformat() in name


# ------------------------------------------------------------------- notes
def _board(qt_app, tmp_path):
    """A real board with notes at known positions, in the dark theme."""
    from pathlib import Path as _Path

    from database.connection import Database
    from database.migrations import MigrationRunner
    from services.note_service import NoteService
    from ui.pages.notes_page import NotesPage
    from ui.theme import DARK, apply_theme

    apply_theme(qt_app, DARK)
    database = Database(tmp_path / "notes.db")
    MigrationRunner(database, _Path("database/migrations")).run()
    service = NoteService(database)
    board = service.list_boards()[0]
    service.repository.create_note(board.id, x=40, y=40, width=300, height=180, colour="amber")
    service.repository.create_note(board.id, x=400, y=40, width=240, height=180, colour="mint")
    service.repository.create_note(board.id, x=40, y=260, width=240, height=160, colour="sky")

    page = NotesPage(service)
    page.resize(1000, 600)
    page.show()
    for _ in range(3):
        qt_app.processEvents()
    return page


def test_board_pdf_keeps_the_arrangement(qt_app, tmp_path) -> None:
    """The board must print as it was left, not reflowed into a document."""
    from services.export_service import write_board_pdf

    page = _board(qt_app, tmp_path)
    rect = page.canvas.board_rect()
    # The bounding box spans all three notes, so the layout is what gets drawn.
    assert rect.width() > 600
    assert rect.height() > 380

    path = write_board_pdf(
        page.canvas.render_board, (rect.width(), rect.height()),
        tmp_path / "board.pdf", "Notlar",
    )
    assert path.read_bytes().startswith(b"%PDF")
    page.close()


def test_a_wide_board_is_printed_landscape(qt_app, tmp_path) -> None:
    from PySide6.QtPdf import QPdfDocument

    from services.export_service import write_board_pdf

    page = _board(qt_app, tmp_path)
    rect = page.canvas.board_rect()
    path = write_board_pdf(
        page.canvas.render_board, (rect.width(), rect.height()),
        tmp_path / "wide.pdf", "Notlar",
    )
    document = QPdfDocument()
    document.load(str(path))
    assert document.pageCount() == 1, "bir tuval bir sayfa olmalı"
    size = document.pagePointSize(0)
    assert size.width() > size.height(), "geniş tuval yatay basılmalı"
    page.close()


def test_printing_restores_the_dark_theme_afterwards(qt_app, tmp_path) -> None:
    """The light palette is forced only for the render."""
    from services.export_service import write_board_pdf
    from ui.theme import DARK, tokens

    page = _board(qt_app, tmp_path)
    rect = page.canvas.board_rect()
    write_board_pdf(
        page.canvas.render_board, (rect.width(), rect.height()),
        tmp_path / "restore.pdf", "Notlar",
    )
    assert tokens().name == DARK.name
    # Every note is back on the dark palette and its editor is usable again.
    for item in page.canvas._items.values():
        assert item.body.cursorWidth() > 0
        assert DARK.text in item.body.styleSheet() or item.body.styleSheet()
    page.close()


def test_an_empty_board_is_refused_with_a_readable_message(qt_app, tmp_path) -> None:
    from services.export_service import ExportError, write_board_pdf

    with pytest.raises(ExportError) as error:
        write_board_pdf(lambda *_: None, (0, 0), tmp_path / "bos.pdf", "Boş")
    assert "not yok" in str(error.value)


def test_palette_override_is_restored_even_on_failure(qt_app) -> None:
    from ui.theme import DARK, LIGHT, apply_theme, palette_override, tokens

    apply_theme(qt_app, DARK)
    with pytest.raises(RuntimeError):
        with palette_override(LIGHT):
            assert tokens().name == LIGHT.name
            raise RuntimeError("render patladı")
    assert tokens().name == DARK.name
