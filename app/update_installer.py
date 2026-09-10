"""The half of the update that runs after the application has exited.

Reached only through `main.py --apply-update`, and only from the *staged*
build: the program folder being replaced cannot be replaced by something
running inside it, and the staged folder sits outside it. That is also why
there is no second executable to build and keep in step with this one — the
new version installs itself.

Nothing here imports Qt. It runs before any of that, so a broken UI cannot
stop an update from completing or from being rolled back.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from services.update_swap import (
    SwapError,
    rollback,
    swap,
    wait_for_exit,
    write_result,
)

logger = logging.getLogger("office_reminder.update.install")

#: How long to wait for the old process to let go of its files.
EXIT_TIMEOUT_SECONDS = 60.0


def _log_path(update_root: Path) -> Path:
    update_root.mkdir(parents=True, exist_ok=True)
    return update_root / "update.log"


def _note(update_root: Path, message: str) -> None:
    """Append to a plain text log.

    The application's own logging goes to the runtime folder and is set up by
    code we deliberately do not reach here, so this writes directly. When an
    update fails on a machine three hundred kilometres away, this file is the
    only account of what happened.
    """
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n"
    try:
        with _log_path(update_root).open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
    print(line.rstrip(), file=sys.stderr)


def apply_update(
    target: Path,
    staging: Path,
    update_root: Path,
    wait_pid: int | None = None,
    version: str = "",
    relaunch: bool = True,
) -> int:
    """Replace `target` with `staging` and start the result.

    Returns a process exit code: 0 when the new build is in place, 1 when the
    previous one was put back. Every path through this function ends with a
    working program in `target` — that is the whole contract.
    """
    target = Path(target)
    staging = Path(staging)
    update_root = Path(update_root)
    _note(update_root, f"--- güncelleme başlıyor: {version or '?'} -> {target}")

    if wait_pid:
        if wait_for_exit(wait_pid, timeout=EXIT_TIMEOUT_SECONDS):
            _note(update_root, f"önceki süreç kapandı (pid {wait_pid})")
        else:
            # Carrying on would fail at the rename with the files still locked;
            # stopping here leaves the running program untouched.
            _note(update_root, f"pid {wait_pid} {EXIT_TIMEOUT_SECONDS:.0f} sn içinde kapanmadı, vazgeçildi")
            write_result(
                update_root,
                {
                    "status": "aborted",
                    "version": version,
                    "message": "Program kapanmadığı için güncelleme uygulanmadı.",
                    "at": datetime.now().isoformat(timespec="seconds"),
                },
            )
            return 1

    try:
        old = swap(target, staging)
        _note(update_root, f"takas tamam, önceki sürüm: {old.name}")
    except SwapError as exc:
        _note(update_root, f"TAKAS BAŞARISIZ: {exc}")
        write_result(
            update_root,
            {
                "status": "failed",
                "version": version,
                "message": f"Güncelleme uygulanamadı: {exc}",
                "at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        if relaunch:
            _relaunch(target, update_root)
        return 1

    executable = target / "OfficeReminder.exe"
    if not executable.is_file():
        # swap() checks this before copying, so reaching here means the copy
        # itself lost something. Put the working build back.
        _note(update_root, "yeni klasörde exe yok, geri alınıyor")
        try:
            rollback(target, old)
            _note(update_root, "geri alma tamam")
        except SwapError as exc:
            _note(update_root, f"GERİ ALMA BAŞARISIZ: {exc}")
        write_result(
            update_root,
            {
                "status": "rolled_back",
                "version": version,
                "message": "Yeni sürüm eksik geldi, önceki sürüm geri yüklendi.",
                "at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        if relaunch:
            _relaunch(target, update_root)
        return 1

    write_result(
        update_root,
        {
            "status": "installed",
            "version": version,
            "previous": str(old),
            "staging": str(staging),
            "at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    _note(update_root, f"güncelleme tamamlandı: {version or '?'}")
    if relaunch:
        _relaunch(target, update_root)
    return 0


def _relaunch(target: Path, update_root: Path) -> None:
    executable = Path(target) / "OfficeReminder.exe"
    if not executable.is_file():
        _note(update_root, f"başlatılacak exe yok: {executable}")
        return
    try:
        # Detached: this helper is about to exit and must not keep the new
        # process as a child that dies with it.
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [str(executable)],
            cwd=str(target),
            creationflags=flags,
            close_fds=True,
        )
        _note(update_root, f"başlatıldı: {executable}")
    except Exception as exc:
        _note(update_root, f"BAŞLATILAMADI: {exc}")


__all__ = ["EXIT_TIMEOUT_SECONDS", "apply_update"]
