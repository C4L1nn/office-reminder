"""Mini sayaç: en acil iş seçimi + kompakt metin + tone."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services.formatting import (
    mini_counter_remaining_short,
    mini_counter_text,
    mini_counter_tone,
)


def _service(tmp_path: Path):
    from database.connection import Database
    from database.migrations import MigrationRunner
    from services.reminder_service import ReminderService

    db = Database(tmp_path / "mini_counter.db")
    MigrationRunner(db, Path(__file__).resolve().parents[1] / "database" / "migrations").run()
    return ReminderService(db)


def test_geciken_varken_en_eskisini_secer(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    today = date(2026, 9, 10)
    svc.create_manual(title="Yeni Geciken", due_date=today - timedelta(days=1))
    svc.create_manual(title="Eski Geciken", due_date=today - timedelta(days=5))
    svc.create_manual(title="Yaklasan", due_date=today + timedelta(days=2))
    snap = svc.get_mini_counter_snapshot(today=today)
    assert snap.item is not None and snap.item.title == "Eski Geciken"
    # 1 geciken + 1 yaklaşan geride kalır.
    assert snap.extra == 2


def test_geciken_yoksa_en_yakin_vadeyi_secer(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    today = date(2026, 9, 10)
    svc.create_manual(title="Uzak", due_date=today + timedelta(days=9))
    svc.create_manual(title="Yakin", due_date=today + timedelta(days=2))
    snap = svc.get_mini_counter_snapshot(today=today)
    assert snap.item is not None and snap.item.title == "Yakin"
    assert snap.extra == 1


def test_bugune_ait_is_kartta_bugun_olarak_cikar(tmp_path: Path) -> None:
    """Bugün vadeli tek iş, gecikme yokken kartın kendisidir."""
    svc = _service(tmp_path)
    today = date(2026, 9, 10)
    svc.create_manual(title="Bugun", due_date=today)
    snap = svc.get_mini_counter_snapshot(today=today)
    assert snap.item is not None and snap.item.title == "Bugun"
    assert snap.extra == 0
    _, sub = mini_counter_text(snap.item.title, 0, snap.extra)
    assert sub == "Bugün"


def test_hic_is_yoksa_bos_durum(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    snap = svc.get_mini_counter_snapshot(today=date(2026, 9, 10))
    assert snap.item is None
    assert snap.extra == 0
    heading, sub = mini_counter_text(None, None, 0)
    assert heading == "Bugün iş yok"
    assert mini_counter_tone(None) == "success"


def test_kompakt_metin_ayni_dili_konusur() -> None:
    assert mini_counter_remaining_short(-2) == "2g gecikti"
    assert mini_counter_remaining_short(0) == "Bugün"
    assert mini_counter_remaining_short(1) == "Yarın"
    assert mini_counter_remaining_short(3) == "3g kaldı"
    heading, sub = mini_counter_text("KDV", 3, 2)
    assert heading == "KDV"
    assert sub == "3g kaldı · +2 iş daha"
    heading, sub = mini_counter_text("Kira", 0, 0)
    assert sub == "Bugün"


def test_tone_gecikende_danger_bugunde_warning() -> None:
    assert mini_counter_tone(-1) == "danger"
    assert mini_counter_tone(0) == "warning"
    assert mini_counter_tone(5) == "accent"


def test_widget_acilir_ve_cokmez(qt_app) -> None:
    from ui.mini_counter import MiniCounter

    card = MiniCounter()
    try:
        card.refresh("KDV", 3, 2, "ABC LTD · KDV · 28 Eylül 2026")
        assert card._title.text() == "KDV"
        assert "+2 iş daha" in card._subtitle.text()
        card.refresh(None, None, 0)
        assert card._title.text() == "Bugün iş yok"
    finally:
        card.deleteLater()


def test_mini_counter_ayari_varsayilan_kapali(tmp_path: Path) -> None:
    from database.connection import Database
    from database.migrations import MigrationRunner
    from services.settings_service import MINI_COUNTER_ENABLED, SettingsService

    db = Database(tmp_path / "mini_settings.db")
    MigrationRunner(db, Path(__file__).resolve().parents[1] / "database" / "migrations").run()
    settings = SettingsService(db)
    assert settings.get_bool(MINI_COUNTER_ENABLED) is False
    settings.set_bool(MINI_COUNTER_ENABLED, True)
    assert settings.get_bool(MINI_COUNTER_ENABLED) is True


def test_kayit_degisince_kabuk_haber_alir(qt_app, seeded_db) -> None:
    """Tamamlanan kayıt mini sayaca 15 dakika beklemeden ulaşmalı.

    Kart bildirim zamanlayıcısına bağlıyken, kullanıcı bir işi tamamladıktan
    sonra da o işi göstermeye devam ediyordu. Mutasyon `data_changed` yayar,
    süzgeç tazelemesi yaymaz.
    """
    from services.company_service import CompanyService
    from services.reminder_service import ReminderService
    from ui.pages.reminders_page import RemindersPage
    from ui.theme import apply_theme

    apply_theme(qt_app)
    companies = CompanyService(seeded_db)
    reminders = ReminderService(seeded_db)
    company_id = companies.create(name="SINYAL LTD.", tax_number="3333333333")
    reminders.create_manual(
        title="Kira", due_date=date(2026, 9, 12), company_id=company_id, category="RENT"
    )
    page = RemindersPage(reminders, companies)
    page.refresh()

    heard: list[int] = []
    page.data_changed.connect(lambda: heard.append(1))

    # Süzgeç tazelemesi bir mutasyon değildir.
    page.refresh()
    assert heard == []

    row = next(
        row for row, item in page._row_items.items() if item.title == "Kira"
    )
    page.table.setCurrentCell(row, 0)
    page.toggle_complete()
    assert heard == [1], "tamamlama sinyali yayılmadı"


def test_kabuk_sinyali_pencereden_disari_cikar(qt_app, seeded_db) -> None:
    """Sayfanın sinyali pencereden geçip dışarıya ulaşmalı.

    Mini sayaç pencerenin içinde değil; kartı besleyen zincirin kopmadığını
    burada sabitliyoruz.
    """
    from services.company_service import CompanyService
    from services.note_service import NoteService
    from services.official_update_service import OfficialUpdateService
    from services.reminder_service import ReminderService
    from services.settings_service import SettingsService
    from ui.main_window import MainWindow
    from ui.theme import apply_theme

    apply_theme(qt_app)
    window = MainWindow(
        ReminderService(seeded_db),
        CompanyService(seeded_db),
        SettingsService(seeded_db),
        OfficialUpdateService(seeded_db),
        None,
        None,
        NoteService(seeded_db),
    )
    try:
        heard: list[int] = []
        window.data_changed.connect(lambda: heard.append(1))
        window.reminders_page.data_changed.emit()
        assert heard, "sayfa sinyali pencereden dışarı çıkmadı"
    finally:
        window.close()
        window.deleteLater()
