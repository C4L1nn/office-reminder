"""Uygulama kapandıktan sonra çalışan kurulum yarısı.

Sözleşme tek cümle: bu fonksiyondan hangi yoldan çıkılırsa çıkılsın, hedef
klasörde çalışan bir program kalır. Testler gerçek dosya ağaçları üzerinde
koşar ama süreç başlatmaz (`relaunch=False`).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.update_installer import apply_update
from services.update_swap import read_result


def _build(folder: Path, version: str) -> Path:
    (folder / "_internal").mkdir(parents=True)
    (folder / "OfficeReminder.exe").write_text(f"exe {version}", encoding="utf-8")
    (folder / "_internal" / "base_library.zip").write_text(f"lib {version}", encoding="utf-8")
    return folder


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    target = _build(tmp_path / "OfficeReminder", "1.0.0")
    staging = _build(tmp_path / "update" / "staging", "1.1.0")
    return target, staging, tmp_path / "update"


def test_basarili_kurulum_yeni_surumu_yerine_koyar(tmp_path: Path) -> None:
    target, staging, root = _setup(tmp_path)
    code = apply_update(target, staging, root, version="1.1.0", relaunch=False)

    assert code == 0
    assert (target / "OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.1.0"
    result = read_result(root)
    assert result is not None and result["status"] == "installed"
    assert result["version"] == "1.1.0"


def test_onceki_surum_silinmeden_yanda_bekler(tmp_path: Path) -> None:
    """Yeni sürüm bir kez açılana kadar geri dönülecek yer durmalı."""
    target, staging, root = _setup(tmp_path)
    apply_update(target, staging, root, version="1.1.0", relaunch=False)

    old = target.with_name(target.name + ".old")
    assert old.is_dir()
    assert (old / "OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"


def test_hazirlanan_klasor_yoksa_kurulu_surum_bozulmaz(tmp_path: Path) -> None:
    target, _staging, root = _setup(tmp_path)
    code = apply_update(target, tmp_path / "olmayan", root, version="1.1.0", relaunch=False)

    assert code == 1
    assert (target / "OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"
    result = read_result(root)
    assert result is not None and result["status"] == "failed"


def test_exe_siz_hazirlik_kurulmaz(tmp_path: Path) -> None:
    target, _s, root = _setup(tmp_path)
    bogus = tmp_path / "update" / "bos"
    bogus.mkdir(parents=True)
    (bogus / "okuma.txt").write_text("bos", encoding="utf-8")

    code = apply_update(target, bogus, root, version="1.1.0", relaunch=False)
    assert code == 1
    assert (target / "OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"


def test_kapanmayan_surece_dokunulmaz(tmp_path: Path) -> None:
    """Kilit hâlâ duruyorsa güncelleme hiç başlamaz."""
    import os

    target, staging, root = _setup(tmp_path)
    # Kendi sürecimiz elbette kapanmıyor: bekleme zaman aşımına uğramalı.
    import app.update_installer as installer

    original = installer.EXIT_TIMEOUT_SECONDS
    installer.EXIT_TIMEOUT_SECONDS = 1.0
    try:
        code = apply_update(
            target, staging, root, wait_pid=os.getpid(), version="1.1.0", relaunch=False
        )
    finally:
        installer.EXIT_TIMEOUT_SECONDS = original

    assert code == 1
    assert (target / "OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"
    result = read_result(root)
    assert result is not None and result["status"] == "aborted"


def test_kapanmis_surec_beklemeyi_gecirmez(tmp_path: Path) -> None:
    """Var olmayan bir pid 'çoktan kapandı' demektir, 60 saniye beklenmez."""
    import time

    target, staging, root = _setup(tmp_path)
    started = time.monotonic()
    code = apply_update(
        target, staging, root, wait_pid=999_999_999, version="1.1.0", relaunch=False
    )
    assert code == 0
    assert time.monotonic() - started < 5.0


def test_gunluk_dosyasi_yaziliyor(tmp_path: Path) -> None:
    """Uzaktaki bir makinede olan biteni anlatan tek kayıt bu."""
    target, staging, root = _setup(tmp_path)
    apply_update(target, staging, root, version="1.1.0", relaunch=False)

    log = (root / "update.log").read_text(encoding="utf-8")
    assert "güncelleme başlıyor" in log
    assert "1.1.0" in log
    assert "güncelleme tamamlandı" in log


def test_sonuc_dosyasi_gecerli_json(tmp_path: Path) -> None:
    target, staging, root = _setup(tmp_path)
    apply_update(target, staging, root, version="1.1.0", relaunch=False)
    payload = json.loads((root / "last_result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "installed"


# ----------------------------------------------------------------- giriş bayrakları
def test_anahtar_degerli_bayraklar_ayristirilir() -> None:
    from main import _options

    parsed = _options({"--apply-update", "--target=C:/a b", "--wait-pid=42", "--background"})
    assert parsed == {"target": "C:/a b", "wait-pid": "42"}


def test_data_dir_calisma_klasorunu_degistirir(monkeypatch, tmp_path: Path) -> None:
    """Selftest kapısının tamamı buna dayanıyor: yeni sürüm kendini
    sınarken ofisin gerçek veritabanına migration uygulamamalı."""
    import main

    monkeypatch.delenv("OFFICE_REMINDER_DATA_DIR", raising=False)
    assert main.main(["prog", "--version", f"--data-dir={tmp_path}"]) == 0

    import os

    assert os.environ["OFFICE_REMINDER_DATA_DIR"] == str(tmp_path)
    from app.paths import get_runtime_root

    assert get_runtime_root() == tmp_path


def test_bos_data_dir_reddedilir(monkeypatch) -> None:
    import main

    monkeypatch.delenv("OFFICE_REMINDER_DATA_DIR", raising=False)
    assert main.main(["prog", "--version", "--data-dir="]) == 2


def test_eksik_argumanla_kurulum_baslamaz() -> None:
    import main

    assert main.main(["prog", "--apply-update", "--target=C:/x"]) == 2
