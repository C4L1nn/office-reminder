"""Yeni klasörü hazırlama ve yerine koyma.

Buradaki her testin arkasındaki soru aynı: bir şey ters giderse kullanıcının
elinde çalışan bir program kalıyor mu? Takas, silme değil taşıma üzerine
kurulu; eski klasör yenisi yerine oturana kadar duruyor.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from services.update_swap import (
    DELTA_MANIFEST,
    SwapError,
    can_write,
    rollback,
    stage_delta,
    stage_full,
    swap,
)


def _installed(root: Path, version: str = "1.0.0") -> Path:
    """Kurulu paketi taklit eden bir klasör."""
    folder = root / "OfficeReminder"
    (folder / "_internal" / "PySide6").mkdir(parents=True)
    (folder / "OfficeReminder.exe").write_text(f"exe {version}", encoding="utf-8")
    (folder / "_internal" / "base_library.zip").write_text(f"lib {version}", encoding="utf-8")
    (folder / "_internal" / "PySide6" / "Qt6Core.dll").write_text("qt", encoding="utf-8")
    (folder / "_internal" / "eski_eklenti.dll").write_text("gidecek", encoding="utf-8")
    return folder


def _full_package(path: Path, version: str, wrapped: bool = True) -> Path:
    prefix = "OfficeReminder/" if wrapped else ""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{prefix}OfficeReminder.exe", f"exe {version}")
        archive.writestr(f"{prefix}_internal/base_library.zip", f"lib {version}")
        archive.writestr(f"{prefix}_internal/PySide6/Qt6Core.dll", "qt")
    return path


def _delta_package(path: Path, version: str, removed: list[str] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("OfficeReminder.exe", f"exe {version}")
        archive.writestr("_internal/base_library.zip", f"lib {version}")
        archive.writestr(DELTA_MANIFEST, json.dumps({"removed": removed or []}))
    return path


# ------------------------------------------------------------------ hazırlama
def test_tam_paket_acilir(tmp_path: Path) -> None:
    package = _full_package(tmp_path / "full.zip", "1.1.0")
    staged = stage_full(package, tmp_path / "staging")
    assert staged.executable.read_text(encoding="utf-8") == "exe 1.1.0"
    assert (staged.path / "_internal" / "PySide6" / "Qt6Core.dll").exists()


def test_tek_klasore_sarilmamis_paket_de_acilir(tmp_path: Path) -> None:
    package = _full_package(tmp_path / "full.zip", "1.1.0", wrapped=False)
    staged = stage_full(package, tmp_path / "staging")
    assert staged.executable.is_file()


def test_exe_icermeyen_paket_reddedilir(tmp_path: Path) -> None:
    path = tmp_path / "bos.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("okuma.txt", "merhaba")
    with pytest.raises(SwapError, match="OfficeReminder.exe"):
        stage_full(path, tmp_path / "staging")


def test_disari_cikan_yol_reddedilir(tmp_path: Path) -> None:
    """Kendi paketimizde olmaz ama kontrolün bedeli yok."""
    path = tmp_path / "kotu.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../disarida.txt", "olmaz")
    with pytest.raises(SwapError, match="güvenli olmayan"):
        stage_full(path, tmp_path / "staging")


def test_fark_paketi_kurulu_klasorun_uzerine_serilir(tmp_path: Path) -> None:
    installed = _installed(tmp_path)
    package = _delta_package(tmp_path / "delta.zip", "1.1.0")
    staged = stage_delta(package, installed, tmp_path / "staging")

    # Değişen dosyalar yenilendi.
    assert staged.executable.read_text(encoding="utf-8") == "exe 1.1.0"
    # Değişmeyen dosya kurulu klasörden geldi, indirilmedi.
    assert (staged.path / "_internal" / "PySide6" / "Qt6Core.dll").read_text(encoding="utf-8") == "qt"
    # Kurulu klasöre dokunulmadı.
    assert installed.joinpath("OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"


def test_fark_paketi_kaldirilan_dosyayi_siler(tmp_path: Path) -> None:
    """'Değişen dosyalar' listesi, ortadan kalkan bir dosyayı anlatamaz."""
    installed = _installed(tmp_path)
    package = _delta_package(
        tmp_path / "delta.zip", "1.1.0", removed=["_internal/eski_eklenti.dll"]
    )
    staged = stage_delta(package, installed, tmp_path / "staging")
    assert not (staged.path / "_internal" / "eski_eklenti.dll").exists()
    assert (installed / "_internal" / "eski_eklenti.dll").exists()


def test_silme_listesi_klasor_disini_gosteremez(tmp_path: Path) -> None:
    installed = _installed(tmp_path)
    package = _delta_package(tmp_path / "delta.zip", "1.1.0", removed=["../../onemli.txt"])
    with pytest.raises(SwapError, match="dışını"):
        stage_delta(package, installed, tmp_path / "staging")


# ---------------------------------------------------------------------- takas
def test_takas_eskiyi_silmez_yana_alir(tmp_path: Path) -> None:
    installed = _installed(tmp_path)
    staged = stage_full(_full_package(tmp_path / "full.zip", "1.1.0"), tmp_path / "staging")
    old = swap(installed, staged.path)

    assert installed.joinpath("OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.1.0"
    assert old.is_dir(), "eski klasör silinmiş; geri dönülecek yer kalmaz"
    assert old.joinpath("OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"


def test_geri_alma_calisan_surumu_iade_eder(tmp_path: Path) -> None:
    installed = _installed(tmp_path)
    staged = stage_full(_full_package(tmp_path / "full.zip", "1.1.0"), tmp_path / "staging")
    old = swap(installed, staged.path)

    rollback(installed, old)
    assert installed.joinpath("OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"
    assert not old.exists()


def test_hazirlanmamis_klasorle_takas_yapilmaz(tmp_path: Path) -> None:
    installed = _installed(tmp_path)
    with pytest.raises(SwapError):
        swap(installed, tmp_path / "olmayan")
    assert installed.joinpath("OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"


def test_exe_siz_klasor_yerine_konmaz(tmp_path: Path) -> None:
    """Takas son anda da olsa neyi kurduğuna bakar."""
    installed = _installed(tmp_path)
    bogus = tmp_path / "bos_staging"
    bogus.mkdir()
    (bogus / "okuma.txt").write_text("bos", encoding="utf-8")
    with pytest.raises(SwapError, match="OfficeReminder.exe"):
        swap(installed, bogus)
    assert installed.joinpath("OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"


def test_onceki_yedek_klasor_takasi_engellemez(tmp_path: Path) -> None:
    """Bir önceki güncellemeden kalan .old, yenisini durdurmamalı."""
    installed = _installed(tmp_path)
    stale = installed.with_name(installed.name + ".old")
    stale.mkdir()
    (stale / "artik.txt").write_text("eski", encoding="utf-8")

    staged = stage_full(_full_package(tmp_path / "full.zip", "1.1.0"), tmp_path / "staging")
    old = swap(installed, staged.path)
    assert installed.joinpath("OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.1.0"
    assert not (old / "artik.txt").exists()


def test_yazilabilirlik_kontrolu_iz_birakmaz(tmp_path: Path) -> None:
    folder = tmp_path / "program"
    folder.mkdir()
    assert can_write(folder) is True
    assert list(folder.iterdir()) == [], "sınama dosyası geride kalmış"


def test_olmayan_klasor_yazilabilir_sayilmaz(tmp_path: Path) -> None:
    assert can_write(tmp_path / "yok") is False
