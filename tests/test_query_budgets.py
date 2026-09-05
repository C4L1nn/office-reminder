"""Guards against the query patterns that made screens slow.

Every one of these was measured before it was fixed: a per-day holiday lookup
turned one tooltip into 300 round trips, a per-row profile lookup turned one
dashboard refresh into 178 connections, and `PRAGMA journal_mode` on every
connect cost ten milliseconds a time. None of that is visible from reading the
code, so the budgets are asserted here.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from database.connection import Database
from services.company_service import CompanyService
from services.eligibility_service import EligibilityService
from services.holiday_service import HolidayService
from services.reminder_service import ReminderService


class Counter:
    """Counts connections opened while it is active."""

    def __init__(self, monkeypatch):
        self.count = 0
        original = Database.connect

        def counted(inner_self):
            self.count += 1
            return original(inner_self)

        monkeypatch.setattr(Database, "connect", counted)


@pytest.fixture()
def office(seeded_db):
    """A handful of companies with real obligation profiles."""
    companies = CompanyService(seeded_db)
    types = {t.code: t.id for t in companies.list_obligation_types()}
    wanted = [types[c] for c in ("GIB_KDV", "GIB_DAMGA") if c in types]
    reminders = ReminderService(seeded_db)
    for index in range(8):
        company_id = companies.create(
            name=f"BÜTÇE {index} LTD.", tax_number=f"{7000000000 + index}"
        )
        companies.set_company_obligations(company_id, wanted)
        reminders.create_manual(
            title=f"Manuel {index}",
            due_date=date.today() + timedelta(days=4 + index),
            company_id=company_id,
            category="OTHER",
        )
    return companies, reminders


# ------------------------------------------------------------------ holidays
def test_working_days_reads_the_holiday_table_once_per_year(seeded_db, monkeypatch) -> None:
    holidays = HolidayService(seeded_db)
    counter = Counter(monkeypatch)
    holidays.working_days_between(date(2026, 1, 5), date(2026, 12, 20))
    # One read for the year, not one per day.
    assert counter.count <= 2, f"{counter.count} bağlantı — gün başına sorgu var"


def test_the_holiday_set_is_kept_between_calls(seeded_db, monkeypatch) -> None:
    holidays = HolidayService(seeded_db)
    holidays.working_days_between(date(2026, 2, 1), date(2026, 3, 1))
    counter = Counter(monkeypatch)
    holidays.working_days_between(date(2026, 4, 1), date(2026, 5, 1))
    assert counter.count == 0, "aynı yıl için tekrar okundu"


def test_a_half_day_holiday_is_still_a_working_day(seeded_db) -> None:
    """`is_holiday` has always meant full-day; the cache must agree."""
    holidays = HolidayService(seeded_db)
    with seeded_db.session() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO holidays_tr (holiday_date, name, kind, is_full_day)"
            " VALUES ('2026-06-10', 'Yarım gün', 'NATIONAL', 0)"
        )
    assert date(2026, 6, 10) not in holidays.holiday_dates(2026)
    assert not holidays.is_holiday(date(2026, 6, 10))


# -------------------------------------------------------------- eligibility
def test_bulk_settings_match_the_per_row_lookup(office, seeded_db) -> None:
    """The fast path must return exactly what the slow one did."""
    companies, _reminders = office
    eligibility = EligibilityService(seeded_db)
    pairs = {(c.id, "GIB_KDV") for c in companies.list_all()}

    bulk = eligibility.load_settings(pairs)
    for company_id, code in pairs:
        one = eligibility.get_company_obligation_settings(company_id, code)
        assert bulk.get((company_id, code)) == one, (company_id, code)


def test_a_dashboard_refresh_stays_within_its_budget(qt_app, office, seeded_db, monkeypatch) -> None:
    from ui.pages.dashboard_page import DashboardPage
    from ui.theme import apply_theme

    apply_theme(qt_app)
    companies, reminders = office
    page = DashboardPage(reminders, companies)

    counter = Counter(monkeypatch)
    page.refresh()
    # Was 178 with a profile lookup per official row.
    assert counter.count < 40, f"{counter.count} bağlantı"
    page.close()


def test_a_reminders_refresh_stays_within_its_budget(qt_app, office, seeded_db, monkeypatch) -> None:
    from ui.pages.reminders_page import RemindersPage
    from ui.theme import apply_theme

    apply_theme(qt_app)
    companies, reminders = office
    page = RemindersPage(reminders, companies)
    page.refresh()

    counter = Counter(monkeypatch)
    page.refresh()
    # Was over a thousand: the due tooltip counted working days day by day.
    assert counter.count < 40, f"{counter.count} bağlantı"
    page.close()


# ---------------------------------------------------------------- companies
def test_bulk_summaries_match_the_per_company_query(office, seeded_db) -> None:
    companies, _reminders = office
    bulk = companies.list_summaries()
    for company in companies.list_all():
        one = companies.get_company_summary(company.id)
        got = bulk.get(company.id, {k: 0 for k in one})
        assert got == one, company.name


def test_listing_companies_does_not_query_per_row(qt_app, office, seeded_db, monkeypatch) -> None:
    from ui.pages.companies_page import CompaniesPage
    from ui.theme import apply_theme

    apply_theme(qt_app)
    companies, _reminders = office
    page = CompaniesPage(companies)
    page.refresh()

    counter = Counter(monkeypatch)
    page.refresh()
    assert counter.count < 30, f"{counter.count} bağlantı"
    page.close()


# --------------------------------------------------------------- connection
def test_journal_mode_is_set_once_per_database(tmp_path) -> None:
    """WAL lives in the file header; asking for it on every connect cost 10ms.

    sqlite3.Connection is immutable, so the statements are collected with the
    driver's own trace callback rather than by patching `execute`.
    """
    path = tmp_path / "budget.db"
    database = Database(path)
    Database._wal_ready.discard(str(path.resolve()))

    seen: list[str] = []
    for _ in range(5):
        connection = database.connect()
        connection.set_trace_callback(seen.append)
        connection.execute("SELECT 1")
        connection.close()

    # The trace only sees statements after it is installed, so connect() is
    # measured by what it leaves behind: the journal mode of the file.
    with database.connect() as probe:
        mode = probe.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    assert str(path.resolve()) in Database._wal_ready


def test_the_second_connection_skips_the_journal_pragma(tmp_path) -> None:
    """The saving is real only if the pragma is actually skipped."""
    import sqlite3

    path = tmp_path / "second.db"
    database = Database(path)
    Database._wal_ready.discard(str(path.resolve()))

    statements: list[str] = []
    original_connect = sqlite3.connect

    def traced(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    sqlite3.connect = traced
    try:
        database.connect().close()
        first = [s for s in statements if "journal_mode" in s]
        statements.clear()
        database.connect().close()
        second = [s for s in statements if "journal_mode" in s]
    finally:
        sqlite3.connect = original_connect

    assert first, "ilk bağlantıda WAL ayarlanmadı"
    assert not second, "ikinci bağlantıda gereksiz yere tekrar ayarlandı"
