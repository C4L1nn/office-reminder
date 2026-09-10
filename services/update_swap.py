"""Building the new program folder, then putting it in place of the old one.

Two jobs live here, kept apart on purpose:

*Staging* assembles what the new folder should look like, from either a full
package or a difference package, without touching the installed one. It is
ordinary file work and can be tested anywhere.

*Swapping* replaces the installed folder with the staged one. Windows will not
let a running program overwrite its own files, so this half runs from a helper
process after the application has exited — see `tools/updater/updater.py`. It
is written so that every failure leaves a working program behind: the old
folder is moved aside rather than deleted, and it is only removed once the new
one is in place.
"""

from __future__ import annotations

import json
import logging
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("office_reminder.update.swap")

#: Written by the release tool into a difference package. Lists what to delete,
#: because "the files that changed" cannot express a file that went away.
DELTA_MANIFEST = "delta.json"

#: The old folder is kept under this name until the new one is in place.
OLD_SUFFIX = ".old"


class SwapError(Exception):
    """The update could not be assembled or installed."""


@dataclass(frozen=True, slots=True)
class StagedBuild:
    """A folder that is ready to become the program folder."""

    path: Path
    executable: Path
    file_count: int


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Entries that stay inside the destination when extracted.

    A package we built ourselves would never contain "..\\..\\windows", but the
    check costs nothing and this code runs with the user's own permissions on
    a folder full of executables.
    """
    members = []
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts or ":" in name:
            raise SwapError(f"Pakette güvenli olmayan yol var: {info.filename}")
        members.append(info)
    return members


def stage_full(package: Path, staging: Path) -> StagedBuild:
    """Unpack a full package into an empty staging folder."""
    staging = Path(staging)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(package) as archive:
            archive.extractall(staging, members=_safe_members(archive))
    except SwapError:
        raise
    except Exception as exc:
        raise SwapError(f"Paket açılamadı: {exc}") from exc
    return _finish(staging)


def stage_delta(package: Path, installed: Path, staging: Path) -> StagedBuild:
    """Copy the installed folder, then lay the changed files over it.

    Copying first is what makes this safe to interrupt: the installed folder is
    only ever read, and a half-built staging folder is thrown away rather than
    installed.
    """
    installed = Path(installed)
    staging = Path(staging)
    if not installed.is_dir():
        raise SwapError(f"Kurulu klasör bulunamadı: {installed}")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(installed, staging)

    try:
        with zipfile.ZipFile(package) as archive:
            members = _safe_members(archive)
            removed: list[str] = []
            if DELTA_MANIFEST in archive.namelist():
                raw = json.loads(archive.read(DELTA_MANIFEST).decode("utf-8"))
                removed = [str(entry) for entry in raw.get("removed", [])]
            archive.extractall(
                staging, members=[m for m in members if m.filename != DELTA_MANIFEST]
            )
    except SwapError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise SwapError(f"Fark paketi uygulanamadı: {exc}") from exc

    root = staging.resolve()
    for relative in removed:
        # resolve() first: `relative_to` is purely lexical, so "a/../../b"
        # passes a plain prefix check while pointing outside the folder.
        candidate = (staging / relative).resolve()
        if candidate == root or not candidate.is_relative_to(root):
            shutil.rmtree(staging, ignore_errors=True)
            raise SwapError(f"Silinecek yol paketin dışını gösteriyor: {relative}")
        if candidate.is_file():
            candidate.unlink()
        elif candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)

    return _finish(staging)


def _finish(staging: Path) -> StagedBuild:
    """Check that what was assembled actually looks like the program."""
    # A package built by tools/make_release.py has the program inside a single
    # top-level folder; unwrap it so callers always get the folder itself.
    entries = [entry for entry in staging.iterdir()]
    if len(entries) == 1 and entries[0].is_dir() and not (staging / "OfficeReminder.exe").exists():
        inner = entries[0]
        for item in list(inner.iterdir()):
            shutil.move(str(item), str(staging / item.name))
        inner.rmdir()

    executable = staging / "OfficeReminder.exe"
    if not executable.is_file():
        raise SwapError("Pakette OfficeReminder.exe yok")
    count = sum(1 for path in staging.rglob("*") if path.is_file())
    return StagedBuild(path=staging, executable=executable, file_count=count)


def can_write(target: Path) -> bool:
    """Whether the program folder can be replaced without elevation.

    A build unzipped under the user's own folder can; one installed into
    Program Files cannot, and the honest answer there is to say so rather than
    to fail halfway through.
    """
    target = Path(target)
    probe = target / ".update-write-test"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def swap(target: Path, staging: Path) -> Path:
    """Put the staged build in place of `target`, or leave `target` untouched.

    The staged folder is *copied*, not moved, because the program doing the
    copying is itself running from it — this is what lets the update happen
    without a second executable to ship and keep in step. Returns the path the
    previous folder was moved to, so the caller can delete it once the new
    build has started. Nothing is deleted here: a folder that still exists can
    be put back, a folder that has been removed cannot.
    """
    target = Path(target)
    staging = Path(staging)
    if not staging.is_dir():
        raise SwapError(f"Hazırlanan klasör yok: {staging}")
    if not (staging / "OfficeReminder.exe").is_file():
        raise SwapError("Hazırlanan klasörde OfficeReminder.exe yok")

    old = target.with_name(target.name + OLD_SUFFIX)
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
        if old.exists():
            raise SwapError(f"Önceki yedek klasör silinemedi: {old}")

    if target.exists():
        try:
            target.rename(old)
        except OSError as exc:
            # The usual cause is that the program has not finished exiting and
            # still holds a file open.
            raise SwapError(f"Kurulu klasör kilitli, taşınamadı: {exc}") from exc
    try:
        shutil.copytree(staging, target)
    except Exception as exc:
        # Put the working program back before giving up.
        shutil.rmtree(target, ignore_errors=True)
        if old.exists() and not target.exists():
            try:
                old.rename(target)
            except OSError:
                logger.error("Geri alma da başarısız: %s -> %s", old, target)
        raise SwapError(f"Yeni klasör yerine konamadı: {exc}") from exc
    return old


def rollback(target: Path, old: Path) -> None:
    """Undo a swap: throw away the new folder and put the previous one back."""
    target = Path(target)
    old = Path(old)
    if not old.is_dir():
        raise SwapError(f"Geri alınacak klasör yok: {old}")
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    old.rename(target)


def wait_for_exit(pid: int, timeout: float = 60.0, poll: float = 0.25) -> bool:
    """Block until the process leaves, or the timeout runs out.

    `os.kill(pid, 0)` is not a liveness probe on Windows — it terminates the
    process — so the handle is opened directly. A pid we cannot open is treated
    as gone, which is the safe reading: the only thing waiting protects is the
    file lock, and the swap checks that for itself anyway.
    """
    import ctypes
    import time

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return True
        kernel32.CloseHandle(handle)
        time.sleep(poll)
    return False


def write_result(update_root: Path, payload: dict) -> None:
    """Leave a note the next start can read.

    Without this a failed update is silent: the old build comes back and the
    user is left wondering whether anything happened.
    """
    try:
        Path(update_root).mkdir(parents=True, exist_ok=True)
        (Path(update_root) / "last_result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        logger.warning("Güncelleme sonucu yazılamadı", exc_info=True)


def read_result(update_root: Path) -> dict | None:
    path = Path(update_root) / "last_result.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def clear_result(update_root: Path) -> None:
    try:
        (Path(update_root) / "last_result.json").unlink(missing_ok=True)
    except OSError:
        pass


__all__ = [
    "DELTA_MANIFEST",
    "OLD_SUFFIX",
    "clear_result",
    "read_result",
    "wait_for_exit",
    "write_result",
    "StagedBuild",
    "SwapError",
    "can_write",
    "rollback",
    "stage_delta",
    "stage_full",
    "swap",
]
