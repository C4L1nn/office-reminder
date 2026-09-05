from __future__ import annotations

import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "database" / "migrations"
SEED_DIR = PROJECT_ROOT / "resources" / "seed"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """Keep every test off the developer's real runtime directory."""
    monkeypatch.setenv("OFFICE_REMINDER_DATA_DIR", str(tmp_path / "runtime"))
    yield


@pytest.fixture
def migrated_db(tmp_path):
    """A fresh database with all migrations applied."""
    from database.connection import Database
    from database.migrations import MigrationRunner

    database = Database(tmp_path / "office_reminder.db")
    MigrationRunner(database, MIGRATIONS_DIR).run()
    return database


@pytest.fixture
def seeded_db(migrated_db):
    """Migrated database plus the bundled GİB 2026 calendar and SGK 2026 rules."""
    from services.holiday_service import HolidayService
    from services.official_calendar_service import OfficialCalendarSeedService
    from services.sgk_calendar_service import SgkCalendarService

    OfficialCalendarSeedService(migrated_db, SEED_DIR).import_seed("official_calendar_2026.json")
    SgkCalendarService(migrated_db, HolidayService(migrated_db)).generate_and_import(
        2026, wage_periods=["MONTHLY_1_END", "MONTHLY_15_14"]
    )
    return migrated_db


@pytest.fixture(scope="session")
def sgk_fixture_dir() -> Path:
    return FIXTURES_DIR / "sgk"


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the whole session (widgets and QtPdf need it)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    return app
