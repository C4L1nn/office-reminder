"""Application settings, kept in SQLite so every layer reads the same value.

The UI never touches `app_settings` (or any other table) directly; it asks this
service. QSettings is reserved for pure window-chrome state such as geometry.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from database.connection import Database

logger = logging.getLogger("office_reminder.settings")

NOTIFICATIONS_ENABLED = "notifications.enabled"
NOTIFICATION_OFFSETS = "notifications.default_offsets"
CHECK_INTERVAL_MINUTES = "notifications.check_interval_minutes"
STARTUP_ENABLED = "startup.enabled"
STARTUP_BACKGROUND = "startup.background"
MINIMIZE_TO_TRAY = "window.minimize_to_tray"
BACKUP_ENABLED = "backup.enabled"
BACKUP_RETENTION_DAYS = "backup.retention_days"
APPEARANCE_THEME = "appearance.theme"
MINI_COUNTER_ENABLED = "mini_counter.enabled"

#: "system" follows the Windows colour mode; the other two override it.
THEME_CHOICES = ("system", "light", "dark")

_DEFAULTS: dict[str, str] = {
    NOTIFICATIONS_ENABLED: "true",
    NOTIFICATION_OFFSETS: "[14,7,3,1,0]",
    CHECK_INTERVAL_MINUTES: "15",
    STARTUP_ENABLED: "false",
    STARTUP_BACKGROUND: "true",
    MINIMIZE_TO_TRAY: "true",
    BACKUP_ENABLED: "true",
    BACKUP_RETENTION_DAYS: "30",
    APPEARANCE_THEME: "system",
    MINI_COUNTER_ENABLED: "false",
}

_TRUE = {"1", "true", "yes", "on"}


@dataclass(slots=True, frozen=True)
class AppSettings:
    notifications_enabled: bool
    minimize_to_tray: bool
    start_with_windows: bool
    start_in_background: bool
    check_interval_minutes: int
    backup_enabled: bool
    backup_retention_days: int
    default_offsets: list[int]


class SettingsService:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ------------------------------------------------------------------ primitives
    def get(self, key: str, default: str | None = None) -> str | None:
        with self.database.session() as connection:
            row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if row is not None:
            return row["value"]
        return default if default is not None else _DEFAULTS.get(key)

    def set(self, key: str, value: str) -> None:
        with self.database.session() as connection:
            connection.execute(
                "INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                (key, value),
            )

    def get_theme(self) -> str:
        """The stored appearance choice, falling back to following Windows."""
        value = (self.get(APPEARANCE_THEME) or "system").strip().lower()
        return value if value in THEME_CHOICES else "system"

    def set_theme(self, value: str) -> None:
        if value not in THEME_CHOICES:
            raise ValueError(f"Bilinmeyen tema: {value}")
        self.set(APPEARANCE_THEME, value)

    def get_bool(self, key: str) -> bool:
        raw = self.get(key)
        return str(raw).strip().lower() in _TRUE

    def set_bool(self, key: str, value: bool) -> None:
        self.set(key, "true" if value else "false")

    def get_int(self, key: str, minimum: int | None = None, maximum: int | None = None) -> int:
        raw = self.get(key)
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            value = int(_DEFAULTS.get(key, "0"))
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def get_json(self, key: str, fallback: Any) -> Any:
        raw = self.get(key)
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except ValueError:
            logger.warning("Setting %s is not valid JSON, using fallback", key)
            return fallback

    # ------------------------------------------------------------------ facade
    def load(self) -> AppSettings:
        offsets = self.get_json(NOTIFICATION_OFFSETS, [14, 7, 3, 1, 0])
        if not isinstance(offsets, list) or not all(isinstance(o, int) for o in offsets):
            offsets = [14, 7, 3, 1, 0]
        return AppSettings(
            notifications_enabled=self.get_bool(NOTIFICATIONS_ENABLED),
            minimize_to_tray=self.get_bool(MINIMIZE_TO_TRAY),
            start_with_windows=self.get_bool(STARTUP_ENABLED),
            start_in_background=self.get_bool(STARTUP_BACKGROUND),
            check_interval_minutes=self.get_int(CHECK_INTERVAL_MINUTES, minimum=1, maximum=24 * 60),
            backup_enabled=self.get_bool(BACKUP_ENABLED),
            backup_retention_days=self.get_int(BACKUP_RETENTION_DAYS, minimum=1, maximum=365),
            default_offsets=sorted(set(offsets), reverse=True),
        )

    def set_notifications_enabled(self, enabled: bool) -> None:
        self.set_bool(NOTIFICATIONS_ENABLED, enabled)

    def set_minimize_to_tray(self, enabled: bool) -> None:
        self.set_bool(MINIMIZE_TO_TRAY, enabled)

    def set_start_with_windows(self, enabled: bool) -> None:
        self.set_bool(STARTUP_ENABLED, enabled)

    def set_start_in_background(self, enabled: bool) -> None:
        self.set_bool(STARTUP_BACKGROUND, enabled)
