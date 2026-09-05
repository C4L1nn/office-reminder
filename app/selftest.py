"""Headless verification of a build's storage and bundled resources.

Run as `OfficeReminder.exe --selftest`. It exercises the parts a packaged build
most often gets wrong — missing migrations, a missing seed file, an unwritable
runtime directory — and reports them without needing a desktop session.
Exit code 0 means the build is sound.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime

CHECK_MARK = "OK  "
CROSS = "FAIL"


def run_selftest() -> int:
    from app.paths import (
        ensure_runtime_dirs,
        get_bundle_dir,
        get_database_path,
        get_migrations_dir,
        get_runtime_root,
        get_seed_dir,
        is_frozen,
    )
    from app.version import APP_NAME, APP_VERSION

    # Paths and Turkish labels must survive a legacy console codepage.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    failures: list[str] = []
    # A windowed build has no console, so the report is also written to a file
    # the checklist can read back.
    transcript: list[str] = []

    def say(line: str) -> None:
        transcript.append(line)
        print(line)

    def check(label: str, ok: bool, detail: str = "") -> None:
        say(f"[{CHECK_MARK if ok else CROSS}] {label}{(' — ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    def finish(code: int) -> int:
        say("-" * 60)
        say("SELFTEST PASSED" if code == 0 else f"SELFTEST FAILED: {', '.join(failures) or 'setup'}")
        try:
            report = get_runtime_root() / "selftest.txt"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("\n".join(transcript) + "\n", encoding="utf-8")
        except OSError:
            pass
        return code

    say(f"{APP_NAME} {APP_VERSION} selftest — {datetime.now():%Y-%m-%d %H:%M:%S}")
    say(f"frozen={is_frozen()}  bundle={get_bundle_dir()}")
    say(f"runtime={get_runtime_root()}")
    say("-" * 60)

    migrations_dir = get_migrations_dir()
    migration_files = sorted(migrations_dir.glob("*.sql")) if migrations_dir.exists() else []
    check("bundled migrations", bool(migration_files), f"{len(migration_files)} dosya")

    seed_file = get_seed_dir() / "official_calendar_2026.json"
    check("bundled GİB seed", seed_file.exists(), str(seed_file.name))

    try:
        ensure_runtime_dirs()
        writable = True
        detail = str(get_runtime_root())
    except OSError as exc:
        writable, detail = False, str(exc)
    check("runtime dizini yazılabilir", writable, detail)

    if not (migration_files and writable):
        return finish(1)

    from database.connection import Database
    from database.migrations import MigrationRunner

    database = Database(get_database_path())
    try:
        applied = MigrationRunner(database, migrations_dir).run()
        check("migration", True, f"{len(applied)} uygulandı, şema güncel")
    except Exception as exc:
        check("migration", False, str(exc))
        return finish(1)

    if seed_file.exists():
        from services.official_calendar_service import OfficialCalendarSeedService

        try:
            inserted = OfficialCalendarSeedService(database, get_seed_dir()).import_seed(
                "official_calendar_2026.json"
            )
            check("GİB takvimi", True, f"{inserted} yeni kayıt")
        except Exception as exc:
            check("GİB takvimi", False, str(exc))

    from services.holiday_service import HolidayService
    from services.sgk_calendar_service import SgkCalendarService

    try:
        count = SgkCalendarService(database, HolidayService(database)).generate_and_import(
            2026, wage_periods=["MONTHLY_1_END", "MONTHLY_15_14"]
        )
        check("SGK kural takvimi", True, f"{count} yeni kayıt")
    except Exception as exc:
        check("SGK kural takvimi", False, str(exc))

    connection = sqlite3.connect(get_database_path())
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        check("integrity_check", integrity == "ok", integrity)
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        check("foreign_key_check", not foreign_keys, f"{len(foreign_keys)} ihlal")
        events = connection.execute("SELECT COUNT(*) FROM official_calendar_events").fetchone()[0]
        check("resmî takvim kayıtları", events > 0, str(events))
        types = connection.execute("SELECT COUNT(*) FROM obligation_types").fetchone()[0]
        check("yükümlülük türleri", types > 0, str(types))
    finally:
        connection.close()

    try:
        from PySide6.QtSvg import QSvgRenderer  # noqa: F401

        check("QtSvg (ikonlar)", True)
    except Exception as exc:
        check("QtSvg (ikonlar)", False, str(exc))

    try:
        from PySide6.QtPdf import QPdfDocument  # noqa: F401

        check("QtPdf (SGK ekleri)", True)
    except Exception as exc:
        check("QtPdf (SGK ekleri)", False, str(exc))

    # Export is a bundled third-party dependency, so a packaging mistake must
    # surface here rather than the first time someone tries to save a list.
    try:
        from openpyxl import Workbook  # noqa: F401

        check("openpyxl (Excel dışa aktarma)", True)
    except Exception as exc:
        check("openpyxl (Excel dışa aktarma)", False, str(exc))

    return finish(1 if failures else 0)


if __name__ == "__main__":  # pragma: no cover - manual use
    sys.exit(run_selftest())
