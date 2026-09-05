from datetime import date, timedelta
from pathlib import Path

import pytest

from database.connection import Database
from database.migrations import MigrationRunner
from services.company_service import CompanyService
from services.reminder_service import ReminderService


@pytest.fixture()
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "faz2.db")
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    MigrationRunner(db, migrations).run()
    return db


@pytest.fixture()
def company_service(database: Database) -> CompanyService:
    return CompanyService(database)


@pytest.fixture()
def reminder_service(database: Database) -> ReminderService:
    return ReminderService(database)


def test_obligation_types_seeded(company_service: CompanyService) -> None:
    types = company_service.list_obligation_types()
    codes = {t.code for t in types}
    assert "GIB_KDV" in codes
    assert "GIB_MUHSGK" in codes
    assert "SGK_4A_PREMIUM" in codes
    assert len(types) >= 9


def test_company_crud_and_tax_unique(company_service: CompanyService) -> None:
    cid = company_service.create("ABC Ltd", "1234567890")
    assert company_service.get_by_id(cid) is not None
    with pytest.raises(ValueError):
        company_service.create("Other", "1234567890")
    company_service.update(cid, name="ABC Updated")
    assert company_service.get_by_id(cid).name == "ABC Updated"
    company_service.set_active(cid, False)
    assert company_service.get_by_id(cid).is_active is False
    assert cid not in {c.id for c in company_service.list_active()}
    assert cid in {c.id for c in company_service.list_all()}


def test_company_obligation_assignment(company_service: CompanyService) -> None:
    cid = company_service.create("TestCo")
    types = company_service.list_obligation_types()
    kdv = next(t for t in types if t.code == "GIB_KDV")
    sgk = next(t for t in types if t.code == "SGK_4A_PREMIUM")
    company_service.set_company_obligations(cid, [kdv.id, sgk.id])
    assert company_service.get_assigned_obligation_ids(cid) == {kdv.id, sgk.id}
    company_service.set_company_obligations(cid, [kdv.id])
    assert company_service.get_assigned_obligation_ids(cid) == {kdv.id}


def test_official_event_matching_via_obligation(company_service: CompanyService, reminder_service: ReminderService, database: Database) -> None:
    cid = company_service.create("SirketA")
    kdv = next(t for t in company_service.list_obligation_types() if t.code == "GIB_KDV")
    muhs = next(t for t in company_service.list_obligation_types() if t.code == "GIB_MUHSGK")
    company_service.set_company_obligations(cid, [kdv.id])
    with database.session() as conn:
        conn.execute(
            """
            INSERT INTO official_calendar_events
            (obligation_type_id, source_kind, source_event_key, title, year, normal_due_date, effective_due_date, source_url)
            VALUES (?, 'GIB', 'KDV-2026-09', 'KDV 09/2026', 2026, '2026-09-28', '2026-09-28', 'https://gib.gov.tr')
            """,
            (kdv.id,),
        )
        conn.execute(
            """
            INSERT INTO official_calendar_events
            (obligation_type_id, source_kind, source_event_key, title, year, normal_due_date, effective_due_date, source_url)
            VALUES (?, 'GIB', 'MUHSGK-2026-09', 'MUHSGK 09/2026', 2026, '2026-09-26', '2026-09-26', 'https://gib.gov.tr')
            """,
            (muhs.id,),
        )
        eid = conn.execute("SELECT id FROM official_calendar_events WHERE source_event_key='KDV-2026-09'").fetchone()["id"]
    due = reminder_service.list_due(horizon_days=30, today=date(2026, 9, 1), company_id=cid)
    titles = [d.title for d in due]
    assert any("KDV" in t for t in titles)
    assert not any("MUHSGK" in t for t in titles)
    # assign muhs then should appear
    company_service.set_company_obligations(cid, [kdv.id, muhs.id])
    due2 = reminder_service.list_due(horizon_days=30, today=date(2026, 9, 1), company_id=cid)
    assert any("MUHSGK" in t for t in [d.title for d in due2])
    # complete and verify hidden
    reminder_service.complete(source_kind="OFFICIAL", source_id=eid, company_id=cid)
    due3 = reminder_service.list_due(horizon_days=30, today=date(2026, 9, 1), company_id=cid)
    assert not any(d.source_id == eid for d in due3)


def test_vehicle_crud_and_plate_unique(company_service: CompanyService) -> None:
    cid = company_service.create("VehCo")
    vid = company_service.create_vehicle(company_id=cid, plate="34 ABC 123", make="Toyota")
    assert company_service.vehicles.get_by_id(vid).plate == "34 ABC 123"
    with pytest.raises(ValueError):
        company_service.create_vehicle(company_id=cid, plate="34 ABC 123")
    company_service.update_vehicle(vid, plate="34 XYZ 999")
    assert company_service.vehicles.get_by_id(vid).plate == "34 XYZ 999"


def test_company_summary(company_service: CompanyService, reminder_service: ReminderService, database: Database) -> None:
    cid = company_service.create("SummCo")
    kdv = next(t for t in company_service.list_obligation_types() if t.code == "GIB_KDV")
    company_service.set_company_obligations(cid, [kdv.id])
    with database.session() as conn:
        conn.execute(
            """
            INSERT INTO official_calendar_events
            (obligation_type_id, source_kind, source_event_key, title, year, normal_due_date, effective_due_date, source_url)
            VALUES (?, 'GIB', 'KDV-SUMM', 'KDV 10/2026', 2026, '2026-10-26', '2026-10-26', 'https://gib.gov.tr')
            """,
            (kdv.id,),
        )
    reminder_service.create_manual(title="Manuel 1", due_date=date.today() + timedelta(days=5), company_id=cid)
    company_service.create_vehicle(company_id=cid, plate="06 TEST 01")
    summ = company_service.get_company_summary(cid)
    assert summ["obligations"] == 1
    assert summ["vehicles"] == 1
    assert summ["manual_open"] == 1
    assert summ["official_active"] == 1
