"""Qt draws its own dialog buttons, so they need Qt's own translation.

Without it a Turkish confirmation ends with English "Yes" and "No" buttons,
which is the first thing anyone notices in a delete or complete dialog.
"""

from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtWidgets import QMessageBox


def test_qt_ships_a_turkish_translation() -> None:
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    translator = QTranslator()
    assert translator.load("qtbase_tr", path), f"qtbase_tr.qm bulunamadı: {path}"


def test_standard_buttons_read_evet_and_hayir(qt_app) -> None:
    translator = QTranslator()
    translator.load("qtbase_tr", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    qt_app.installTranslator(translator)
    try:
        box = QMessageBox(
            QMessageBox.Icon.Question,
            "Başlık",
            "Gövde",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        # The ampersand marks the keyboard accelerator; the words are what matter.
        labels = {button.text().replace("&", "") for button in box.buttons()}
        assert labels == {"Evet", "Hayır"}
    finally:
        qt_app.removeTranslator(translator)


def test_the_application_installs_it_at_startup() -> None:
    """The wiring, not just the file: a translator that is not kept alive is
    dropped by Qt and the buttons silently revert to English."""
    import inspect

    from app.application import OfficeReminderApplication

    source = inspect.getsource(OfficeReminderApplication)
    assert "_install_turkish_translation" in source
    assert "self._translator" in source, "çevirmen referansı tutulmuyor"
