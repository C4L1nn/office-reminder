"""Ctrl+Shift+V: a line from an e-mail becomes a reminder.

A due date arrives as a sentence far more often than as a form. Nothing is
saved without the user pressing save, so a bad read costs a glance rather than
a wrong record.
"""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from services.company_service import CompanyService
from services.note_service import NoteService
from services.official_update_service import OfficialUpdateService
from services.reminder_service import ReminderService
from services.settings_service import SettingsService
from ui.main_window import MainWindow
from ui.theme import apply_theme


@pytest.fixture()
def window(qt_app, seeded_db, monkeypatch):
    apply_theme(qt_app)
    opened: list[dict] = []

    widget = MainWindow(
        ReminderService(seeded_db),
        CompanyService(seeded_db),
        SettingsService(seeded_db),
        OfficialUpdateService(seeded_db),
        None,
        None,
        NoteService(seeded_db),
    )
    # The dialog is not the thing under test; capture what it would be given.
    monkeypatch.setattr(
        widget.reminders_page,
        "create_reminder",
        lambda **kwargs: opened.append(kwargs.get("prefill") or {}),
    )
    widget.opened = opened
    yield widget
    widget.close()


def test_a_pasted_line_becomes_the_title(window, qt_app) -> None:
    QApplication.clipboard().setText("Kasko yenileme")
    window.reminder_from_clipboard()
    assert window.opened == [{"title": "Kasko yenileme"}]


def test_a_date_in_the_text_is_offered(window, qt_app) -> None:
    QApplication.clipboard().setText("Kasko yenileme 15 ekim 2027 son gün")
    window.reminder_from_clipboard()

    prefill = window.opened[0]
    assert prefill["due_date"] == date(2027, 10, 15)
    assert prefill["date_phrase"] == "15 ekim 2027"


def test_extra_lines_become_the_note_body(window, qt_app) -> None:
    QApplication.clipboard().setText("Kira sözleşmesi\nEv sahibi: Ahmet Bey\n0212 000 00 00")
    window.reminder_from_clipboard()

    prefill = window.opened[0]
    assert prefill["title"] == "Kira sözleşmesi"
    assert prefill["notes"] == "Ev sahibi: Ahmet Bey\n0212 000 00 00"


def test_text_without_a_date_offers_none(window, qt_app) -> None:
    QApplication.clipboard().setText("Fatura listesi 15 kalem eksik")
    window.reminder_from_clipboard()
    assert "due_date" not in window.opened[0]


def test_an_empty_clipboard_opens_nothing(window, qt_app, monkeypatch) -> None:
    shown: list = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a))
    )
    QApplication.clipboard().setText("   \n  ")
    window.reminder_from_clipboard()

    assert window.opened == []
    assert shown, "boş panoda bilgi verilmedi"


def test_a_very_long_line_is_trimmed(window, qt_app) -> None:
    QApplication.clipboard().setText("y" * 500)
    window.reminder_from_clipboard()
    assert len(window.opened[0]["title"]) <= 120


def test_the_shortcut_is_registered(window) -> None:
    from PySide6.QtGui import QKeySequence, QShortcut

    keys = {s.key().toString() for s in window.findChildren(QShortcut)}
    assert QKeySequence("Ctrl+Shift+V").toString() in keys
