"""Başarısız resmî senkronun yeniden denenmesi.

Fixture, 2026-09-11 sabahının gerçek sonuç satırı: açılıştan 29 saniye sonra
ağ henüz yoktu, iki kaynak da FAILED döndü ve senkron istisna fırlatmadığı için
bir sonraki deneme altı saat sonraya kalmıştı.
"""

from __future__ import annotations

from app.sync_retry import RETRY_DELAYS_MS, failed_sources, retry_delay_ms

MORNING_RESULT = {
    "gib": {
        "2026": {
            "error": "<urlopen error [Errno 11001] getaddrinfo failed>",
            "source_code": "GIB_2026",
            "status": "FAILED",
        }
    },
    "sgk": {
        "auto_applied": 0,
        "discovered": 0,
        "error": "SGK duyuru listesi okunamadı veya boş döndü",
        "needs_review": 0,
        "no_change": 0,
        "processed": 0,
        "source_code": "SGK_NOTICES",
        "status": "FAILED",
        "unchanged": 0,
    },
}

MINUTE = 60_000


def test_bu_sabahki_sonuc_iki_kaynagi_da_basarisiz_sayar() -> None:
    assert failed_sources(MORNING_RESULT) == ["GIB_2026", "SGK_NOTICES"]


def test_basarili_ve_atlanan_sonuc_yeniden_denemez() -> None:
    result = {
        "gib": {"2026": {"status": "UNCHANGED", "source_code": "GIB_2026"}},
        "sgk": {"status": "SKIPPED", "reason": "recently synced"},
    }
    assert failed_sources(result) == []


def test_tek_kaynak_basarisizsa_yalniz_o_sayilir() -> None:
    result = {
        "gib": {"2026": {"status": "UNCHANGED", "source_code": "GIB_2026"}},
        "sgk": {"status": "FAILED", "source_code": "SGK_NOTICES"},
    }
    assert failed_sources(result) == ["SGK_NOTICES"]


def test_bozuk_sonuc_cokertmez() -> None:
    for broken in (None, {}, {"gib": None, "sgk": None}, {"gib": {"2026": "?"}}):
        assert failed_sources(broken) == []


def test_ilk_deneme_alti_saat_beklemez() -> None:
    assert retry_delay_ms(0) <= 5 * MINUTE


def test_bekleme_artar_ve_tavanda_kalir() -> None:
    delays = [retry_delay_ms(attempt) // MINUTE for attempt in range(6)]
    assert delays == [2, 5, 15, 30, 30, 30]
    assert list(RETRY_DELAYS_MS) == sorted(RETRY_DELAYS_MS)


def test_basarisiz_deneme_yeniden_denemeyi_engellemez(seeded_db) -> None:
    """Yeniden deneme "yakın zamanda senkronlandı" diye atlanmamalı.

    should_sync yalnızca last_success_at'e bakıyor; başarısız bir deneme ise
    yalnızca last_attempt_at yazar. Bu ayrım bozulursa iki dakika sonraki
    deneme SKIPPED döner ve yeniden deneme hiçbir şey yapmamış olur.
    """
    from datetime import datetime, timezone

    from services.official_update_service import OfficialUpdateService

    now = datetime.now(timezone.utc).isoformat()
    with seeded_db.session() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO official_source_state"
            " (source_code, source_kind, last_attempt_at, last_success_at)"
            " VALUES ('SGK_NOTICES', 'SGK', ?, NULL)",
            (now,),
        )
    service = OfficialUpdateService(seeded_db)
    assert service.should_sync("SGK_NOTICES") is True, "başarısız deneme yeniden denemeyi engelliyor"

    with seeded_db.session() as connection:
        connection.execute(
            "UPDATE official_source_state SET last_success_at = ?"
            " WHERE source_code = 'SGK_NOTICES'",
            (now,),
        )
    assert service.should_sync("SGK_NOTICES") is False
