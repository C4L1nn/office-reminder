"""Dropping a file where it belongs.

A receipt arrives in Downloads and belongs on one reminder; opening a dialog
and browsing back to the folder it came from is the long way round.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QUrl
from PySide6.QtGui import QDropEvent, QImage, QColor
from PySide6.QtCore import Qt

from services.attachment_service import AttachmentService
from services.company_service import CompanyService
from services.reminder_service import ReminderService
from ui.pages.reminders_page import RemindersPage
from ui.theme import apply_theme


@pytest.fixture()
def page(qt_app, seeded_db):
    apply_theme(qt_app)
    companies = CompanyService(seeded_db)
    reminders = ReminderService(seeded_db)
    company_id = companies.create(name="BIRAK LTD.", tax_number="6666666666")
    reminders.create_manual(
        title="Kira sözleşmesi",
        due_date=date.today() + timedelta(days=6),
        company_id=company_id,
        category="CONTRACT",
    )
    widget = RemindersPage(reminders, companies)
    widget.refresh()
    widget.resize(1000, 500)
    widget.show()
    for _ in range(3):
        qt_app.processEvents()
    yield widget
    widget.close()


def _drop(page, row: int, paths) -> QDropEvent:
    """Build a drop event for one table row.

    A QDropEvent does not own its mime data, so the QMimeData is pinned to the
    event: letting it fall out of scope leaves the event holding a dangling
    pointer, and reading `mimeData().urls()` then fails.
    """
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    rect = page.table.visualRect(page.table.model().index(row, 0))
    event = QDropEvent(
        QPointF(rect.center()),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event._mime = mime
    return event


def test_a_file_dropped_on_a_row_is_attached(page, qt_app, tmp_path) -> None:
    pdf = tmp_path / "sozlesme.pdf"
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 300)

    row, item = next(iter(page._row_items.items()))
    page._drop_files(_drop(page, row, [pdf]))

    service = AttachmentService(page.reminder_service.database)
    attachments = service.list_for("MANUAL", item.source_id)
    assert len(attachments) == 1
    assert attachments[0].display_name == "sozlesme.pdf"


def test_several_files_all_land(page, qt_app, tmp_path) -> None:
    first = tmp_path / "bir.pdf"
    first.write_bytes(b"%PDF-1.4\n" + b"a" * 100)
    second = tmp_path / "iki.png"
    second.write_bytes(b"\x89PNG\r\n" + b"b" * 100)

    row, item = next(iter(page._row_items.items()))
    page._drop_files(_drop(page, row, [first, second]))

    service = AttachmentService(page.reminder_service.database)
    assert service.count_for("MANUAL", item.source_id) == 2


def test_a_refused_type_reports_and_attaches_nothing(page, qt_app, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    warned: list = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)))

    bad = tmp_path / "kurulum.exe"
    bad.write_bytes(b"MZ" + b"z" * 100)
    row, item = next(iter(page._row_items.items()))
    page._drop_files(_drop(page, row, [bad]))

    service = AttachmentService(page.reminder_service.database)
    assert service.count_for("MANUAL", item.source_id) == 0
    assert warned, "reddedilen dosya için uyarı verilmedi"


def test_official_rows_do_not_take_files(page) -> None:
    """A GİB date is not ours to file paperwork against."""

    class Fake:
        source_kind = "OFFICIAL"
        source_id = 1

    row = next(iter(page._row_items))
    page._row_items[row] = Fake()
    rect = page.table.visualRect(page.table.model().index(row, 0))
    assert page._row_at(rect.center()) is None


def test_a_heading_row_takes_nothing(page) -> None:
    headings = [r for r in range(page.table.rowCount()) if r not in page._row_items]
    assert headings
    rect = page.table.visualRect(page.table.model().index(headings[0], 0))
    assert page._row_at(rect.center()) is None


# ------------------------------------------------------------------- notes
def test_an_image_file_dropped_on_a_note_becomes_a_picture(qt_app, tmp_path) -> None:
    from services.note_images import NoteImageStore
    from ui.notes.note_item import NoteBody

    apply_theme(qt_app)
    picture = tmp_path / "ekran.png"
    image = QImage(300, 150, QImage.Format.Format_RGB32)
    image.fill(QColor("#3b6ea5"))
    assert image.save(str(picture))

    store = NoteImageStore(root=tmp_path / "store")
    body = NoteBody(store=store)
    body.resize(320, 220)
    body.show()
    qt_app.processEvents()

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(picture))])
    assert body.canInsertFromMimeData(mime)
    body.insertFromMimeData(mime)
    qt_app.processEvents()

    assert NoteImageStore.references(body.toHtml())
    body.close()


def test_a_non_image_file_is_left_to_qt(qt_app, tmp_path) -> None:
    from services.note_images import NoteImageStore
    from ui.notes.note_item import NoteBody

    apply_theme(qt_app)
    document = tmp_path / "belge.pdf"
    document.write_bytes(b"%PDF-1.4\n")

    store = NoteImageStore(root=tmp_path / "store")
    body = NoteBody(store=store)
    body.resize(320, 220)
    body.show()
    qt_app.processEvents()

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(document))])
    body.insertFromMimeData(mime)
    qt_app.processEvents()

    assert not NoteImageStore.references(body.toHtml())
    body.close()
