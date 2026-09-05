from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile


class SingleInstanceGuard:
    """Ensures only one OfficeReminder instance per Windows session.

    Uses QLockFile in the runtime dir. Second instance will fail to acquire
    and should exit gracefully. The lock is held for the lifetime of the app.
    """

    def __init__(self, lock_path: Path | None = None) -> None:
        from app.paths import get_lock_file_path

        self.lock_path = Path(lock_path) if lock_path else get_lock_file_path()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(self.lock_path))
        # Stale lock detection: QLockFile handles it
        self._lock.setStaleLockTime(0)

    def try_acquire(self) -> bool:
        """Try to acquire lock. Returns True if this is the first instance."""
        # Try to lock, 0 timeout
        if self._lock.tryLock(100):
            return True
        return False

    def is_locked(self) -> bool:
        return self._lock.isLocked()

    def unlock(self) -> None:
        """Release the lock. Safe to call twice and during interpreter teardown."""
        try:
            self._lock.unlock()
        except RuntimeError:
            # The Qt object may already be gone while shutting down.
            pass

    def __del__(self) -> None:
        try:
            self.unlock()
        except Exception:
            pass
