"""Windows başlangıç kaydı.

2026-09-11'de bir ofis bilgisayarı açılışta kaynak kodu Python 3.13 ile
başlattı: kaynaktan çalıştırılan bir oturum "Windows açıldığında başlat"ı
işaretlemişti. Konsol penceresi açıldı ve program ofisin gerçek verisi yerine
geliştirme veritabanını kullandı. Buradaki testler o yolu kapatır.
"""

from __future__ import annotations

import pytest

from services.startup_service import (
    MemoryAutostartStore,
    StartupService,
    StartupUnavailable,
    _get_executable_command,
)

PACKAGED = '"C:/Users/ofis/Masaüstü/OfficeReminder/OfficeReminder.exe"'
SOURCE_RUN = (
    '"C:/Users/ofis/AppData/Local/Programs/Python/Python313/python.exe" '
    '"C:/proje/office_reminder/main.py" --background'
)


def _packaged(background: bool) -> str:
    return PACKAGED + (" --background" if background else "")


def _service(store: MemoryAutostartStore) -> StartupService:
    return StartupService(store=store, command=_packaged)


def test_kaynaktan_calisirken_kayit_yazilmaz() -> None:
    """Testler de kaynaktan koşuyor: varsayılan komut burada hiçbir şey vermemeli."""
    assert _get_executable_command(True) is None
    store = MemoryAutostartStore()
    service = StartupService(store=store)
    assert service.available() is False
    with pytest.raises(StartupUnavailable):
        service.set_enabled(True)
    assert store.get(service.app_name) is None, "kaynak kod başlangıca yazıldı"


def test_baska_programi_gosteren_kayit_acik_sayilmaz() -> None:
    """Eski kontrol içinde 'main.py' geçen her kaydı açık sayıyordu."""
    store = MemoryAutostartStore()
    service = _service(store)
    store.set(service.app_name, SOURCE_RUN)
    assert service.is_enabled() is False
    assert service.points_elsewhere() == SOURCE_RUN


def test_isaretlemek_yabanci_kaydi_duzeltir() -> None:
    store = MemoryAutostartStore()
    service = _service(store)
    store.set(service.app_name, SOURCE_RUN)
    service.set_enabled(True, background=True)
    assert store.get(service.app_name) == _packaged(True)
    assert service.is_enabled() is True
    assert service.points_elsewhere() is None


def test_isareti_kaldirmak_yabanci_kaydi_da_siler() -> None:
    store = MemoryAutostartStore()
    service = _service(store)
    store.set(service.app_name, SOURCE_RUN)
    service.set_enabled(False)
    assert store.get(service.app_name) is None


def test_arka_plan_secenegi_ayni_programdir() -> None:
    """--background yalnızca bir seçenek; kayıt yine bu programı gösteriyor."""
    store = MemoryAutostartStore()
    service = _service(store)
    service.set_enabled(True, background=False)
    assert service.is_enabled() is True
    service.set_enabled(True, background=True)
    assert store.get(service.app_name) == _packaged(True)
    assert service.is_enabled() is True


def test_yol_karsilastirmasi_buyuk_kucuk_harfe_duyarsiz() -> None:
    """Windows'ta 'Masaüstü' ile 'MASAÜSTÜ' aynı klasördür."""
    store = MemoryAutostartStore()
    service = _service(store)
    store.set(service.app_name, PACKAGED.upper() + " --background")
    assert service.is_enabled() is True
