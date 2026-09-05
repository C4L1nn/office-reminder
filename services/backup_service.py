from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger("office_reminder.backup")


class BackupService:
    def __init__(self, database_path: Path, backup_dir: Path, retention_days: int = 30) -> None:
        self.database_path = Path(database_path)
        self.backup_dir = Path(backup_dir)
        self.retention_days = retention_days

    def _today_backup_path(self) -> Path:
        # Use date-based name for once-per-day: office_reminder_2026-09-03.db
        today = date.today().isoformat()
        return self.backup_dir / f"office_reminder_{today}.db"

    def _has_today_backup(self) -> bool:
        return self._today_backup_path().exists()

    def create_backup(self, force: bool = False) -> Path | None:
        """Create backup via SQLite backup API (safe for WAL). Returns path or None if already exists today and not forced."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        if not force and self._has_today_backup():
            return None  # already backed up today

        # Use date-based name, but if forced and exists, use timestamp to avoid overwrite
        if force and self._has_today_backup():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = self.backup_dir / f"office_reminder_{stamp}.db"
        else:
            target = self._today_backup_path()

        # Use SQLite backup API
        # Ensure source exists
        if not self.database_path.exists():
            raise FileNotFoundError(f"Database not found: {self.database_path}")

        # Use sqlite3 backup
        src = sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=10)
        dst = sqlite3.connect(target, timeout=10)
        try:
            src.backup(dst, pages=100)
        finally:
            dst.close()
            src.close()

        # Verify integrity of backup
        self._verify_backup(target)

        # Apply retention
        self._apply_retention()

        return target

    def create_backup_if_needed(self) -> Path | None:
        """Idempotent daily backup — only once per day."""
        return self.create_backup(force=False)

    def _verify_backup(self, backup_path: Path) -> None:
        conn = sqlite3.connect(backup_path)
        try:
            cur = conn.execute("PRAGMA integrity_check")
            row = cur.fetchone()
            if row is None or row[0] != "ok":
                raise ValueError(f"Backup integrity check failed for {backup_path}: {row}")
            # Also check that we can read some data
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()

    def _apply_retention(self) -> None:
        """Keep the newest `retention_days` backups and delete the rest."""
        try:
            files = sorted(
                self.backup_dir.glob("office_reminder_*.db"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            logger.warning("Backup directory could not be listed: %s", self.backup_dir, exc_info=True)
            return
        for old in files[self.retention_days :]:
            try:
                old.unlink()
            except OSError:
                # A backup held open by antivirus or a file browser is skipped
                # this round and removed on the next one.
                logger.info("Old backup could not be removed yet: %s", old.name)

    def list_backups(self) -> list[Path]:
        if not self.backup_dir.exists():
            return []
        return sorted(self.backup_dir.glob("office_reminder_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)

    def get_last_backup_time(self) -> datetime | None:
        backups = self.list_backups()
        if not backups:
            return None
        try:
            return datetime.fromtimestamp(backups[0].stat().st_mtime)
        except Exception:
            return None
