"""Typing a date instead of clicking one out of a calendar.

The rule that matters most is the refusal: anything the parser is not sure
about must come back as None, because a date quietly landing in the wrong
month is worse than no date at all.
"""

from __future__ import annotations

from datetime import date

import pytest

from services.date_phrases import describe, parse_date_phrase

#: A Friday, so weekday arithmetic has something to cross.
TODAY = date(2026, 9, 4)


def parse(text: str):
    return parse_date_phrase(text, TODAY)


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("bugün", date(2026, 9, 4)),
        ("yarın", date(2026, 9, 5)),
        ("yarin", date(2026, 9, 5)),
        ("öbür gün", date(2026, 9, 6)),
        ("dün", date(2026, 9, 3)),
    ],
)
def test_landmarks(phrase, expected) -> None:
    assert parse(phrase) == expected


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("3 gün sonra", date(2026, 9, 7)),
        ("üç gün sonra", date(2026, 9, 7)),
        ("uc gun sonra", date(2026, 9, 7)),
        ("2 hafta sonra", date(2026, 9, 18)),
        ("iki hafta sonra", date(2026, 9, 18)),
        ("1 ay sonra", date(2026, 10, 4)),
        ("6 ay sonra", date(2027, 3, 4)),
        ("1 yıl sonra", date(2027, 9, 4)),
    ],
)
def test_relative_offsets(phrase, expected) -> None:
    assert parse(phrase) == expected


def test_month_arithmetic_clamps_short_months() -> None:
    """31 Ocak + 1 ay is 28 Şubat, not an invalid date."""
    assert parse_date_phrase("1 ay sonra", date(2026, 1, 31)) == date(2026, 2, 28)
    assert parse_date_phrase("1 ay sonra", date(2028, 1, 31)) == date(2028, 2, 29)


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("ay sonu", date(2026, 9, 30)),
        ("ayın son günü", date(2026, 9, 30)),
        ("gelecek ay sonu", date(2026, 10, 31)),
        ("haftaya", date(2026, 9, 11)),
        ("gelecek ay", date(2026, 10, 4)),
    ],
)
def test_period_landmarks(phrase, expected) -> None:
    assert parse(phrase) == expected


def test_february_month_end_is_correct() -> None:
    assert parse_date_phrase("ay sonu", date(2026, 2, 10)) == date(2026, 2, 28)
    assert parse_date_phrase("ay sonu", date(2028, 2, 10)) == date(2028, 2, 29)


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("salı", date(2026, 9, 8)),
        ("sali", date(2026, 9, 8)),
        ("cuma", date(2026, 9, 11)),        # today is Friday: the *next* one
        ("gelecek salı", date(2026, 9, 15)),
        ("bu salı", date(2026, 9, 8)),
        ("perşembe", date(2026, 9, 10)),
    ],
)
def test_weekdays(phrase, expected) -> None:
    assert parse(phrase) == expected


def test_a_bare_weekday_never_means_today() -> None:
    """Typing today's weekday means the next one; today is already on screen."""
    assert parse("cuma") != TODAY


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("15 ekim", date(2026, 10, 15)),
        ("15 Ekim", date(2026, 10, 15)),
        ("15 EKİM", date(2026, 10, 15)),
        ("15 ekim 2027", date(2027, 10, 15)),
        ("1 mart", date(2027, 3, 1)),       # already past: next year
        ("29 şubat 2028", date(2028, 2, 29)),
        ("15.10", date(2026, 10, 15)),
        ("15.10.2027", date(2027, 10, 15)),
        ("15/10/2027", date(2027, 10, 15)),
        ("15.10.27", date(2027, 10, 15)),
    ],
)
def test_explicit_dates(phrase, expected) -> None:
    assert parse(phrase) == expected


def test_a_bare_day_and_month_rolls_to_next_year_when_past() -> None:
    assert parse("01.03") == date(2027, 3, 1)
    assert parse("01.12") == date(2026, 12, 1)


@pytest.mark.parametrize(
    "phrase",
    [
        "",
        "   ",
        "saçma sapan",
        "filanca ayı",
        "32 ekim",
        "29 şubat 2027",   # not a leap year
        "15 xyz",
        "45.99",
        "sonra",
        "gün sonra",
        "kırk iki gün sonra",   # not a number this parser knows
        "önceki salı",          # only forward-looking qualifiers are accepted
    ],
)
def test_anything_uncertain_is_refused(phrase) -> None:
    assert parse(phrase) is None


def test_whitespace_and_case_do_not_matter() -> None:
    assert parse("  YARIN  ") == parse("yarın")
    assert parse("3   GÜN   SONRA") == parse("3 gün sonra")


def test_describe_echoes_the_date_back_for_checking() -> None:
    """The user must be able to see what was understood."""
    assert describe(date(2026, 10, 15)) == "15 Ekim 2026 Per"
    assert describe(date(2026, 1, 1)) == "1 Ocak 2026 Per"


# --------------------------------------------------------------------- dialog
def test_the_dialog_fills_the_picker_from_a_phrase(qt_app, migrated_db) -> None:
    from services.company_service import CompanyService
    from services.reminder_service import ReminderService
    from ui.dialogs.reminder_dialog import ReminderDialog
    from ui.theme import apply_theme

    apply_theme(qt_app)
    dialog = ReminderDialog(ReminderService(migrated_db), CompanyService(migrated_db))
    dialog.quick_date_edit.setText("3 gün sonra")
    qt_app.processEvents()

    expected = parse_date_phrase("3 gün sonra")
    assert dialog.date_edit.date().toPython() == expected
    assert describe(expected) in dialog.quick_date_hint.text()
    dialog.close()


def test_an_unreadable_phrase_leaves_the_date_alone(qt_app, migrated_db) -> None:
    """A phrase nobody can parse must not move the date the user already set."""
    from services.company_service import CompanyService
    from services.reminder_service import ReminderService
    from ui.dialogs.reminder_dialog import ReminderDialog
    from ui.theme import apply_theme

    apply_theme(qt_app)
    dialog = ReminderDialog(ReminderService(migrated_db), CompanyService(migrated_db))
    before = dialog.date_edit.date()

    dialog.quick_date_edit.setText("saçma sapan")
    qt_app.processEvents()

    assert dialog.date_edit.date() == before
    assert "Anlaşılamadı" in dialog.quick_date_hint.text()
    dialog.close()


def test_clearing_the_field_clears_the_hint(qt_app, migrated_db) -> None:
    from services.company_service import CompanyService
    from services.reminder_service import ReminderService
    from ui.dialogs.reminder_dialog import ReminderDialog
    from ui.theme import apply_theme

    apply_theme(qt_app)
    dialog = ReminderDialog(ReminderService(migrated_db), CompanyService(migrated_db))
    dialog.quick_date_edit.setText("yarın")
    qt_app.processEvents()
    assert dialog.quick_date_hint.text()

    dialog.quick_date_edit.setText("")
    qt_app.processEvents()
    assert dialog.quick_date_hint.text() == ""
    dialog.close()
