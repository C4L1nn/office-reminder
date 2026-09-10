"""Güncelleme manifesti okuma ve paket indirme.

Bu katmanın işi güvenmemek: manifest bozuksa, adres tanımadığımız bir sunucuyu
gösteriyorsa ya da inen paketin özeti tutmuyorsa hiçbir şey kurulmamalı.
Testlerin hiçbiri ağa çıkmaz; hem manifest hem indirme enjekte edilir.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from services.update_service import (
    MANIFEST_URL,
    MAX_PACKAGE_BYTES,
    UpdateError,
    UpdateService,
    manifest_fetcher,
    parse_manifest,
    parse_version,
)

GOOD_URL = "https://github.com/C4L1nn/office-reminder-releases/releases/download/v1.1.0/pkg.zip"


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest(**overrides) -> bytes:
    body = {
        "schema": 1,
        "version": "1.1.0",
        "released": "2026-09-20",
        "notes": "Mini sayaç eklendi.",
        "min_version": "1.0.0",
        "full": {"url": GOOD_URL, "sha256": "a" * 64, "size": 45_000_000},
    }
    body.update(overrides)
    return json.dumps(body).encode("utf-8")


# --------------------------------------------------------------- sürüm numarası
def test_surum_numarasi_uc_parcali_olmali() -> None:
    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version(" 10.0.44 ") == (10, 0, 44)
    for bad in ("1.2", "1.2.3.4", "1.2.x", "", "sürüm", "1.-2.3"):
        with pytest.raises(UpdateError):
            parse_version(bad)


def test_surumler_sayisal_karsilastirilir() -> None:
    """Metin karşılaştırması '1.10.0' < '1.9.0' derdi."""
    assert parse_version("1.10.0") > parse_version("1.9.0")


# -------------------------------------------------------------------- manifest
def test_gecerli_manifest_okunur() -> None:
    release = parse_manifest(_manifest())
    assert release.version == (1, 1, 0)
    assert release.full.size == 45_000_000
    assert release.delta is None
    assert "Mini sayaç" in release.notes


def test_eksik_alan_manifesti_gecersiz_kilar() -> None:
    body = json.loads(_manifest())
    del body["full"]["sha256"]
    with pytest.raises(UpdateError, match="sha256"):
        parse_manifest(json.dumps(body).encode("utf-8"))


def test_bozuk_ozet_reddedilir() -> None:
    with pytest.raises(UpdateError, match="sha256"):
        parse_manifest(_manifest(full={"url": GOOD_URL, "sha256": "kısa", "size": 10}))


def test_http_adresi_reddedilir() -> None:
    """Manifest kurcalanmış olsa bile paket şifresiz bir adresten inmez."""
    bad = GOOD_URL.replace("https://", "http://")
    with pytest.raises(UpdateError, match="HTTPS"):
        parse_manifest(_manifest(full={"url": bad, "sha256": "a" * 64, "size": 10}))


def test_tanimadigimiz_sunucu_reddedilir() -> None:
    bad = "https://ornek-saldirgan.example.com/pkg.zip"
    with pytest.raises(UpdateError, match="izin verilen"):
        parse_manifest(_manifest(full={"url": bad, "sha256": "a" * 64, "size": 10}))


def test_absurt_boyut_reddedilir() -> None:
    huge = MAX_PACKAGE_BYTES + 1
    with pytest.raises(UpdateError, match="boyut"):
        parse_manifest(_manifest(full={"url": GOOD_URL, "sha256": "a" * 64, "size": huge}))


def test_ileri_bir_manifest_bicimi_tahmin_edilmez() -> None:
    """Alan bunun için var: eski istemci yeni biçimi yorumlamaya çalışmasın."""
    with pytest.raises(UpdateError, match="schema"):
        parse_manifest(_manifest(schema=2))


def test_bozuk_json_manifesti_cokertmez() -> None:
    with pytest.raises(UpdateError, match="okunamadı"):
        parse_manifest(b"{bu json degil")


# ----------------------------------------------------------------------- check
def _service(current: str, payload: bytes | None = None) -> UpdateService:
    return UpdateService(
        current,
        fetch=manifest_fetcher({MANIFEST_URL: payload if payload is not None else _manifest()}),
    )


def test_yeni_surum_varsa_bildirilir() -> None:
    release = _service("1.0.0").check()
    assert release is not None and release.version_text == "1.1.0"


def test_ayni_surumde_hicbir_sey_onerilmez() -> None:
    assert _service("1.1.0").check() is None


def test_daha_yeni_bir_yapida_geri_adim_onerilmez() -> None:
    """Geliştirme makinesi yayınlanandan ileride olabilir."""
    assert _service("1.2.0").check() is None


def test_cok_eski_yapi_desteklenmedigini_soyler() -> None:
    service = _service("0.9.0", _manifest(min_version="1.0.0"))
    release = service.check()
    assert release is not None
    assert service.supported(release) is False


# ----------------------------------------------------------------------- delta
def _with_delta(from_version: str) -> bytes:
    return _manifest(
        delta={
            "from": from_version,
            "url": GOOD_URL.replace("pkg.zip", "delta.zip"),
            "sha256": "b" * 64,
            "size": 3_200_000,
        }
    )


def test_fark_paketi_yalnizca_kendi_surumune_verilir() -> None:
    service = _service("1.0.0", _with_delta("1.0.0"))
    release = service.check()
    assert release is not None
    chosen = service.choose(release)
    assert chosen.kind == "delta" and chosen.size == 3_200_000


def test_baska_surumdeki_makineye_tam_paket_verilir() -> None:
    """Yanlış tabana uygulanan fark, yarısı bir sürüm olan bir klasör üretir."""
    service = _service("1.0.5", _with_delta("1.0.0"))
    release = service.check()
    assert release is not None
    assert service.choose(release).kind == "full"


# -------------------------------------------------------------------- indirme
class _FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _opener(payload: bytes):
    def open_url(request, timeout=None):
        return _FakeResponse(payload)

    return open_url


def _package_service(payload: bytes, digest: str, size: int) -> tuple[UpdateService, object]:
    manifest = _manifest(full={"url": GOOD_URL, "sha256": digest, "size": size})
    service = UpdateService(
        "1.0.0",
        fetch=manifest_fetcher({MANIFEST_URL: manifest}),
        open_url=_opener(payload),
    )
    release = service.check()
    assert release is not None
    return service, release.full


def test_ozeti_tutan_paket_kabul_edilir(tmp_path: Path) -> None:
    payload = b"paket-icerigi" * 1000
    service, package = _package_service(payload, _digest(payload), len(payload))
    seen: list[tuple[int, int]] = []
    out = service.download(package, tmp_path / "pkg.zip", progress=lambda a, b: seen.append((a, b)))
    assert out.read_bytes() == payload
    assert seen and seen[-1][0] == len(payload)


def test_ozeti_tutmayan_paket_kurulmaz(tmp_path: Path) -> None:
    """Asıl güvenlik ağı bu: HTTPS tek başına yeterli değil."""
    payload = b"kurcalanmis-icerik" * 500
    service, package = _package_service(payload, "c" * 64, len(payload))
    with pytest.raises(UpdateError, match="sha256"):
        service.download(package, tmp_path / "pkg.zip")
    assert not (tmp_path / "pkg.zip").exists()
    assert not (tmp_path / "pkg.zip.part").exists()


def test_eksik_inen_paket_kurulmaz(tmp_path: Path) -> None:
    payload = b"yarim"
    service, package = _package_service(payload, _digest(payload), len(payload) + 100)
    with pytest.raises(UpdateError, match="eksik"):
        service.download(package, tmp_path / "pkg.zip")
    assert not (tmp_path / "pkg.zip.part").exists()


def test_bildirilenden_buyuk_paket_diski_doldurmaz(tmp_path: Path) -> None:
    payload = b"x" * 5000
    service, package = _package_service(payload, _digest(payload), 100)
    with pytest.raises(UpdateError, match="büyük"):
        service.download(package, tmp_path / "pkg.zip")
    assert not (tmp_path / "pkg.zip.part").exists()


def test_yarim_kalan_indirme_tamamlanmis_sayilmaz(tmp_path: Path) -> None:
    """Bir sonraki denemede .part dosyası hazır paket sanılmamalı."""
    payload = b"kesilen" * 100

    class _Broken(_FakeResponse):
        def read(self, size=-1):
            raise OSError("baglanti koptu")

    manifest = _manifest(full={"url": GOOD_URL, "sha256": _digest(payload), "size": len(payload)})
    service = UpdateService(
        "1.0.0",
        fetch=manifest_fetcher({MANIFEST_URL: manifest}),
        open_url=lambda request, timeout=None: _Broken(b""),
    )
    release = service.check()
    assert release is not None
    with pytest.raises(UpdateError):
        service.download(release.full, tmp_path / "pkg.zip")
    assert list(tmp_path.iterdir()) == []
