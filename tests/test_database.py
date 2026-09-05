from datetime import date
from pathlib import Path

import pytest

from database.connection import Database
from database.migrations import MigrationRunner
from database.repositories.companies import CompanyRepository
from database.repositories.reminders import ReminderRepository


@pytest.fixture()
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.db")
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    runner = MigrationRunner(db, migrations)
    runner.run()
    return db


def test_migrations_are_idempotent(database: Database) -> None:
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    runner = MigrationRunner(database, migrations)
    assert runner.run() == []


def test_company_and_manual_reminder_crud(database: Database) -> None:
    companies = CompanyRepository(database)
    reminders = ReminderRepository(database)

    company_id = companies.create("ABC Ltd.", "1234567890")
    reminder_id = reminders.create_manual(
        title="Araç muayenesi",
        due_date=date(2026, 9, 16),
        company_id=company_id,
        category="VEHICLE_INSPECTION",
    )

    rows = reminders.list_open()
    assert len(rows) == 1
    assert rows[0].id == reminder_id
    assert rows[0].company_name == "ABC Ltd."
    assert rows[0].due_date == "2026-09-16"


def test_general_notification_delivery_is_unique(database: Database) -> None:
    with database.session() as connection:
        connection.execute(
            """
            INSERT INTO manual_reminders(title, category, due_date)
            VALUES ('Test', 'GENERAL', '2026-09-10')
            """
        )
        reminder_id = connection.execute(
            "SELECT id FROM manual_reminders WHERE title = 'Test'"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO notification_deliveries
                (source_kind, source_id, company_id, notification_key, due_date_snapshot)
            VALUES ('MANUAL', ?, NULL, 'DUE_MINUS_7', '2026-09-10')
            """,
            (reminder_id,),
        )

    with pytest.raises(Exception):
        with database.session() as connection:
            connection.execute(
                """
                INSERT INTO notification_deliveries
                    (source_kind, source_id, company_id, notification_key, due_date_snapshot)
                VALUES ('MANUAL', ?, NULL, 'DUE_MINUS_7', '2026-09-10')
                """,
                (reminder_id,),
            )
