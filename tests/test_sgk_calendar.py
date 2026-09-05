from datetime import date
from pathlib import Path

import pytest

from database.connection import Database
from database.migrations import MigrationRunner
from services.company_service import CompanyService
from services.holiday_service import HolidayService
from services.reminder_service import ReminderService
from services.sgk_calendar_service import SgkCalendarService
from services.sgk_rule_engine import SgkRuleEngine


@pytest.fixture()
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test_sgk.db")
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    MigrationRunner(db, migrations).run()
    return db


@pytest.fixture()
def holiday_service(database: Database) -> HolidayService:
    return HolidayService(database)


@pytest.fixture()
def sgk_service(database: Database, holiday_service: HolidayService) -> SgkCalendarService:
    return SgkCalendarService(database, holiday_service)


def test_holiday_service_basic(holiday_service: HolidayService) -> None:
    assert holiday_service.is_holiday(date(2026, 1, 1)) is True
    assert holiday_service.is_holiday(date(2026, 3, 20)) is True
    assert holiday_service.is_holiday(date(2026, 5, 27)) is True
    assert holiday_service.is_holiday(date(2026, 3, 15)) is False
    # half-day arife should not be full holiday for SGK (is_full_day=0)
    assert holiday_service.is_holiday(date(2026, 3, 19)) is False
    assert holiday_service.is_holiday(date(2026, 10, 28)) is False


def test_sgk_following_month_end_and_weekend() -> None:
    assert SgkRuleEngine.following_month_end(2026, 1) == date(2026, 2, 28)
    assert SgkRuleEngine.following_month_end(2026, 12) == date(2027, 1, 31)
    assert SgkRuleEngine.following_month_end(2024, 1) == date(2024, 2, 29)  # leap
    assert SgkRuleEngine.move_weekend_to_next_weekday(date(2026, 2, 28)) == date(2026, 3, 2)  # Sat -> Mon
    assert SgkRuleEngine.move_weekend_to_next_weekday(date(2026, 3, 31)) == date(2026, 3, 31)  # Tue


def test_sgk_holiday_adjustment(holiday_service: HolidayService) -> None:
    # 2026-01 period normal 2026-02-28 Sat -> Mon 2026-03-02
    normal = SgkRuleEngine.following_month_end(2026, 1)
    eff = SgkRuleEngine.adjust_for_holidays(normal, holiday_service)
    assert eff == date(2026, 3, 2)
    # 2026-04 period normal 2026-05-31 Sun -> Mon 2026-06-01
    normal2 = SgkRuleEngine.following_month_end(2026, 4)
    eff2 = SgkRuleEngine.adjust_for_holidays(normal2, holiday_service)
    assert eff2 == date(2026, 6, 1)
    # Holiday: 2026-03-31 is not holiday, stays
    assert SgkRuleEngine.adjust_for_holidays(date(2026, 3, 31), holiday_service) == date(2026, 3, 31)
    # Mock holiday on 2026-03-31
    class MockHoliday:
        def is_holiday(self, d): return d == date(2026, 3, 31)
        def adjust_to_next_working_day(self, d):
            from datetime import timedelta
            cur = d
            while cur.weekday() >= 5 or self.is_holiday(cur):
                cur += timedelta(days=1)
            return cur
    mock = MockHoliday()
    assert SgkRuleEngine.adjust_for_holidays(date(2026, 3, 31), mock) == date(2026, 4, 1)


def test_sgk_generation_for_year(holiday_service: HolidayService) -> None:
    events = SgkRuleEngine.generate_for_year(2026, holiday_service)
    assert len(events) == 12
    # Check first and last for default 1_END
    assert events[0]["period_key"] == "2026-01"
    assert events[0]["normal_due_date"] == "2026-02-28"
    assert events[0]["effective_due_date"] == "2026-03-02"
    assert events[0]["rule_code"] == SgkRuleEngine.RULE_CODE
    assert events[0]["wage_period"] == "MONTHLY_1_END"
    # Check year transition
    dec = next(e for e in events if e["period_key"] == "2026-12")
    assert dec["normal_due_date"] == "2027-01-31"
    # 2027-01-31 is Sunday -> Monday 2027-02-01
    assert dec["effective_due_date"] == "2027-02-01"
    # Check 15-14 wage period
    events_both = SgkRuleEngine.generate_for_year(2026, holiday_service, wage_periods=["MONTHLY_1_END", "MONTHLY_15_14"])
    assert len(events_both) == 24
    # Check 15_14 has different period_key and correct due (following month 14th)
    p15 = next(e for e in events_both if e["wage_period"] == "MONTHLY_15_14" and e["period_key"].startswith("2026-01"))
    assert "15" in p15["period_key"]
    assert p15["source_event_key"] == "SGK_4A_2026_01_15_14"
    # Explicit per spec: 2026-01-15 to 2026-02-14 period -> due 2026-03-14 Sat -> effective 2026-03-16 Mon
    assert p15["normal_due_date"] == "2026-03-14"
    assert p15["effective_due_date"] == "2026-03-16"
    # Also check a normal weekday for 15_14 (Feb 15 to Mar 14 -> due Apr 14 Tue, no shift)
    feb_15 = next(e for e in events_both if e["wage_period"] == "MONTHLY_15_14" and e["period_key"].startswith("2026-02"))
    assert feb_15["normal_due_date"] == "2026-04-14"
    assert feb_15["effective_due_date"] == "2026-04-14"
    # Check a weekend for 15_14: Dec 15 to Jan 14 -> due Feb 14 2027 Sun -> Mon Feb 15
    dec_15 = next(e for e in events_both if e["wage_period"] == "MONTHLY_15_14" and e["period_key"].startswith("2026-12"))
    assert dec_15["normal_due_date"] == "2027-02-14"
    assert dec_15["effective_due_date"] == "2027-02-15"


def test_sgk_db_import_idempotent(database: Database, sgk_service: SgkCalendarService) -> None:
    inserted = sgk_service.generate_and_import(2026)
    assert inserted == 12
    with database.session() as conn:
        cnt = conn.execute("SELECT COUNT(*) as c FROM official_calendar_events WHERE source_kind='SGK'").fetchone()["c"]
        assert cnt == 12
        row = conn.execute("SELECT * FROM official_calendar_events WHERE source_event_key='SGK_4A_2026_01_1END'").fetchone()
        assert row["normal_due_date"] == "2026-02-28"
        assert row["effective_due_date"] == "2026-03-02"
        assert row["rule_code"] == SgkRuleEngine.RULE_CODE
        assert row["source_kind"] == "SGK"
    inserted2 = sgk_service.generate_and_import(2026)
    assert inserted2 == 0


def test_sgk_muhsgk_guard(database: Database, sgk_service: SgkCalendarService) -> None:
    sgk_service.generate_and_import(2026)
    # Ensure no SGK event has GIB_MUHSGK code (guard)
    with database.session() as conn:
        muhs = conn.execute("SELECT COUNT(*) as c FROM official_calendar_events WHERE obligation_type_id=(SELECT id FROM obligation_types WHERE code='GIB_MUHSGK') AND source_kind='SGK'").fetchone()["c"]
        assert muhs == 0
    # Also test that GIB_MUHSGK and SGK_4A are distinct
    from services.company_service import CompanyService
    cs = CompanyService(database)
    # Create company with both
    cid = cs.create("GuardCo")
    kdv = next(t for t in cs.list_obligation_types() if t.code == "GIB_MUHSGK")
    sgk = next(t for t in cs.list_obligation_types() if t.code == "SGK_4A_PREMIUM")
    # They should be different ids
    assert kdv.id != sgk.id


def test_sgk_company_separation(database: Database, holiday_service: HolidayService) -> None:
    sgk_service = SgkCalendarService(database, holiday_service)
    sgk_service.generate_and_import(2026)
    cs = CompanyService(database)
    rs = ReminderService(database)
    cid1 = cs.create("SGKCo1")
    cid2 = cs.create("SGKCo2")
    sgk_type = next(t for t in cs.list_obligation_types() if t.code == "SGK_4A_PREMIUM")
    cs.set_company_obligations(cid1, [sgk_type.id])
    cs.set_company_obligations(cid2, [sgk_type.id])
    # For SGK, need to set wage_period in settings_json for eligibility
    with database.session() as conn:
        conn.execute(
            "UPDATE company_obligations SET settings_json = ? WHERE company_id = ? AND obligation_type_id = ?",
            ('{"wage_period": "MONTHLY_1_END"}', cid1, sgk_type.id),
        )
        conn.execute(
            "UPDATE company_obligations SET settings_json = ? WHERE company_id = ? AND obligation_type_id = ?",
            ('{"wage_period": "MONTHLY_1_END"}', cid2, sgk_type.id),
        )
    due1 = rs.list_due(horizon_days=400, today=date(2026, 1, 1), company_id=cid1)
    sgk_due1 = [d for d in due1 if d.source_label == "SGK"]
    assert len(sgk_due1) == 12
    # Complete one for cid1
    with database.session() as conn:
        eid = conn.execute("SELECT id FROM official_calendar_events WHERE source_event_key='SGK_4A_2026_01_1END'").fetchone()["id"]
    rs.complete(source_kind="OFFICIAL", source_id=eid, company_id=cid1)
    assert rs.is_completed("OFFICIAL", eid, cid1) is True
    assert rs.is_completed("OFFICIAL", eid, cid2) is False
    due1_after = rs.list_due(horizon_days=400, today=date(2026, 1, 1), company_id=cid1)
    assert len([d for d in due1_after if d.source_label == "SGK"]) == 11
    due2 = rs.list_due(horizon_days=400, today=date(2026, 1, 1), company_id=cid2)
    assert len([d for d in due2 if d.source_label == "SGK"]) == 12


def test_sgk_wage_period_two_types(database: Database, holiday_service: HolidayService) -> None:
    # Test that two companies with different wage periods don't interfere
    sgk_service = SgkCalendarService(database, holiday_service)
    # Generate both wage periods
    sgk_service.generate_and_import(2026, wage_periods=["MONTHLY_1_END", "MONTHLY_15_14"])
    with database.session() as conn:
        cnt = conn.execute("SELECT COUNT(*) as c FROM official_calendar_events WHERE source_kind='SGK'").fetchone()["c"]
        assert cnt == 24
    cs = CompanyService(database)
    rs = ReminderService(database)
    cid_1end = cs.create("SGK_1END_Co")
    cid_15 = cs.create("SGK_15_Co")
    sgk_type = next(t for t in cs.list_obligation_types() if t.code == "SGK_4A_PREMIUM")
    cs.set_company_obligations(cid_1end, [sgk_type.id])
    cs.set_company_obligations(cid_15, [sgk_type.id])
    with database.session() as conn:
        conn.execute(
            "UPDATE company_obligations SET settings_json = ? WHERE company_id = ?",
            ('{"wage_period": "MONTHLY_1_END"}', cid_1end),
        )
        conn.execute(
            "UPDATE company_obligations SET settings_json = ? WHERE company_id = ?",
            ('{"wage_period": "MONTHLY_15_14"}', cid_15),
        )
    # Use horizon 500 to include Dec 15_14 due Feb 14 next year (400 ends Feb 5)
    due_1end = rs.list_due(horizon_days=500, today=date(2026, 1, 1), company_id=cid_1end)
    due_15 = rs.list_due(horizon_days=500, today=date(2026, 1, 1), company_id=cid_15)
    sgk_1end = [d for d in due_1end if d.source_label == "SGK"]
    sgk_15 = [d for d in due_15 if d.source_label == "SGK"]
    # Each should see 12, not 24, and not interfere
    assert len(sgk_1end) == 12
    assert len(sgk_15) == 12
    # Check that period keys are distinct
    assert any("1–Ay Sonu" in d.title for d in sgk_1end)
    assert any("15–14" in d.title for d in sgk_15)
    # Ensure a 1_END event not visible to 15_14 company
    assert not any("1–Ay Sonu" in d.title for d in sgk_15)
    assert not any("15–14" in d.title for d in sgk_1end)


def test_sgk_normal_vs_effective_and_revision(database: Database, sgk_service: SgkCalendarService) -> None:
    sgk_service.generate_and_import(2026)
    with database.session() as conn:
        row = conn.execute("SELECT id, normal_due_date, effective_due_date FROM official_calendar_events WHERE source_event_key='SGK_4A_2026_02_1END'").fetchone()
        assert row["normal_due_date"] == "2026-03-31"
        assert row["effective_due_date"] == "2026-03-31"
        eid = row["id"]
        normal = row["normal_due_date"]
    # Apply official extension to 2026-04-02
    sgk_service.apply_official_override("SGK_4A_2026_02_1END", date(2026, 4, 2), "SGK duyurusu uzatma", "https://sgk.gov.tr/duyuru", "2026-03-28")
    with database.session() as conn:
        row2 = conn.execute("SELECT normal_due_date, effective_due_date FROM official_calendar_events WHERE source_event_key='SGK_4A_2026_02_1END'").fetchone()
        assert row2["normal_due_date"] == normal  # preserved
        assert row2["effective_due_date"] == "2026-04-02"
        rev = conn.execute("SELECT * FROM official_calendar_revisions WHERE official_event_id=?", (eid,)).fetchone()
        assert rev is not None
        assert rev["old_due_date"] == "2026-03-31"
        assert rev["new_due_date"] == "2026-04-02"
        assert rev["reason"] == "SGK duyurusu uzatma"


def test_sgk_february_leap_year() -> None:
    # 2024 leap year
    assert SgkRuleEngine.following_month_end(2024, 1) == date(2024, 2, 29)
    # 2023 non-leap
    assert SgkRuleEngine.following_month_end(2023, 1) == date(2023, 2, 28)
    # 2026 non-leap Feb has 28 days, but generation for Feb period due March 31
    assert SgkRuleEngine.following_month_end(2026, 2) == date(2026, 3, 31)


def test_sgk_generation_stops_where_the_holiday_data_stops(
    database: Database, sgk_service: SgkCalendarService
) -> None:
    """The last year SGK can produce is one less than the last holiday year.

    A period's due date can land in January of the *following* year, so
    `generate_and_import` refuses the whole year unless holidays exist for
    `year` and `year + 1`. The bundled table ends with 2028, which means 2027
    is the last year that can be generated — not 2028. This test pins that
    boundary so the runway cannot shrink unnoticed: when it fails, the fix is
    a migration adding the next years' official holidays.
    """
    periods = ["MONTHLY_1_END", "MONTHLY_15_14"]

    assert sgk_service.generate_and_import(2027, wage_periods=periods) > 0
    assert sgk_service.generate_and_import(2028, wage_periods=periods) == 0

    with database.session() as conn:
        produced = conn.execute(
            "SELECT COUNT(*) c FROM official_calendar_events "
            "WHERE year = 2028 AND source_kind = 'SGK'"
        ).fetchone()["c"]
        state = conn.execute(
            "SELECT status FROM official_source_state WHERE source_code = 'SGK_4A_2029'"
        ).fetchone()

    # Fail closed: no date is invented for a year whose holidays are unknown.
    assert produced == 0
    assert state is not None and state["status"] == "NEEDS_DATA"
