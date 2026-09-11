"""Şerit, ayar ve "sonra" kaydı.

Buradaki mesele davranış: kullanıcı ayın 26'sında beyanname hazırlarken
güncelleme onu kesmemeli, "Sonra" dediği sürüm bir daha çıkmamalı, ama bir
sonraki sürüm çıkmalı.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import update_controller as controller_module
from app.update_controller import UpdateController
from services.settings_service import (
    UPDATE_AUTO_CHECK,
    UPDATE_SKIPPED_VERSION,
    SettingsService,
)
from services.update_service import MANIFEST_URL, UpdateService, manifest_fetcher
from ui.update_banner import UpdateBanner

GOOD_URL = "https://github.com/C4L1nn/office-reminder-releases/releases/download/v1.1.0/p.zip"


def _manifest(version: str = "1.1.0", notes: str = "Mini sayaç eklendi.") -> bytes:
    return json.dumps({
        "schema": 1,
        "version": version,
        "min_version": "1.0.0",
        "notes": notes,
        "full": {"url": GOOD_URL, "sha256": "a" * 64, "size": 3_300_000},
    }).encode("utf-8")


class _Window:
    """Denetleyicinin pencereden ihtiyaç duyduğu tek şey toast alanı."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []
        self.toasts = self

    def show_toast(self, title: str, body: str, tone: str = "success") -> None:
        self.messages.append((title, body, tone))


@pytest.fixture()
def wired(qt_app, seeded_db, monkeypatch):
    from ui.theme import apply_theme

    apply_theme(qt_app)
    monkeypatch.setattr(controller_module.update_flow, "is_frozen", lambda: True)
    settings = SettingsService(seeded_db)
    banner = UpdateBanner()
    window = _Window()
    control = UpdateController(settings, banner, window)
    control.service = UpdateService(
        "1.0.0", fetch=manifest_fetcher({MANIFEST_URL: _manifest()})
    )
    return control, banner, settings, window


def _check_now(control) -> None:
    """Arka plan işçisini beklemeden, denetimin sonucunu doğrudan işle."""
    release = control.service.check()
    assert release is not None
    if control._skipped(release.version_text):
        return
    control._offer(release, manual=False)


def test_yeni_surum_serit_olarak_duyurulur(wired) -> None:
    control, banner, _settings, _window = wired
    _check_now(control)

    assert not banner.isHidden()
    assert "1.1.0" in banner._text.text()
    assert "MB" in banner._text.text(), "ne kadar ineceği yazmıyor"


def test_sonra_denen_surum_bir_daha_cikmaz(wired) -> None:
    control, banner, settings, _window = wired
    _check_now(control)
    banner._dismiss()

    assert settings.get(UPDATE_SKIPPED_VERSION) == "1.1.0"
    assert banner.isHidden()

    # Aynı sürüm yeniden duyurulmamalı.
    banner.hide()
    _check_now(control)
    assert banner.isHidden(), "atlanan sürüm yeniden çıktı"


def test_sonraki_surum_yine_duyurulur(wired) -> None:
    """"Sonra" bir sürüme aittir, güncellemenin tamamına değil."""
    control, banner, settings, _window = wired
    _check_now(control)
    banner._dismiss()

    control.service = UpdateService(
        "1.0.0", fetch=manifest_fetcher({MANIFEST_URL: _manifest(version="1.2.0")})
    )
    _check_now(control)
    assert not banner.isHidden()
    assert "1.2.0" in banner._text.text()


def test_otomatik_denetim_kapaliyken_aga_cikilmaz(wired) -> None:
    control, _banner, settings, _window = wired
    settings.set_bool(UPDATE_AUTO_CHECK, False)

    calls: list[int] = []
    control.service.check = lambda: calls.append(1)
    control.check(manual=False)
    assert calls == []


def test_elle_denetim_ayari_gecersiz_kilar(wired, monkeypatch) -> None:
    """Kullanıcı tepsiden isteyince ayar ne olursa olsun bakılır."""
    control, _banner, settings, _window = wired
    settings.set_bool(UPDATE_AUTO_CHECK, False)

    calls: list[int] = []
    monkeypatch.setattr(
        controller_module, "run_in_background",
        lambda func, on_finished=None, on_error=None, **kw: calls.append(1),
    )
    control.check(manual=True)
    assert calls == [1]


def test_indirme_sirasinda_serit_kapatilamaz(wired) -> None:
    """Yarıda bırakılmış bir indirme kullanıcıya bir şey kazandırmaz."""
    control, banner, _settings, _window = wired
    _check_now(control)
    banner.downloading(1_000_000, 3_300_000)
    assert banner._close_button.isHidden()
    assert not banner._install_button.isEnabled()


def test_onceki_basarisiz_guncelleme_haber_verilir(wired, tmp_path: Path, monkeypatch) -> None:
    """Kurulum uygulama kapalıyken koşuyor; not bırakmasa sessiz kalırdı."""
    control, _banner, _settings, window = wired
    from services.update_swap import write_result

    root = tmp_path / "update"
    write_result(root, {"status": "rolled_back", "version": "1.1.0", "message": "Yeni sürüm eksik geldi."})
    monkeypatch.setattr(controller_module, "update_flow", controller_module.update_flow)
    monkeypatch.setattr("services.update_service.update_dir", lambda root_=None: root)

    control._report_previous_result()

    assert window.messages, "başarısız güncelleme sessiz kaldı"
    title, body, tone = window.messages[0]
    assert "yapılamadı" in title.lower()
    assert "Önceki sürüm çalışmaya devam ediyor" in body
    assert tone == "warning"


def test_basarili_guncelleme_de_haber_verilir(wired, tmp_path: Path, monkeypatch) -> None:
    control, _banner, _settings, window = wired
    from services.update_swap import write_result

    root = tmp_path / "update"
    write_result(root, {"status": "installed", "version": "1.1.0"})
    monkeypatch.setattr("services.update_service.update_dir", lambda root_=None: root)

    control._report_previous_result()
    assert window.messages and "1.1.0" in window.messages[0][1]


def test_sonuc_notu_bir_kez_gosterilir(wired, tmp_path: Path, monkeypatch) -> None:
    control, _banner, _settings, window = wired
    from services.update_swap import write_result

    root = tmp_path / "update"
    write_result(root, {"status": "installed", "version": "1.1.0"})
    monkeypatch.setattr("services.update_service.update_dir", lambda root_=None: root)

    control._report_previous_result()
    control._report_previous_result()
    assert len(window.messages) == 1, "aynı not her açılışta tekrar gösteriliyor"
