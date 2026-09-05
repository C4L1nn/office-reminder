from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def get_bundle_dir() -> Path:
    """Read-only bundled resources dir (migrations, seed, icons)."""
    if is_frozen():
        # PyInstaller onefile: sys._MEIPASS, onedir: exe dir
        base = getattr(sys, "_MEIPASS", None) or Path(sys.executable).parent
        return Path(base)
    # Development: project root (one level up from app/)
    return Path(__file__).resolve().parents[1]


def get_runtime_root() -> Path:
    """Writable runtime root: %LOCALAPPDATA%/OfficeReminder (or dev fallback)."""
    # Allow override for tests
    env = os.environ.get("OFFICE_REMINDER_DATA_DIR")
    if env:
        return Path(env)
    if is_frozen():
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "OfficeReminder"
        # Fallback to user home
        return Path.home() / "OfficeReminder"
    # Development: use project data dir for convenience, but also support runtime dir via env
    # To avoid polluting project, we still use LOCALAPPDATA in dev if available and not explicitly set to project
    local = os.environ.get("LOCALAPPDATA")
    # Check if we are in packaged test mode
    if os.environ.get("OFFICE_REMINDER_USE_LOCALAPPDATA") == "1" and local:
        return Path(local) / "OfficeReminder"
    return get_bundle_dir() / "data"


def get_data_dir() -> Path:
    return get_runtime_root() / "data"


def get_database_path() -> Path:
    return get_data_dir() / "office_reminder.db"


def get_attachments_dir() -> Path:
    return get_runtime_root() / "attachments"


def get_backups_dir() -> Path:
    return get_runtime_root() / "backups"


def get_logs_dir() -> Path:
    return get_runtime_root() / "logs"


def get_lock_file_path() -> Path:
    return get_runtime_root() / "office_reminder.lock"


def get_migrations_dir() -> Path:
    # Always from bundle (read-only)
    return get_bundle_dir() / "database" / "migrations"


def get_seed_dir() -> Path:
    return get_bundle_dir() / "resources" / "seed"


def ensure_runtime_dirs() -> None:
    for p in [get_runtime_root(), get_data_dir(), get_attachments_dir(), get_backups_dir(), get_logs_dir()]:
        p.mkdir(parents=True, exist_ok=True)


# Legacy constants for backward compat (imported by old code)
APP_NAME = "Office Reminder"
# For backward compat, keep these but they now point to runtime-aware paths
try:
    DATABASE_PATH = get_database_path()
    DATA_DIR = get_data_dir()
    MIGRATIONS_DIR = get_migrations_dir()
    SEED_DIR = get_seed_dir()
    APP_DIR = get_bundle_dir()
except Exception:
    # Fallback during import errors
    APP_DIR = Path(__file__).resolve().parents[1]
    DATA_DIR = APP_DIR / "data"
    DATABASE_PATH = DATA_DIR / "office_reminder.db"
    MIGRATIONS_DIR = APP_DIR / "database" / "migrations"
    SEED_DIR = APP_DIR / "resources" / "seed"
