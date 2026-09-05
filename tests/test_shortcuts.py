"""Keyboard access for the daily actions.

A desktop tool that can only be driven with the mouse feels unfinished, and
these bindings are the conventional Windows ones rather than invented keys.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QKeySequence, QShortcut

from services.company_service import CompanyService
from services.note_service import NoteService
from services.official_update_service import OfficialUpdateService
from services.reminder_service import ReminderService
from services.settings_service import SettingsService
from ui.main_window import PAGE_ORDER, MainWindow
from ui.theme import apply_theme


@pytest.fixture()
def window(qt_app, seeded_db):
    apply_theme(qt_app)
    widget = MainWindow(
        ReminderService(seeded_db),
        CompanyService(seeded_db),
        SettingsService(seeded_db),
        OfficialUpdateService(seeded_db),
        None,
        None,
        NoteService(seeded_db),
    )
    # Focus only moves inside a shown window.
    widget.show()
    qt_app.processEvents()
    yield widget
    widget.close()


def _bindings(widget) -> set[str]:
    return {s.key().toString() for s in widget.findChildren(QShortcut)}


def test_the_daily_actions_all_have_a_key(window) -> None:
    keys = _bindings(window)
    for expected in ("Ctrl+K", "Ctrl+N", "Ctrl+F", "Ctrl+E", "F5", "Ctrl+Shift+R"):
        assert QKeySequence(expected).toString() in keys, expected


def test_every_page_has_a_number_key(window) -> None:
    keys = _bindings(window)
    pages = [key for key in PAGE_ORDER if key in window._pages]
    for index in range(1, len(pages) + 1):
        assert QKeySequence(f"Ctrl+{index}").toString() in keys, index


def test_number_keys_switch_to_the_right_page(window) -> None:
    pages = [key for key in PAGE_ORDER if key in window._pages]
    for index, key in enumerate(pages, start=1):
        window.show_page(key)
        assert window.stack.currentWidget() is window._pages[key], key


def test_no_binding_is_used_twice(window) -> None:
    """Two shortcuts on one key make both unreliable."""
    keys = [s.key().toString() for s in window.findChildren(QShortcut)]
    assert len(keys) == len(set(keys)), sorted(keys)


def test_ctrl_f_lands_in_the_filter_box(window) -> None:
    window.show_page("reminders")
    window.focus_filter()
    assert window.focusWidget() is window.reminders_page.search_edit


def test_f5_refreshes_without_raising(window) -> None:
    for key in [k for k in PAGE_ORDER if k in window._pages]:
        window.show_page(key)
        window.refresh_current()


def test_ctrl_n_creates_on_the_page_that_supports_it(window, monkeypatch) -> None:
    """Ctrl+N means "new thing here", so it must reach the page's own action."""
    called: list[str] = []
    monkeypatch.setattr(
        window.reminders_page, "create_reminder", lambda *a, **k: called.append("reminder")
    )
    window.show_page("reminders")
    window.new_record()
    assert called == ["reminder"]


def test_settings_page_has_no_new_record_action(window) -> None:
    """A page with nothing to create must not raise on Ctrl+N."""
    window.show_page("settings")
    window.new_record()
