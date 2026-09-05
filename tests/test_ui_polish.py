"""The polish pass, pinned where it can regress silently."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from PySide6.QtWidgets import QListWidget

from ui.theme import DARK, LIGHT, apply_theme
from ui.widgets import DistributionStrip, EmptyState


def _ratio(a: str, b: str) -> float:
    def lum(value: str) -> float:
        value = value.lstrip("#")
        parts = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        parts = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]

    high, low = max(lum(a), lum(b)), min(lum(a), lum(b))
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_every_text_tone_meets_wcag_aa(palette) -> None:
    """4.5:1 for normal text. The captions and group headings use text_faint,
    which is the most-read secondary text in the app."""
    for tone in ("text", "text_muted", "text_faint", "danger", "warning", "success", "info"):
        for ground in ("surface", "surface_alt", "rail"):
            ratio = _ratio(getattr(palette, tone), getattr(palette, ground))
            assert ratio >= 4.5, f"{palette.name}: {tone}/{ground} = {ratio:.2f}"


def test_empty_state_body_gets_a_readable_measure(qt_app) -> None:
    """A centred layout collapsed the wrapping label to ~175px and cut the
    sentence in half."""
    apply_theme(qt_app)
    body = (
        "Takip edilecek ilk şirketi ekleyin; ardından tabi olduğu KDV, SGK ve "
        "diğer yükümlülükleri işaretleyin."
    )
    widget = EmptyState("Henüz şirket yok", body, "building", "Yeni Şirket")
    widget.resize(780, 320)
    widget.show()
    qt_app.processEvents()

    from PySide6.QtWidgets import QLabel

    target = next(lab for lab in widget.findChildren(QLabel) if lab.text().startswith("Takip"))
    assert target.width() >= 340, target.width()
    # Tall enough for every line the text needs at that width.
    assert target.height() >= target.heightForWidth(target.width())
    widget.close()


def test_distribution_strip_takes_one_bar_per_day(qt_app) -> None:
    apply_theme(qt_app)
    strip = DistributionStrip()
    today = date.today()
    counts = [(today + timedelta(days=n), n % 4) for n in range(40)]
    strip.set_counts(counts)
    # Never more than a month, however much it is handed.
    assert len(strip._counts) == DistributionStrip.DAYS
    strip.resize(600, 58)
    strip.show()
    qt_app.processEvents()
    assert strip._bar_width() > 1
    strip.close()


def test_distribution_strip_survives_an_empty_month(qt_app) -> None:
    apply_theme(qt_app)
    strip = DistributionStrip()
    strip.set_counts([])
    strip.resize(600, 58)
    strip.show()
    qt_app.processEvents()  # paintEvent must not divide by zero
    strip.close()


def test_empty_list_shows_a_hint_instead_of_a_blank_frame(qt_app) -> None:
    from ui.widgets import set_list_placeholder

    apply_theme(qt_app)
    listing = QListWidget()
    set_list_placeholder(listing, "Henüz şirket yok.")
    listing.resize(300, 400)
    listing.show()
    qt_app.processEvents()

    placeholder = set_list_placeholder.__globals__["_ListPlaceholder"]
    hint = listing.viewport().findChild(placeholder)
    assert hint is not None and hint.isVisible(), "boş listede ipucu görünmüyor"

    listing.addItem("Bir kayıt")
    qt_app.processEvents()
    assert not hint.isVisible(), "kayıt varken ipucu gizlenmeli"
    listing.close()


def test_notes_board_has_no_scrollbars_when_empty(qt_app, migrated_db) -> None:
    from services.note_service import NoteService
    from ui.pages.notes_page import NotesPage

    apply_theme(qt_app)
    page = NotesPage(NoteService(migrated_db))
    page.resize(900, 500)
    page.show()
    for _ in range(4):
        qt_app.processEvents()
    assert not page.canvas.horizontalScrollBar().isVisible()
    assert not page.canvas.verticalScrollBar().isVisible()
    page.close()


# ------------------------------------------------------------ visual language
def test_cards_are_separated_by_tone_not_by_an_outline(qt_app) -> None:
    """Every panel drawn as a box made the screen read as a wireframe.

    The card is lighter than the page behind it, and that is what separates
    them — so the two tones must stay distinguishable in both themes.
    """
    from ui.theme import DARK, LIGHT, build_stylesheet

    for palette in (DARK, LIGHT):
        sheet = build_stylesheet(palette)
        card_block = sheet.split("#Card, #StatCard {")[1].split("}")[0]
        assert "border: none" in card_block, palette.name
        assert palette.canvas != palette.surface, palette.name
        assert _ratio(palette.canvas, palette.surface) > 1.03, palette.name


def test_badges_are_filled_not_outlined(qt_app) -> None:
    from ui.theme import DARK, build_stylesheet

    block = build_stylesheet(DARK).split("#Badge {")[1].split("}")[0]
    assert "border: none" in block


def test_the_selected_nav_item_carries_an_accent_bar(qt_app) -> None:
    """The same accent-bar language the tables and lists already use."""
    from ui.theme import DARK, build_stylesheet

    sheet = build_stylesheet(DARK)
    block = sheet.split("#RailItem:checked {")[1].split("}")[0]
    assert f"border-left: 3px solid {DARK.accent}" in block
    # The unselected item reserves the same width so labels do not shift.
    base = sheet.split("#RailItem {")[1].split("}")[0]
    assert "border-left: 3px solid transparent" in base


def test_row_separators_are_drawn_inset_and_visible(qt_app) -> None:
    """A full-bleed rule boxes a dense table in; an invisible one loses the
    grid altogether. This checks the hairline is actually painted."""
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

    from ui.theme import LIGHT, apply_theme
    from ui.widgets import AccentRowDelegate

    apply_theme(qt_app, LIGHT)
    table = QTableWidget(3, 3)
    delegate = AccentRowDelegate(table)
    table.setItemDelegate(delegate)
    for row in range(3):
        for column in range(3):
            table.setItem(row, column, QTableWidgetItem("x"))
        table.setRowHeight(row, 38)
    table.resize(400, 200)
    table.show()
    qt_app.processEvents()

    image = table.grab().toImage()
    rule = LIGHT.border.lower()
    found = [
        y
        for y in range(40, image.height())
        if sum(
            image.pixelColor(x, y).name().lower() == rule for x in range(60, 340)
        )
        > 100
    ]
    assert found, "satır ayırıcısı çizilmemiş"
    # Inset: the first pixels of the row carry no rule.
    y = found[0]
    assert image.pixelColor(2, y).name().lower() != rule
    table.close()


def test_group_heading_rows_take_no_separator(qt_app) -> None:
    from PySide6.QtWidgets import QTableWidget

    from ui.widgets import AccentRowDelegate

    table = QTableWidget(2, 2)
    delegate = AccentRowDelegate(table)
    delegate.set_spanned_rows({0})
    assert 0 in delegate._spanned
    assert 1 not in delegate._spanned
    table.close()
