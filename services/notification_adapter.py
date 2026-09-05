"""Notification delivery channels.

The domain layer never talks to a Windows API directly; it hands a
:class:`NotificationPayload` to an adapter and trusts the boolean it gets back.
That boolean is what decides whether a delivery is recorded, so an adapter must
return ``False`` — never raise, never lie — when it did not show anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("office_reminder.notifications")

DEFAULT_TIMEOUT_MS = 10_000


@dataclass(slots=True, frozen=True)
class NotificationPayload:
    title: str
    body: str
    tag: str | None = None  # for dedup / click routing


class NotificationAdapter(Protocol):
    def show(self, payload: NotificationPayload) -> bool:
        """Show the notification. True only if it was actually displayed."""
        ...

    def is_available(self) -> bool: ...


class QtTrayNotificationAdapter:
    """QSystemTrayIcon balloon message.

    On Windows 10/11 this is routed through the shell and surfaces as a real
    Windows notification (and lands in Action Center), so it is the primary
    channel rather than a fallback.
    """

    def __init__(self, tray_icon) -> None:
        self.tray_icon = tray_icon

    def is_available(self) -> bool:
        if self.tray_icon is None:
            return False
        try:
            return bool(self.tray_icon.isVisible() and self.tray_icon.supportsMessages())
        except Exception:
            return False

    def show(self, payload: NotificationPayload) -> bool:
        if not self.is_available():
            return False
        try:
            from PySide6.QtWidgets import QSystemTrayIcon

            self.tray_icon.showMessage(
                payload.title,
                payload.body,
                QSystemTrayIcon.MessageIcon.Information,
                DEFAULT_TIMEOUT_MS,
            )
            return True
        except Exception:
            logger.warning("Tray notification failed for %s", payload.tag, exc_info=True)
            return False


class WindowsToastNotificationAdapter:
    """Optional richer toast via the `windows-toasts` package, if installed.

    Not a hard dependency: the app ships without it and relies on the tray
    channel. When the package is present this gives a proper app-attributed
    toast with a multi-line body.
    """

    def __init__(self, app_id: str = "Office Reminder") -> None:
        self.app_id = app_id
        self._toaster = None
        self._checked = False

    def is_available(self) -> bool:
        if self._checked:
            return self._toaster is not None
        self._checked = True
        import platform

        if platform.system() != "Windows":
            return False
        try:
            from windows_toasts import WindowsToaster  # type: ignore

            self._toaster = WindowsToaster(self.app_id)
        except Exception:
            self._toaster = None
        return self._toaster is not None

    def show(self, payload: NotificationPayload) -> bool:
        if not self.is_available():
            return False
        try:
            from windows_toasts import Toast  # type: ignore

            toast = Toast()
            toast.text_fields = [payload.title, payload.body]
            self._toaster.show_toast(toast)
            return True
        except Exception:
            logger.warning("Windows toast failed for %s", payload.tag, exc_info=True)
            return False


class CompositeNotificationAdapter:
    """Try the primary channel, fall back to the secondary one."""

    def __init__(self, primary: NotificationAdapter, fallback: NotificationAdapter) -> None:
        self.primary = primary
        self.fallback = fallback

    def is_available(self) -> bool:
        return self.primary.is_available() or self.fallback.is_available()

    def show(self, payload: NotificationPayload) -> bool:
        if self.primary.is_available() and self.primary.show(payload):
            return True
        return self.fallback.show(payload)


class NullNotificationAdapter:
    """Used when no channel exists (headless tests, tray unavailable)."""

    def is_available(self) -> bool:
        return False

    def show(self, payload: NotificationPayload) -> bool:
        return False


class RecordingNotificationAdapter:
    """Test double that records what would have been shown."""

    def __init__(self, succeed: bool = True) -> None:
        self.succeed = succeed
        self.shown: list[NotificationPayload] = []

    def is_available(self) -> bool:
        return True

    def show(self, payload: NotificationPayload) -> bool:
        if not self.succeed:
            return False
        self.shown.append(payload)
        return True
