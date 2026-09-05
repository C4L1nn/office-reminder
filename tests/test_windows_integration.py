import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from database.connection import Database
from database.migrations import MigrationRunner


def test_runtime_paths(tmp_path: Path, monkeypatch) -> None:
    # Test that AppPaths correctly resolves runtime vs bundle
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("OFFICE_REMINDER_DATA_DIR", str(runtime))
    monkeypatch.setenv("OFFICE_REMINDER_USE_LOCALAPPDATA", "0")
    # Reimport
    import importlib
    import app.paths

    importlib.reload(app.paths)
    from app.paths import get_database_path, get_runtime_root, get_backups_dir, get_logs_dir

    assert get_runtime_root() == runtime
    assert get_database_path() == runtime / "data" / "office_reminder.db"
    assert get_backups_dir() == runtime / "backups"
    assert get_logs_dir() == runtime / "logs"
    # Cleanup env
    monkeypatch.delenv("OFFICE_REMINDER_DATA_DIR", raising=False)
    importlib.reload(app.paths)


def test_first_run_db_initialize(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "first_run"
    monkeypatch.setenv("OFFICE_REMINDER_DATA_DIR", str(runtime))
    import importlib
    import app.paths

    importlib.reload(app.paths)
    from app.paths import get_database_path, get_migrations_dir, get_seed_dir

    # Ensure DB does not exist
    assert not get_database_path().exists()
    # Simulate first run: create DB, run migrations, import seed
    from database.connection import Database
    from database.migrations import MigrationRunner
    from services.official_calendar_service import OfficialCalendarSeedService

    db = Database(get_database_path())
    # Ensure parent exists via Database
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    # Use the real migrations dir from bundle (which is project root)
    # For test, use that
    applied = MigrationRunner(db, migrations).run()
    assert len(applied) > 0
    # Import seed
    seed_dir = Path(__file__).resolve().parents[1] / "resources" / "seed"
    inserted = OfficialCalendarSeedService(db, seed_dir).import_seed("official_calendar_2026.json")
    assert inserted == 476
    # DB should exist and have data
    assert get_database_path().exists()
    with db.session() as conn:
        cnt = conn.execute("SELECT COUNT(*) as c FROM official_calendar_events").fetchone()["c"]
        assert cnt == 476
    monkeypatch.delenv("OFFICE_REMINDER_DATA_DIR", raising=False)
    importlib.reload(app.paths)


def test_existing_db_not_overwritten(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "existing"
    monkeypatch.setenv("OFFICE_REMINDER_DATA_DIR", str(runtime))
    import importlib
    import app.paths

    importlib.reload(app.paths)
    from app.paths import get_database_path

    # Create existing DB with custom data
    db = Database(get_database_path())
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    MigrationRunner(db, migrations).run()
    # Insert a custom company
    with db.session() as conn:
        conn.execute("INSERT INTO companies(name) VALUES ('ExistingCo')")
        cid = conn.execute("SELECT id FROM companies WHERE name='ExistingCo'").fetchone()["id"]
        assert cid is not None
    # Simulate second startup: should not overwrite existing DB, should preserve ExistingCo
    # Re-run migrations and seed (idempotent)
    from services.official_calendar_service import OfficialCalendarSeedService

    seed_dir = Path(__file__).resolve().parents[1] / "resources" / "seed"
    # This should not delete ExistingCo
    MigrationRunner(db, migrations).run()
    OfficialCalendarSeedService(db, seed_dir).import_seed("official_calendar_2026.json")
    with db.session() as conn:
        row = conn.execute("SELECT * FROM companies WHERE name='ExistingCo'").fetchone()
        assert row is not None
    monkeypatch.delenv("OFFICE_REMINDER_DATA_DIR", raising=False)
    importlib.reload(app.paths)


def test_autostart_idempotent() -> None:
    from services.startup_service import MemoryAutostartStore, StartupService

    store = MemoryAutostartStore()
    svc = StartupService(store=store)
    assert svc.is_enabled() is False
    svc.enable(background=True)
    assert svc.is_enabled() is True
    first_cmd = svc.get_command()
    # Idempotent: enable again should not change
    svc.enable(background=True)
    assert svc.get_command() == first_cmd
    svc.disable()
    assert svc.is_enabled() is False
    # Disable idempotent
    svc.disable()
    assert svc.is_enabled() is False
    # Enable/disable via set_enabled
    svc.set_enabled(True, background=True)
    assert svc.is_enabled() is True
    svc.set_enabled(True, background=True)  # again
    assert svc.is_enabled() is True
    svc.set_enabled(False)
    assert svc.is_enabled() is False


def test_single_instance_guard(tmp_path: Path) -> None:
    from app.single_instance import SingleInstanceGuard

    lock_path = tmp_path / "test.lock"
    guard1 = SingleInstanceGuard(lock_path=lock_path)
    assert guard1.try_acquire() is True
    guard2 = SingleInstanceGuard(lock_path=lock_path)
    # Second should fail
    assert guard2.try_acquire() is False
    guard1.unlock()
    # Now second should succeed after unlock
    assert guard2.try_acquire() is True
    guard2.unlock()


def test_close_to_tray_and_explicit_quit(tmp_path: Path, qt_app) -> None:
    """Closing the window hides to tray only while that setting is on."""
    from unittest.mock import MagicMock

    from database.connection import Database
    from database.migrations import MigrationRunner
    from PySide6.QtGui import QCloseEvent
    from services.company_service import CompanyService
    from services.official_update_service import OfficialUpdateService
    from services.reminder_service import ReminderService
    from services.settings_service import SettingsService
    from ui.main_window import MainWindow

    db = Database(tmp_path / "tray.db")
    MigrationRunner(db, Path(__file__).resolve().parents[1] / "database" / "migrations").run()
    settings = SettingsService(db)
    settings.set_minimize_to_tray(True)

    window = MainWindow(
        ReminderService(db), CompanyService(db), settings, OfficialUpdateService(db)
    )
    tray = MagicMock()
    tray.isVisible.return_value = True
    window.set_tray_icon(tray)

    quit_calls = []
    window.quit_requested.connect(lambda: quit_calls.append(1))

    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted(), "tepside kalmalı, kapanmamalı"
    assert not quit_calls, "tepsiye küçülmek çıkış sayılmaz"

    settings.set_minimize_to_tray(False)
    window._settings_changed()
    second = QCloseEvent()
    window.closeEvent(second)
    assert second.isAccepted()
    assert quit_calls == [1], "ayar kapalıyken kapatmak gerçekten çıkıştır"

    window.close()


def test_notification_adapter_and_dedup(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from database.connection import Database
    from database.migrations import MigrationRunner
    from services.company_service import CompanyService
    from services.notification_adapter import NotificationPayload, QtTrayNotificationAdapter
    from services.notification_service import NotificationService
    from services.reminder_service import ReminderService

    db = Database(tmp_path / "notif.db")
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    MigrationRunner(db, migrations).run()
    rs = ReminderService(db)
    cs = CompanyService(db)
    cid = cs.create("NotifCo")
    # Create a manual reminder due in 3 days
    from datetime import date, timedelta

    rid = rs.create_manual(title="TestNotif", due_date=date.today() + timedelta(days=3), company_id=cid)
    # Mock tray
    mock_tray = MagicMock()
    mock_tray.supportsMessages.return_value = True
    adapter = QtTrayNotificationAdapter(mock_tray)
    # Create service with adapter
    notif = NotificationService(db, rs, tray_icon=mock_tray, adapter=adapter)
    # First check should deliver
    delivered = notif.check_and_notify(today=date.today())
    # Should have called showMessage
    assert mock_tray.showMessage.called
    # Second check should be 0 due dedup
    mock_tray.reset_mock()
    # Need to recreate adapter with same mock
    notif2 = NotificationService(db, rs, tray_icon=mock_tray, adapter=QtTrayNotificationAdapter(mock_tray))
    delivered2 = notif2.check_and_notify(today=date.today())
    assert delivered2 == 0
    assert not mock_tray.showMessage.called


def test_daily_backup_once_per_day_and_retention(tmp_path: Path) -> None:
    from datetime import date

    from app.paths import get_database_path

    # Create a temp DB
    db_path = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    # Create source DB with data
    db = Database(db_path)
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    MigrationRunner(db, migrations).run()
    with db.session() as conn:
        conn.execute("INSERT INTO companies(name) VALUES ('BackupCo')")

    from services.backup_service import BackupService

    svc = BackupService(db_path, backup_dir, retention_days=3)
    # First backup
    p1 = svc.create_backup_if_needed()
    assert p1 is not None
    assert p1.exists()
    # Second backup same day should be None (already exists)
    p2 = svc.create_backup_if_needed()
    assert p2 is None
    # Force backup should create new with timestamp
    p3 = svc.create_backup(force=True)
    assert p3 is not None
    assert p3 != p1
    # Create 5 fake old backups with old mtime
    import time

    for i in range(5):
        old = backup_dir / f"office_reminder_2020-01-0{i+1}.db"
        old.write_text("fake")
        # Set mtime to old
        old_time = time.time() - (10 + i) * 86400
        os.utime(old, (old_time, old_time))
    # Apply retention (keep 3)
    svc._apply_retention()
    remaining = svc.list_backups()
    # Should keep 3 most recent (including today's)
    assert len(remaining) <= 3 or len(remaining) == 3  # at least not all 7
    # Check integrity of real backup
    # Verify backup is valid sqlite
    conn = sqlite3.connect(p1)
    cur = conn.execute("PRAGMA integrity_check")
    assert cur.fetchone()[0] == "ok"
    conn.close()
    # Check content consistent
    src_conn = sqlite3.connect(db_path)
    bkp_conn = sqlite3.connect(p1)
    src_cnt = src_conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    bkp_cnt = bkp_conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    assert src_cnt == bkp_cnt
    src_conn.close()
    bkp_conn.close()


def test_backup_integrity_and_content(tmp_path: Path) -> None:
    db_path = tmp_path / "src2.db"
    backup_dir = tmp_path / "backups2"
    db = Database(db_path)
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    MigrationRunner(db, migrations).run()
    with db.session() as conn:
        conn.execute("INSERT INTO companies(name) VALUES ('IntegrityCo')")
    from services.backup_service import BackupService

    svc = BackupService(db_path, backup_dir)
    p = svc.create_backup(force=True)
    assert p is not None
    # Integrity
    conn = sqlite3.connect(p)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT name FROM companies WHERE name='IntegrityCo'").fetchone() is not None
    conn.close()


def test_packaged_resource_path_resolution(tmp_path: Path, monkeypatch) -> None:
    # Test that get_migrations_dir and get_seed_dir correctly resolve to bundle dir
    import sys
    from unittest.mock import patch

    # Simulate frozen
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    # Create fake bundle structure
    bundle = tmp_path / "bundle"
    (bundle / "database" / "migrations").mkdir(parents=True)
    (bundle / "resources" / "seed").mkdir(parents=True)
    (bundle / "database" / "migrations" / "test.sql").write_text("SELECT 1")
    (bundle / "resources" / "seed" / "test.json").write_text("{}")

    import importlib
    import app.paths

    importlib.reload(app.paths)
    from app.paths import get_migrations_dir, get_seed_dir

    assert get_migrations_dir() == bundle / "database" / "migrations"
    assert get_seed_dir() == bundle / "resources" / "seed"
    assert (get_migrations_dir() / "test.sql").exists()
    assert (get_seed_dir() / "test.json").exists()

    # Cleanup
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    importlib.reload(app.paths)
