"""İndirmeden kuruluma kadar olan sıra.

Buradaki sorular: kurulamayacak bir makinede baştan söyleniyor mu, kendi
sınamasından geçemeyen bir yapı kuruluyor mu, ve hangi adımda durulursa
durulsun kurulu sürüm yerinde kalıyor mu.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

from app import update_flow
from app.update_flow import UpdateBlocked, check_installable, cleanup, prepare
from services.update_service import (
    MANIFEST_URL,
    UpdateError,
    UpdateService,
    manifest_fetcher,
)


@pytest.fixture()
def frozen(monkeypatch):
    """Paketlenmiş çalışıyormuş gibi davran."""
    monkeypatch.setattr(update_flow, "is_frozen", lambda: True)


def _installed(root: Path) -> Path:
    folder = root / "OfficeReminder"
    (folder / "_internal").mkdir(parents=True)
    (folder / "OfficeReminder.exe").write_text("exe 1.0.0", encoding="utf-8")
    (folder / "_internal" / "sabit.dll").write_text("degismez", encoding="utf-8")
    return folder


def _package(path: Path, version: str) -> bytes:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"OfficeReminder/OfficeReminder.exe", f"exe {version}")
        archive.writestr("OfficeReminder/_internal/sabit.dll", "degismez")
    return path.read_bytes()


def _service(payload: bytes, url: str, served: bytes | None = None) -> tuple[UpdateService, object]:
    """`payload` manifestte duyurulan içerik; `served` gerçekte inen içerik."""
    manifest = json.dumps({
        "schema": 1,
        "version": "1.1.0",
        "min_version": "1.0.0",
        "notes": "Deneme",
        "full": {
            "url": url,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        },
    }).encode("utf-8")

    class _Response:
        status = 200

        def __init__(self, body: bytes) -> None:
            self._body = body
            self._at = 0

        def read(self, size=-1):
            chunk = self._body[self._at:] if size < 0 else self._body[self._at:self._at + size]
            self._at += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    body = payload if served is None else served
    service = UpdateService(
        "1.0.0",
        fetch=manifest_fetcher({MANIFEST_URL: manifest}),
        open_url=lambda request, timeout=None: _Response(body),
    )
    release = service.check()
    assert release is not None
    return service, release


GOOD_URL = "https://github.com/C4L1nn/office-reminder-releases/releases/download/v1.1.0/p.zip"


# ------------------------------------------------------------------ ön kontrol
def test_kaynaktan_calisirken_guncelleme_reddedilir(monkeypatch) -> None:
    monkeypatch.setattr(update_flow, "is_frozen", lambda: False)
    with pytest.raises(UpdateBlocked, match="Kaynaktan"):
        check_installable(Path("."))


def test_yazilamayan_klasor_bastan_soylenir(frozen, monkeypatch, tmp_path: Path) -> None:
    """Yarısında değil, hiç başlamadan."""
    target = _installed(tmp_path)
    monkeypatch.setattr(update_flow, "can_write", lambda path: False)
    with pytest.raises(UpdateBlocked, match="yazılamıyor"):
        check_installable(target)


def test_program_klasoru_degilse_reddedilir(frozen, tmp_path: Path) -> None:
    folder = tmp_path / "rastgele"
    folder.mkdir()
    with pytest.raises(UpdateBlocked, match="tanınmadı"):
        check_installable(folder)


# ---------------------------------------------------------------- hazırlık
def test_sinavini_gecen_yapi_kurulmaya_hazirlanir(frozen, monkeypatch, tmp_path: Path) -> None:
    target = _installed(tmp_path)
    payload = _package(tmp_path / "kaynak.zip", "1.1.0")
    service, release = _service(payload, GOOD_URL)
    monkeypatch.setattr(update_flow, "_gate", lambda executable: None)

    prepared = prepare(
        service, release, release.full, target=target, root=tmp_path / "update"
    )

    assert prepared.version == "1.1.0"
    assert (prepared.staging / "OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.1.0"
    # Kurulu sürüme hiç dokunulmadı.
    assert (target / "OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"


def test_indirilen_paket_acildiktan_sonra_silinir(frozen, monkeypatch, tmp_path: Path) -> None:
    target = _installed(tmp_path)
    payload = _package(tmp_path / "kaynak.zip", "1.1.0")
    service, release = _service(payload, GOOD_URL)
    monkeypatch.setattr(update_flow, "_gate", lambda executable: None)

    prepare(service, release, release.full, target=target, root=tmp_path / "update")
    assert not list((tmp_path / "update").glob("*.zip"))


def test_sinavdan_kalan_yapi_kurulmaz(frozen, monkeypatch, tmp_path: Path) -> None:
    """Kapının bütün amacı bu."""
    target = _installed(tmp_path)
    payload = _package(tmp_path / "kaynak.zip", "1.1.0")
    service, release = _service(payload, GOOD_URL)

    def _failing_gate(executable):
        raise UpdateError("Yeni sürüm kendi sınamasından geçemedi:\n[HATA] migration")

    monkeypatch.setattr(update_flow, "_gate", _failing_gate)

    with pytest.raises(UpdateError, match="sınamasından geçemedi"):
        prepare(service, release, release.full, target=target, root=tmp_path / "update")
    assert (target / "OfficeReminder.exe").read_text(encoding="utf-8") == "exe 1.0.0"


def test_ozeti_tutmayan_paket_hazirliga_bile_gecmez(frozen, tmp_path: Path) -> None:
    """Manifest bir şey vaat ediyor, sunucudan başka bir şey iniyor.

    Sahte içerik bilerek aynı uzunlukta: boyut kontrolü devreye girerse
    özet kontrolü hiç sınanmamış olurdu.
    """
    target = _installed(tmp_path)
    payload = _package(tmp_path / "kaynak.zip", "1.1.0")
    service, release = _service(payload, GOOD_URL, served=b"\x00" * len(payload))

    with pytest.raises(UpdateError, match="sha256"):
        prepare(service, release, release.full, target=target, root=tmp_path / "update")
    assert not (tmp_path / "update" / "staging").exists()


# --------------------------------------------------------------------- kapı
def test_kapi_gercek_bir_sureci_calistirir(tmp_path: Path) -> None:
    """Kapı, exe'yi kendi kum havuzuyla çağırıyor mu — çıkış kodu 0 olan bir
    süreçle sınanır, gerçek yapı gerektirmeden."""
    script = tmp_path / "sahte.py"
    script.write_text("import sys; sys.exit(0)", encoding="utf-8")

    calls: list[list[str]] = []
    real_run = update_flow.subprocess.run

    def _capture(command, **kwargs):
        calls.append(command)
        return real_run([sys.executable, str(script)], **kwargs)

    update_flow.subprocess.run = _capture
    try:
        update_flow._gate(tmp_path / "OfficeReminder.exe")
    finally:
        update_flow.subprocess.run = real_run

    assert calls and "--selftest" in calls[0]
    assert any(arg.startswith("--data-dir=") for arg in calls[0])


def test_kapi_sifir_disi_cikisi_hata_sayar(tmp_path: Path) -> None:
    script = tmp_path / "sahte.py"
    script.write_text("print('[HATA] migration'); import sys; sys.exit(3)", encoding="utf-8")
    real_run = update_flow.subprocess.run

    def _capture(command, **kwargs):
        return real_run([sys.executable, str(script)], **kwargs)

    update_flow.subprocess.run = _capture
    try:
        with pytest.raises(UpdateError, match="sınamasından geçemedi"):
            update_flow._gate(tmp_path / "OfficeReminder.exe")
    finally:
        update_flow.subprocess.run = real_run


def test_kapi_gecici_klasoru_geride_birakmaz(tmp_path: Path) -> None:
    import tempfile

    script = tmp_path / "sahte.py"
    script.write_text("import sys; sys.exit(0)", encoding="utf-8")
    before = set(Path(tempfile.gettempdir()).glob("or-gate-*"))
    real_run = update_flow.subprocess.run
    update_flow.subprocess.run = lambda command, **kwargs: real_run(
        [sys.executable, str(script)], **kwargs
    )
    try:
        update_flow._gate(tmp_path / "OfficeReminder.exe")
    finally:
        update_flow.subprocess.run = real_run
    assert set(Path(tempfile.gettempdir()).glob("or-gate-*")) == before


# ------------------------------------------------------------------ temizlik
def test_acilis_temizligi_onceki_surumu_kaldirir(tmp_path: Path) -> None:
    target = _installed(tmp_path)
    old = target.with_name(target.name + ".old")
    old.mkdir()
    (old / "eski.txt").write_text("x", encoding="utf-8")
    staging = tmp_path / "update" / "staging"
    staging.mkdir(parents=True)

    cleanup(target=target, root=tmp_path / "update")

    assert not old.exists()
    assert not staging.exists()
    assert (target / "OfficeReminder.exe").is_file()


def test_temizlik_yapacak_bir_sey_yoksa_sessiz(tmp_path: Path) -> None:
    target = _installed(tmp_path)
    cleanup(target=target, root=tmp_path / "update")
    assert (target / "OfficeReminder.exe").is_file()
