from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Protocol


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


def _get_executable_command(background: bool = False) -> str:
    """Return the command to launch OfficeReminder.

    For packaged exe: "C:\...\OfficeReminder.exe" [--background]
    For dev: "C:\...\python.exe" "C:\...\main.py" [--background]
    """
    bg = " --background" if background else ""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        # Quote if spaces
        return f'"{exe}"{bg}'
    # Development: use python + main.py
    py = Path(sys.executable).resolve()
    # Find main.py via bundle dir
    try:
        from app.paths import get_bundle_dir

        main_py = get_bundle_dir() / "main.py"
    except Exception:
        main_py = Path(__file__).resolve().parents[1] / "main.py"
    return f'"{py}" "{main_py}"{bg}'


class StartupService:
    """Windows autostart (HKCU Run) — current-user, no admin, idempotent."""

    def __init__(self, store: AutostartStore | None = None) -> None:
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

    def is_enabled(self) -> bool:
        val = self.store.get(self.app_name)
        if not val:
            return False
        # Consider enabled if value contains OfficeReminder (or python+main)
        # Also check if stale (path no longer exists) — then treat as disabled
        # We check if the executable part exists
        try:
            # Extract quoted exe path
            import shlex

            # Simple: if frozen path, check exe exists; if dev, check main.py exists
            # For now, just check that value is non-empty and contains OfficeReminder or main.py
            if "OfficeReminder" in val or "main.py" in val:
                return True
            return False
        except Exception:
            return bool(val)

    def enable(self, background: bool = True) -> None:
        cmd = _get_executable_command(background=background)
        self.store.set(self.app_name, cmd)

    def disable(self) -> None:
        self.store.delete(self.app_name)

    def set_enabled(self, enabled: bool, background: bool = True) -> None:
        if enabled:
            # Idempotent: if already enabled with same command, no change needed
            current = self.store.get(self.app_name)
            desired = _get_executable_command(background=background)
            if current == desired:
                return
            # Also fix stale path: if enabled but path is stale, update
            self.enable(background=background)
        else:
            self.disable()

    def get_command(self) -> str | None:
        return self.store.get(self.app_name)
