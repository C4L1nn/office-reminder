"""Ayarlar ekranı, başlangıç kaydının gerçek durumunu söylemeli.

Eski ekran, kayıt bir kaynak kod kopyasını başlatırken bile kutuyu işaretli
gösteriyordu; kullanıcının bir şeylerin yanlış gittiğini anlamasının yolu
yoktu. 2026-09-11'deki açılış tam olarak böyle fark edilmeden kaldı.
"""

from __future__ import annotations

from services.settings_service import SettingsService
from services.startup_service import MemoryAutostartStore, StartupService
from ui.pages.settings_page import SettingsPage
from ui.theme import apply_theme

PACKAGED = '"C:/Ofis/OfficeReminder/OfficeReminder.exe"'
SOURCE_RUN = '"C:/Python313/python.exe" "C:/proje/main.py" --background'


def _packaged(background: bool) -> str:
    return PACKAGED + (" --background" if background else "")


def _page(qt_app, seeded_db, startup: StartupService) -> SettingsPage:
    apply_theme(qt_app)
    page = SettingsPage(SettingsService(seeded_db), startup)
    page.refresh()
    return page


def test_kaynaktan_calisirken_kutu_kapali_ve_sebebi_yazili(qt_app, seeded_db) -> None:
    page = _page(qt_app, seeded_db, StartupService(store=MemoryAutostartStore()))
    assert page.autostart_check.isEnabled() is False
    assert page._autostart_note_row.isHidden() is False
    assert "Kaynak koddan" in page.autostart_note.text()


def test_yabanci_kayit_isaretli_gosterilmez_ve_soylenir(qt_app, seeded_db) -> None:
    store = MemoryAutostartStore()
    store.set("OfficeReminder", SOURCE_RUN)
    page = _page(qt_app, seeded_db, StartupService(store=store, command=_packaged))

    assert page.autostart_check.isEnabled() is True
    assert page.autostart_check.isChecked() is False
    assert "başka bir programı" in page.autostart_note.text()
    assert SOURCE_RUN in page.autostart_note.text()


def test_isaretlemek_kaydi_duzeltir_ve_notu_kaldirir(qt_app, seeded_db) -> None:
    store = MemoryAutostartStore()
    store.set("OfficeReminder", SOURCE_RUN)
    page = _page(qt_app, seeded_db, StartupService(store=store, command=_packaged))

    page.autostart_check.setChecked(True)

    assert store.get("OfficeReminder").startswith(PACKAGED)
    assert page._autostart_note_row.isHidden() is True


def test_dogru_kayitta_not_gorunmez(qt_app, seeded_db) -> None:
    store = MemoryAutostartStore()
    store.set("OfficeReminder", _packaged(True))
    page = _page(qt_app, seeded_db, StartupService(store=store, command=_packaged))

    assert page.autostart_check.isChecked() is True
    assert page._autostart_note_row.isHidden() is True
