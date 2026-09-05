"""One search box over everything the office keeps here.

Each screen has its own filter, which is fine once you know where a record
lives. This is for when you do not: you remember a plate, half a company name
or a phrase from a note, and want to get to it without guessing the screen.

The service only finds things. Deciding what to show when a hit is picked
belongs to the window, not here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from database.connection import Database
from database.repositories.companies import CompanyRepository
from database.repositories.notes import NotesRepository
from database.repositories.reminders import ReminderRepository
from database.repositories.vehicles import VehicleRepository
from services.formatting import short_date

logger = logging.getLogger("office_reminder.search")

#: Below this a search matches almost everything and the list is noise.
MIN_TERM = 2
#: Per-kind cap, so one crowded kind cannot push the others off the list.
PER_KIND = 6

COMPANY = "company"
VEHICLE = "vehicle"
REMINDER = "reminder"
NOTE = "note"

KIND_LABELS = {
    COMPANY: "Şirket",
    VEHICLE: "Araç",
    REMINDER: "Hatırlatma",
    NOTE: "Not",
}
KIND_ICONS = {
    COMPANY: "building",
    VEHICLE: "car",
    REMINDER: "calendar",
    NOTE: "note",
}
#: The order hits are listed in: the things people look up most, first.
KIND_ORDER = (COMPANY, VEHICLE, REMINDER, NOTE)


@dataclass(slots=True, frozen=True)
class SearchHit:
    kind: str
    record_id: int
    title: str
    subtitle: str
    #: Extra identifier the window needs to reveal the record, e.g. a note's
    #: board or a reminder's title.
    context: str = ""

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def icon(self) -> str:
        return KIND_ICONS.get(self.kind, "search")


def _excerpt(text: str, term: str, width: int = 70) -> str:
    """A window of the note around the match, so the hit explains itself."""
    flat = " ".join((text or "").split())
    if not flat:
        return ""
    position = flat.casefold().find(term.casefold())
    if position < 0:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, position - width // 3)
    end = min(len(flat), start + width)
    piece = flat[start:end]
    return ("…" if start else "") + piece + ("…" if end < len(flat) else "")


class SearchService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.companies = CompanyRepository(database)
        self.vehicles = VehicleRepository(database)
        self.reminders = ReminderRepository(database)
        self.notes = NotesRepository(database)

    def search(self, term: str) -> list[SearchHit]:
        """Everything matching `term`, grouped by kind in a fixed order.

        A failure in one kind must not blank the whole result list; the office
        would rather see the three kinds that worked than an empty box.
        """
        term = " ".join((term or "").split())
        if len(term) < MIN_TERM:
            return []

        hits: list[SearchHit] = []
        for kind, finder in (
            (COMPANY, self._companies),
            (VEHICLE, self._vehicles),
            (REMINDER, self._reminders),
            (NOTE, self._notes),
        ):
            try:
                hits.extend(finder(term)[:PER_KIND])
            except Exception:
                logger.warning("Arama başarısız: %s", kind, exc_info=True)
        return hits

    # ---------------------------------------------------------------- finders
    def _companies(self, term: str) -> list[SearchHit]:
        needle = term.casefold()
        found = []
        for company in self.companies.list_all():
            haystack = f"{company.name} {company.tax_number or ''}".casefold()
            if needle in haystack:
                subtitle = company.tax_number or "Vergi no yok"
                if not company.is_active:
                    subtitle = f"{subtitle} · pasif"
                found.append(SearchHit(COMPANY, company.id, company.name, subtitle))
        return found

    def _vehicles(self, term: str) -> list[SearchHit]:
        needle = term.casefold()
        found = []
        for vehicle in self.vehicles.list_all():
            descriptor = " ".join(p for p in [vehicle.make, vehicle.model] if p)
            haystack = f"{vehicle.plate} {descriptor} {vehicle.company_name or ''}".casefold()
            if needle in haystack:
                subtitle = " · ".join(
                    p for p in [descriptor, vehicle.company_name] if p
                ) or "Şirkete bağlı değil"
                found.append(SearchHit(VEHICLE, vehicle.id, vehicle.plate, subtitle))
        return found

    def _reminders(self, term: str) -> list[SearchHit]:
        found = []
        for record in self.reminders.list_filtered(search=term, limit=PER_KIND * 3):
            parts = [record.company_name or "Genel"]
            if record.due_date:
                parts.append(short_date(record.due_date_obj))
            if record.status == "COMPLETED":
                parts.append("tamamlandı")
            found.append(
                SearchHit(REMINDER, record.id, record.title, " · ".join(parts), record.title)
            )
        return found

    def _notes(self, term: str) -> list[SearchHit]:
        boards = {board.id: board.name for board in self.notes.list_boards()}
        found = []
        for note in self.notes.search(term):
            board = boards.get(note.board_id, "Notlar")
            found.append(
                SearchHit(
                    NOTE,
                    note.id,
                    _excerpt(note.content_text, term) or "(boş not)",
                    f"Not · {board}",
                    str(note.board_id),
                )
            )
        return found


__all__ = [
    "COMPANY",
    "KIND_ORDER",
    "MIN_TERM",
    "NOTE",
    "PER_KIND",
    "REMINDER",
    "VEHICLE",
    "SearchHit",
    "SearchService",
]
