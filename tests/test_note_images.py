"""Pictures pasted onto sticky notes.

A screenshot is stored as a file beside the database and referenced from the
note's HTML through a private scheme, so the markup never carries an absolute
path and the database never carries megabytes of base64.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QImage

from services.note_images import MAX_WIDTH, SCHEME, NoteImageStore


@pytest.fixture()
def store(tmp_path) -> NoteImageStore:
    return NoteImageStore(root=tmp_path / "note_images")


def _image(width: int = 400, height: int = 200, colour: str = "#3b6ea5") -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    return image


def test_saving_writes_a_png_and_returns_its_name(qt_app, store) -> None:
    name = store.save(_image())
    assert name.endswith(".png")
    path = store.root / name
    assert path.is_file()
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_same_picture_is_stored_once(qt_app, store) -> None:
    """The name is the digest, so pasting a screenshot twice costs one file."""
    first = store.save(_image())
    second = store.save(_image())
    assert first == second
    assert len(list(store.root.glob("*.png"))) == 1


def test_a_huge_screenshot_is_scaled_down(qt_app, store) -> None:
    name = store.save(_image(width=MAX_WIDTH * 2, height=MAX_WIDTH))
    stored = QImage(str(store.root / name))
    assert stored.width() == MAX_WIDTH


def test_a_null_image_is_refused(qt_app, store) -> None:
    with pytest.raises(ValueError):
        store.save(QImage())


def test_a_name_cannot_escape_the_folder(qt_app, store) -> None:
    """The name comes out of stored HTML, so it is not trusted."""
    store.root.mkdir(parents=True, exist_ok=True)
    for attempt in ("../gizli.png", r"..\gizli.png"):
        with pytest.raises(ValueError):
            store.path_for(attempt)


def test_references_are_read_out_of_the_markup() -> None:
    html = (
        f"<p><img src='{SCHEME}:aaaa1111.png'/></p>"
        f"<p><img src='{SCHEME}:bbbb2222.png'/></p>"
    )
    assert NoteImageStore.references(html) == {"aaaa1111.png", "bbbb2222.png"}
    assert NoteImageStore.references("") == set()
    assert NoteImageStore.references("<p>düz metin</p>") == set()


def test_pruning_keeps_what_is_still_referenced(qt_app, store) -> None:
    kept = store.save(_image(colour="#111111"))
    dropped = store.save(_image(colour="#222222"))
    assert store.prune({kept}) == 1
    assert (store.root / kept).exists()
    assert not (store.root / dropped).exists()


# ------------------------------------------------------------------ pasting
def test_pasting_an_image_stores_a_file_and_references_it(qt_app, tmp_path) -> None:
    from PySide6.QtCore import QMimeData

    from ui.notes.note_item import NoteBody
    from ui.theme import apply_theme

    apply_theme(qt_app)
    store = NoteImageStore(root=tmp_path / "images")
    body = NoteBody(store=store)
    body.resize(300, 200)
    body.show()
    qt_app.processEvents()

    mime = QMimeData()
    mime.setImageData(_image())
    assert body.canInsertFromMimeData(mime)
    body.insertFromMimeData(mime)
    qt_app.processEvents()

    html = body.toHtml()
    names = NoteImageStore.references(html)
    assert len(names) == 1
    assert (store.root / next(iter(names))).is_file()
    # The markup must not carry a path from this machine.
    assert str(tmp_path) not in html
    body.close()


def test_a_reloaded_note_finds_its_picture(qt_app, tmp_path) -> None:
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QTextDocument

    from ui.notes.note_item import NoteBody
    from ui.theme import apply_theme

    apply_theme(qt_app)
    store = NoteImageStore(root=tmp_path / "images")
    body = NoteBody(store=store)
    body.resize(300, 200)
    body.show()
    mime = QMimeData()
    mime.setImageData(_image())
    body.insertFromMimeData(mime)
    qt_app.processEvents()
    html = body.toHtml()
    name = next(iter(NoteImageStore.references(html)))
    body.close()

    reopened = NoteBody(store=store)
    reopened.setHtml(html)
    reopened.resize(300, 200)
    reopened.show()
    qt_app.processEvents()
    resource = reopened.document().resource(
        QTextDocument.ResourceType.ImageResource, QUrl(f"{SCHEME}:{name}")
    )
    assert not QImage(resource).isNull()
    reopened.close()


def test_a_missing_picture_does_not_crash_the_note(qt_app, tmp_path) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QTextDocument

    from ui.notes.note_item import NoteBody
    from ui.theme import apply_theme

    apply_theme(qt_app)
    store = NoteImageStore(root=tmp_path / "images")
    body = NoteBody(store=store)
    body.setHtml(f"<p><img src='{SCHEME}:yok.png'/></p>")
    body.resize(300, 200)
    body.show()
    qt_app.processEvents()
    resource = body.document().resource(
        QTextDocument.ResourceType.ImageResource, QUrl(f"{SCHEME}:yok.png")
    )
    assert QImage(resource).isNull()
    body.close()


# ------------------------------------------------------------------ printing
def test_printing_a_board_draws_the_whole_note(qt_app, migrated_db) -> None:
    """Regression: the board PDF silently cut long notes off.

    `QGraphicsScene.render()` lays an embedded editor out for the target device
    and then clips it to a fraction of its height, so a five-line note printed
    as one and a half lines. The text is drawn from the document instead.
    """
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter

    from services.note_service import NoteService
    from ui.pages.notes_page import NotesPage
    from ui.theme import apply_theme

    apply_theme(qt_app)
    service = NoteService(migrated_db)
    board = service.list_boards()[0]
    note_id = service.repository.create_note(
        board.id, x=20, y=20, width=300, height=240, colour="yellow"
    )
    service.set_content(
        note_id,
        html="<p>bir</p><p>iki</p><p>üç</p><p>dört</p><p>beş</p>",
        text="bir iki üç dört beş",
    )
    page = NotesPage(service)
    page.resize(900, 500)
    page.show()
    for _ in range(4):
        qt_app.processEvents()

    canvas = QImage(700, 400, QImage.Format.Format_ARGB32)
    canvas.fill(QColor("white"))
    painter = QPainter(canvas)
    page.canvas.render_board(painter, QRectF(10, 10, 680, 380))
    painter.end()

    # Ink is dark; the paper is not. Count dark pixels in the lower half of the
    # note — the last lines land there, and they were missing before.
    def dark_pixels(top: int, bottom: int) -> int:
        found = 0
        for y in range(top, bottom, 2):
            for x in range(20, 500, 2):
                if canvas.pixelColor(x, y).lightness() < 120:
                    found += 1
        return found

    assert dark_pixels(60, 180) > 0, "ilk satırlar da çizilmemiş"
    assert dark_pixels(240, 380) > 0, "son satırlar kırpılmış"
    page.close()
