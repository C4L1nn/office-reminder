"""Bir güncellemeyi indirmekten kurulumu başlatmaya kadar olan sıra.

Kararı kullanıcı verir; burası yalnızca "evet" dendikten sonrasını yürütür ve
her adımda geri dönülebilir bir noktada durur. Sıra bilerek şu biçimde:

    yazılabilir mi -> indir -> özet doğrula -> klasörü hazırla
    -> yeni yapıyı kendi kum havuzunda selftest'ten geçir
    -> veritabanını yedekle -> kurulumu başlat -> uygulamadan çık

Selftest kapısı ile yedek adımı yer değiştiremez: yedek, kurulum başlamadan
önceki son güvenli an. Migration'lar tek yönlü olduğu için, yeni sürüm şemayı
değiştirdikten sonra eskiye dönmenin yolu `.old` klasörü değil, o yedektir.

Bu modül Qt bilmez. Uzun süren işler `sync_worker` üzerinden çağrılır ve
sonuçları arayüze `application.py` taşır.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from services.update_service import Package, Release, UpdateError, UpdateService, update_dir
from services.update_swap import can_write, stage_delta, stage_full

logger = logging.getLogger("office_reminder.update.flow")

#: Yeni yapının kendini sınaması için verilen süre. Selftest migration
#: uygular ve GİB seed'ini yükler; yavaş bir diskte bile bunun altında biter.
GATE_TIMEOUT_SECONDS = 180


class UpdateBlocked(Exception):
    """Güncelleme bu makinede yapılamaz; sebebi kullanıcıya söylenir."""


@dataclass(frozen=True, slots=True)
class Prepared:
    """Kurulmaya hazır, sınavını geçmiş yapı."""

    staging: Path
    version: str
    update_root: Path
    target: Path


def program_dir() -> Path:
    """Değiştirilecek klasör: exe'nin durduğu yer."""
    return Path(sys.executable).parent


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def check_installable(target: Path | None = None) -> Path:
    """Kurulumun mümkün olduğunu baştan söyler, yarısında değil."""
    if not is_frozen():
        raise UpdateBlocked(
            "Kaynaktan çalışırken güncelleme kurulmaz; `git pull` kullanın."
        )
    target = Path(target) if target else program_dir()
    if not (target / "OfficeReminder.exe").is_file():
        raise UpdateBlocked(f"Program klasörü tanınmadı: {target}")
    if not can_write(target):
        raise UpdateBlocked(
            f"Program klasörüne yazılamıyor: {target}\n\n"
            "Uygulama yönetici izni isteyen bir konuma kurulmuş olabilir. "
            "Yeni sürümü elle indirip kurmanız gerekiyor."
        )
    return target


def prepare(
    service: UpdateService,
    release: Release,
    package: Package,
    target: Path | None = None,
    root: Path | None = None,
    progress=None,
) -> Prepared:
    """İndir, doğrula, klasörü kur ve yeni yapıya kendini sınat.

    Buraya kadar kurulu sürüme hiç dokunulmaz: her şey `update/` altında olur,
    bu yüzden hangi adımda durursa dursun çalışan program yerinde kalır.
    """
    target = check_installable(target)
    root = update_dir(root)
    staging = root / "staging"

    package_path = root / f"OfficeReminder-{release.version_text}-{package.kind}.zip"
    service.download(package, package_path, progress=progress)

    if package.kind == "delta":
        staged = stage_delta(package_path, target, staging)
    else:
        staged = stage_full(package_path, staging)
    logger.info("Staged %s files for %s", staged.file_count, release.version_text)

    _gate(staged.executable)

    # Paket açıldı ve sınavını geçti; kopyası artık diskte yer kaplamasın.
    package_path.unlink(missing_ok=True)
    return Prepared(
        staging=staged.path, version=release.version_text, update_root=root, target=target
    )


def _gate(executable: Path) -> None:
    """Yeni yapıyı, kendi geçici veri klasöründe `--selftest`'ten geçirir.

    Kum havuzu şart: selftest migration uygular. Gerçek veritabanına karşı
    koşturmak, kullanıcı henüz güncellemeye razı olmadan şemayı değiştirmek
    olurdu — ve vazgeçilirse eski sürüm tanımadığı bir şemayla kalırdı.
    """
    sandbox = Path(tempfile.mkdtemp(prefix="or-gate-"))
    try:
        result = subprocess.run(
            [str(executable), "--selftest", f"--data-dir={sandbox}"],
            capture_output=True,
            timeout=GATE_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise UpdateError(
            "Yeni sürüm kendini sınarken yanıt vermedi; güncelleme yapılmadı."
        ) from None
    except OSError as exc:
        raise UpdateError(f"Yeni sürüm çalıştırılamadı: {exc}") from exc
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    if result.returncode != 0:
        tail = (result.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        detail = "\n".join(tail[-6:]) if tail else f"çıkış kodu {result.returncode}"
        raise UpdateError(f"Yeni sürüm kendi sınamasından geçemedi:\n{detail}")
    logger.info("Update gate passed for %s", executable)


def launch_installer(prepared: Prepared) -> None:
    """Kurulumu başlatır. Çağıran hemen ardından uygulamadan çıkmalıdır.

    Kurulumu hazırlanan klasörün exe'si yapar; o klasör hedefin dışında
    olduğu için hedefi değiştirebilir. Bizim pid'imizi bekler, yani dosya
    kilitleri bırakılmadan hiçbir şeye dokunmaz.
    """
    executable = prepared.staging / "OfficeReminder.exe"
    command = [
        str(executable),
        "--apply-update",
        f"--target={prepared.target}",
        f"--staging={prepared.staging}",
        f"--update-root={prepared.update_root}",
        f"--wait-pid={os.getpid()}",
        f"--version={prepared.version}",
    ]
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        command,
        cwd=str(prepared.staging),
        creationflags=flags,
        close_fds=True,
    )
    logger.info("Installer launched for %s", prepared.version)


def cleanup(target: Path | None = None, root: Path | None = None) -> None:
    """Bir önceki güncellemenin artıklarını toplar.

    Açılışta çağrılır: bu noktada yeni sürüm çalışıyor demektir, yani `.old`
    klasörünün ve hazırlık klasörünün işi bitmiştir. Silinemezlerse sorun
    değil, bir sonraki açılışta yine denenir.
    """
    target = Path(target) if target else program_dir()
    old = target.with_name(target.name + ".old")
    if old.is_dir():
        shutil.rmtree(old, ignore_errors=True)
        logger.info("Removed previous build: %s", old)
    try:
        staging = update_dir(root) / "staging"
    except OSError:
        return
    if staging.is_dir():
        shutil.rmtree(staging, ignore_errors=True)


__all__ = [
    "GATE_TIMEOUT_SECONDS",
    "Prepared",
    "UpdateBlocked",
    "check_installable",
    "cleanup",
    "is_frozen",
    "launch_installer",
    "prepare",
    "program_dir",
]
