"""Windows autostart: the HKCU Run entry that starts the program at sign-in.

Current-user only, no administrator rights, idempotent.

Only a packaged build may write the entry. On 2026-09-11 an office machine
booted into the source tree: a run of `python main.py` under a stray Python
3.13 had ticked "Windows açıldığında başlat", the entry pointed at that
interpreter, and every sign-in opened a console window over the development
database instead of the office's real data. A source checkout is never what
should start with Windows, so from source the entry is simply not written.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Callable, Protocol


class AutostartStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class RegistryAutostartStore:
    """Windows HKCU Run registry store."""

    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "OfficeReminder"

    def _key(self):
        import winreg

        return winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_READ | winreg.KEY_WRITE
        )

    def get(self, name: str) -> str | None:
        if os.name != "nt":
            return None
        try:
            import winreg

            with self._key() as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def set(self, name: str, value: str) -> None:
        if os.name != "nt":
            return
        import winreg

        with self._key() as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        if os.name != "nt":
            return
        try:
            import winreg

            with self._key() as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass
        except Exception:
            pass


class MemoryAutostartStore:
    """In-memory store for tests / non-Windows."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._data.get(name)

    def set(self, name: str, value: str) -> None:
        self._data[name] = value

    def delete(self, name: str) -> None:
        self._data.pop(name, None)


class StartupUnavailable(Exception):
    """This build cannot register itself to start with Windows."""


def _get_executable_command(background: bool = False) -> str | None:
    """The command that starts *this* program, or None when there is none.

    Packaged: `"C:/.../OfficeReminder.exe" --background`. From source there is
    deliberately no answer: whichever interpreter happens to be running is not
    a program anyone installed, and its data folder is the development one.
    """
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    return f'"{exe}"' + (" --background" if background else "")


_QUOTED = re.compile(r'^\s*"([^"]+)"')


def _program_of(command: str | None) -> str | None:
    """The executable a Run entry launches, normalised for comparison."""
    if not command:
        return None
    match = _QUOTED.match(command)
    program = match.group(1) if match else command.strip().split(" ")[0]
    if not program:
        return None
    # Windows paths compare case-insensitively and with either slash.
    return os.path.normcase(os.path.normpath(program))


class StartupService:
    """Windows autostart (HKCU Run) — current-user, no admin, idempotent."""

    def __init__(
        self,
        store: AutostartStore | None = None,
        command: Callable[[bool], str | None] | None = None,
    ) -> None:
        if store is not None:
            self.store = store
        else:
            if os.name == "nt":
                try:
                    self.store = RegistryAutostartStore()
                except Exception:
                    self.store = MemoryAutostartStore()
            else:
                self.store = MemoryAutostartStore()
        self.app_name = RegistryAutostartStore.APP_NAME
        # Injectable so tests can stand in for a packaged build; the default
        # refuses from source.
        self._command = command or _get_executable_command

    def available(self) -> bool:
        """Whether this build may register itself at all."""
        return self._command(True) is not None

    def get_command(self) -> str | None:
        return self.store.get(self.app_name)

    def is_enabled(self) -> bool:
        """True only when the entry starts *this* program.

        The previous check accepted any value containing "OfficeReminder" or
        "main.py", so a packaged build showed autostart as on while the entry
        actually launched a source checkout.
        """
        own = _program_of(self._command(True))
        return own is not None and _program_of(self.get_command()) == own

    def points_elsewhere(self) -> str | None:
        """The stored command when an entry exists but starts something else."""
        current = self.get_command()
        if not current or self.is_enabled():
            return None
        return current

    def enable(self, background: bool = True) -> None:
        command = self._command(background)
        if command is None:
            raise StartupUnavailable(
                "Kaynak koddan çalışırken Windows başlangıcına eklenmez; "
                "bu ayarı paketlenmiş uygulamadan (OfficeReminder.exe) yapın."
            )
        if self.get_command() != command:
            self.store.set(self.app_name, command)

    def disable(self) -> None:
        # Removes the entry whatever it points at: the name is ours, and a user
        # who unticks the box expects nothing to start.
        self.store.delete(self.app_name)

    def set_enabled(self, enabled: bool, background: bool = True) -> None:
        if enabled:
            # Also repairs an entry that points at another copy of the program.
            self.enable(background=background)
        else:
            self.disable()
