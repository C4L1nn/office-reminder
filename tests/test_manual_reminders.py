from datetime import date, timedelta
from pathlib import Path

import pytest

from database.connection import Database
from database.migrations import MigrationRunner
from services.reminder_service import ReminderService, compute_next_due_date
from services.notification_service import NotificationService
from unittest.mock import MagicMock


@pytest.fixture()
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test_faz1.db")
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    MigrationRunner(db, migrations).run()
    return db


@pytest.fixture()
def reminder_service(database: Database) -> ReminderService:
    return ReminderService(database)


def test_create_update_delete_manual(reminder_service: ReminderService) -> None:
    rid = reminder_service.create_manual(title="Faz1 Test", due_date=date(2026, 9, 20), category="GENERAL")
    rec = reminder_service.get_manual(rid)
    assert rec is not None and rec.title == "Faz1 Test"
    reminder_service.update_manual(rid, title="Guncellendi")
    assert reminder_service.get_manual(rid).title == "Guncellendi"
    assert reminder_service.delete_manual(rid) is True
    assert reminder_service.get_manual(rid) is None


def test_recurrence_helpers() -> None:
    assert compute_next_due_date(date(2026, 1, 15), "MONTHLY") == date(2026, 2, 15)
    assert compute_next_due_date(date(2026, 1, 15), "QUARTERLY") == date(2026, 4, 15)
    assert compute_next_due_date(date(2026, 1, 15), "YEARLY") == date(2027, 1, 15)
    assert compute_next_due_date(date(2026, 1, 31), "MONTHLY") == date(2026, 2, 28)
    assert compute_next_due_date(date(2026, 1, 15), "NONE") is None


def test_recurrence_creation_on_complete(reminder_service: ReminderService) -> None:
    rid = reminder_service.create_manual(
        title="Kira", due_date=date(2026, 5, 10), category="RENT", recurrence_kind="MONTHLY"
    )
    reminder_service.complete(source_kind="MANUAL", source_id=rid)
    recs = reminder_service.search_manual(search="Kira")
    assert len(recs) == 2
    nxt = [r for r in recs if r.status == "OPEN"][0]
    assert nxt.due_date == "2026-06-10"


def test_custom_notification_offsets(reminder_service: ReminderService) -> None:
    rid = reminder_service.create_manual(
        title="Off", due_date=date.today() + timedelta(days=7), notification_offsets=[7, 1]
    )
    assert reminder_service.notification_rules.get_effective_offsets("MANUAL", rid) == [7, 1]
    rid2 = reminder_service.create_manual(title="Def", due_date=date.today() + timedelta(days=14))
    assert reminder_service.notification_rules.get_effective_offsets("MANUAL", rid2) == [14, 7, 3, 1, 0]


def test_due_overdue_listing(reminder_service: ReminderService) -> None:
    today = date.today()
    reminder_service.create_manual(title="Geciken", due_date=today - timedelta(days=2))
    reminder_service.create_manual(title="Bugun", due_date=today)
    reminder_service.create_manual(title="Yaklasan", due_date=today + timedelta(days=3))
    assert any(o.title == "Geciken" for o in reminder_service.list_overdue(today=today))
    assert any(t.title == "Bugun" for t in reminder_service.list_today(today=today))
    upcoming = reminder_service.list_due(horizon_days=7, today=today)
    assert any(u.title == "Yaklasan" for u in upcoming)
    assert not any(u.title == "Geciken" for u in upcoming)


def test_notification_dedup_and_overdue_daily(database: Database, reminder_service: ReminderService) -> None:
    today = date.today()
    rid = reminder_service.create_manual(title="Bildirim", due_date=today + timedelta(days=7))
    mock = MagicMock()
    ns = NotificationService(database, reminder_service, mock)
    assert ns.check_and_notify(today=today) == 1
    assert ns.check_and_notify(today=today) == 0
    # overdue daily
    reminder_service.create_manual(title="Gcik", due_date=today - timedelta(days=1))
    ns2 = NotificationService(database, reminder_service, MagicMock())
    # first overdue delivers (1 for overdue, but upcoming already delivered so only overdue counts)
    # We create fresh db for overdue isolation
    db2 = Database(database.path.parent / "test2.db")
    # Use separate service to isolate
    from database.migrations import MigrationRunner as MR
    from pathlib import Path as P

    # Instead test with current db: today's overdue should deliver 1 (gcik) + maybe 0 for already delivered upcoming
    mock2 = MagicMock()
    ns3 = NotificationService(database, reminder_service, mock2)
    # reset by using new reminder? already tested dedup above, so only overdue remains once
    # Call again same day should not deliver again
    # We already delivered bildirim earlier, so next call should deliver overdue only once
    # Let's use a clean db for precise test
    import tempfile, pathlib

    td = tempfile.mkdtemp()
    db_tmp = Database(pathlib.Path(td) / "tmp.db")
    m = P(__file__).resolve().parents[1] / "database" / "migrations"
    MR(db_tmp, m).run()
    rs_tmp = ReminderService(db_tmp)
    rs_tmp.create_manual(title="Gcik2", due_date=today - timedelta(days=1))
    mock_tmp = MagicMock()
    ns_tmp = NotificationService(db_tmp, rs_tmp, mock_tmp)
    assert ns_tmp.check_and_notify(today=today) == 1
    assert ns_tmp.check_and_notify(today=today) == 0
    assert ns_tmp.check_and_notify(today=today + timedelta(days=1)) == 1


def test_company_filter(reminder_service: ReminderService, database: Database) -> None:
    from database.repositories.companies import CompanyRepository

    cr = CompanyRepository(database)
    cid = cr.create("TestCo", "111")
    cid2 = cr.create("OtherCo", "222")
    today = date.today()
    reminder_service.create_manual(title="A", due_date=today + timedelta(days=2), company_id=cid)
    reminder_service.create_manual(title="B", due_date=today + timedelta(days=2), company_id=cid2)
    filtered = reminder_service.list_due(horizon_days=5, today=today, company_id=cid)
    assert len(filtered) == 1 and filtered[0].title == "A"
