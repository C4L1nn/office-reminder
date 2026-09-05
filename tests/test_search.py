"""One box over every kind of record the office keeps.

The point of the global search is that the user does not know which screen a
record is on, so a hit must carry enough context to be recognised, and one
broken kind must not blank the whole result list.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.company_service import CompanyService
from services.note_service import NoteService
from services.reminder_service import ReminderService
from services.search_service import (
    COMPANY,
    MIN_TERM,
    NOTE,
    REMINDER,
    VEHICLE,
    SearchService,
)


@pytest.fixture()
def data(migrated_db):
    companies = CompanyService(migrated_db)
    reminders = ReminderService(migrated_db)
    notes = NoteService(migrated_db)

    company_id = companies.create(name="EFES POPÜLER GIDA LTD. ŞTİ.", tax_number="9876543210")
    companies.create_vehicle(
        company_id=company_id, plate="35 BHG 163", make="Ford", model="Transit"
    )
    reminders.create_manual(
        title="Ofis kira ödemesi",
        due_date=date.today() + timedelta(days=5),
        company_id=company_id,
        category="RENT",
    )
    board = notes.list_boards()[0]
    note_id = notes.repository.create_note(board.id, x=0, y=0)
    notes.set_content(note_id, html="<p>Ahmet Bey'i ara</p>", text="Ahmet Bey'i ara")

    return SearchService(migrated_db), company_id, board.id


def test_short_terms_are_ignored(data) -> None:
    service = data[0]
    assert service.search("") == []
    assert service.search("a" * (MIN_TERM - 1)) == []


def test_each_kind_is_findable(data) -> None:
    service = data[0]
    assert COMPANY in {h.kind for h in service.search("efes")}
    assert [h.kind for h in service.search("BHG")] == [VEHICLE]
    assert [h.kind for h in service.search("kira")] == [REMINDER]
    assert [h.kind for h in service.search("ahmet")] == [NOTE]


def test_a_company_search_also_surfaces_its_vehicles(data) -> None:
    """Deliberate: a vehicle is matched by its company name too, so looking up
    a client shows the cars registered to it."""
    kinds = [h.kind for h in data[0].search("efes")]
    assert kinds == [COMPANY, VEHICLE]


def test_search_is_case_insensitive(data) -> None:
    service = data[0]
    assert service.search("EFES") and service.search("efes")
    assert len(service.search("EfEs")) == len(service.search("efes"))


def test_a_hit_carries_what_the_window_needs_to_reveal_it(data) -> None:
    service, company_id, board_id = data

    company = service.search("efes")[0]
    assert company.record_id == company_id
    assert "9876543210" in company.subtitle

    note = service.search("ahmet")[0]
    # The note's board, so the window can switch to the right page.
    assert note.context == str(board_id)
    assert "Ahmet" in note.title

    reminder = service.search("kira")[0]
    assert reminder.context == "Ofis kira ödemesi"


def test_note_excerpt_is_windowed_around_the_match(migrated_db) -> None:
    from services.search_service import _excerpt

    text = "bir " * 40 + "ANAHTAR" + " son" * 40
    piece = _excerpt(text, "ANAHTAR", width=40)
    assert "ANAHTAR" in piece
    assert len(piece) <= 44
    assert piece.startswith("…")


def test_one_failing_kind_does_not_blank_the_others(data, monkeypatch) -> None:
    """A broken table must cost that kind's hits, not every hit."""
    service = data[0]

    def boom(_term):
        raise RuntimeError("tablo okunamadı")

    monkeypatch.setattr(service, "_notes", boom)
    hits = service.search("ahmet")
    assert [h.kind for h in hits] == []

    # The kinds that still work keep returning their hits.
    assert COMPANY in {h.kind for h in service.search("efes")}


def test_results_are_capped_per_kind(migrated_db) -> None:
    from services.search_service import PER_KIND

    companies = CompanyService(migrated_db)
    for index in range(PER_KIND + 4):
        companies.create(name=f"ORTAK TEST {index} LTD.", tax_number=f"111111111{index}")
    hits = SearchService(migrated_db).search("ORTAK TEST")
    assert len([h for h in hits if h.kind == COMPANY]) == PER_KIND
