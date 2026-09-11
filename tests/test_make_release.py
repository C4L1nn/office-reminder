"""Sürüm paketlerinin üretimi.

Yayın süreci elle yürütülürse kayar; burada tam paket, fark paketi ve manifest
aynı ölçümden çıkıyor. Testler ürettikleri paketi kurulum tarafına da
uyguluyor — iki taraf aynı biçimi konuşmazsa güncelleme uzaktaki bir makinede
patlar, burada değil.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from services.update_service import parse_manifest
from services.update_swap import DELTA_MANIFEST, stage_delta, stage_full
from tools.make_release import (
    build_manifest,
    diff_trees,
    main,
    tree_digests,
    write_delta,
    write_full,
)


def _dist(root: Path, version: str, extra: dict[str, str] | None = None) -> Path:
    folder = root / f"dist-{version}"
    (folder / "_internal" / "PySide6").mkdir(parents=True)
    (folder / "OfficeReminder.exe").write_text(f"exe {version}", encoding="utf-8")
    (folder / "_internal" / "base_library.zip").write_text(f"lib {version}", encoding="utf-8")
    (folder / "_internal" / "PySide6" / "Qt6Core.dll").write_text("qt sabit", encoding="utf-8")
    for name, body in (extra or {}).items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return folder


def test_fark_yalnizca_degisenleri_ve_silinenleri_bulur(tmp_path: Path) -> None:
    old = _dist(tmp_path, "1.0.0", {"_internal/gidecek.dll": "eski"})
    new = _dist(tmp_path, "1.1.0", {"_internal/gelecek.dll": "yeni"})

    changed, removed = diff_trees(tree_digests(old), tree_digests(new))

    assert "OfficeReminder.exe" in changed
    assert "_internal/gelecek.dll" in changed
    assert "_internal/PySide6/Qt6Core.dll" not in changed, "değişmeyen dosya pakete girmiş"
    assert removed == ["_internal/gidecek.dll"]


def test_tam_paket_tek_klasore_sarilir(tmp_path: Path) -> None:
    dist = _dist(tmp_path, "1.1.0")
    package = write_full(dist, tmp_path / "full.zip")
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    assert all(name.startswith("OfficeReminder/") for name in names)


def test_uretilen_tam_paket_kurulabiliyor(tmp_path: Path) -> None:
    """Üreten ve kuran taraf aynı biçimi konuşuyor mu."""
    dist = _dist(tmp_path, "1.1.0")
    package = write_full(dist, tmp_path / "full.zip")
    staged = stage_full(package, tmp_path / "staging")
    assert staged.executable.read_text(encoding="utf-8") == "exe 1.1.0"


def test_uretilen_fark_paketi_kurulu_surume_uygulanabiliyor(tmp_path: Path) -> None:
    old = _dist(tmp_path, "1.0.0", {"_internal/gidecek.dll": "eski"})
    new = _dist(tmp_path, "1.1.0")
    changed, removed = diff_trees(tree_digests(old), tree_digests(new))
    package = write_delta(new, changed, removed, tmp_path / "delta.zip")

    staged = stage_delta(package, old, tmp_path / "staging")

    assert staged.executable.read_text(encoding="utf-8") == "exe 1.1.0"
    assert (staged.path / "_internal" / "PySide6" / "Qt6Core.dll").read_text(encoding="utf-8") == "qt sabit"
    assert not (staged.path / "_internal" / "gidecek.dll").exists()
    # Sonuç, tam paketten kurulmuş hâliyle birebir aynı olmalı.
    assert tree_digests(staged.path) == tree_digests(new)


def test_fark_paketi_tam_paketten_belirgin_kucuktur(tmp_path: Path) -> None:
    """Sistemin bütün gerekçesi bu."""
    old = _dist(tmp_path, "1.0.0", {"_internal/buyuk.dll": "x" * 200_000})
    new = _dist(tmp_path, "1.1.0", {"_internal/buyuk.dll": "x" * 200_000})
    changed, removed = diff_trees(tree_digests(old), tree_digests(new))
    full = write_full(new, tmp_path / "full.zip")
    delta = write_delta(new, changed, removed, tmp_path / "delta.zip")
    assert delta.stat().st_size < full.stat().st_size / 2


def test_manifest_kendi_dogrulayicimizdan_geciyor(tmp_path: Path) -> None:
    dist = _dist(tmp_path, "1.1.0")
    full = write_full(dist, tmp_path / "OfficeReminder-1.1.0-win64.zip")
    manifest = build_manifest(
        version="1.1.0",
        full_path=full,
        delta_path=None,
        previous_version=None,
        notes="Deneme",
        released="2026-09-20",
        min_version="1.0.0",
    )
    release = parse_manifest(json.dumps(manifest).encode("utf-8"))
    assert release.version_text == "1.1.0"
    assert release.full.size == full.stat().st_size


def test_komut_satiri_uctan_uca_uretiyor(tmp_path: Path) -> None:
    old = _dist(tmp_path, "1.0.0")
    new = _dist(tmp_path, "1.1.0")
    out = tmp_path / "release"

    code = main([
        "--dist", str(new),
        "--out", str(out),
        "--previous", str(old),
        "--previous-version", "1.0.0",
        "--version", "1.1.0",
        "--notes", "Mini sayaç eklendi.",
    ])

    assert code == 0
    release = parse_manifest((out / "latest.json").read_bytes())
    assert release.version_text == "1.1.0"
    assert release.delta is not None and release.delta_from == (1, 0, 0)
    assert (out / "OfficeReminder-1.1.0-win64.zip").is_file()
    assert (out / "OfficeReminder-1.0.0-to-1.1.0-delta.zip").is_file()


def test_onceki_surum_verilmezse_fark_paketi_yok(tmp_path: Path) -> None:
    new = _dist(tmp_path, "1.1.0")
    out = tmp_path / "release"
    assert main(["--dist", str(new), "--out", str(out), "--version", "1.1.0"]) == 0
    release = parse_manifest((out / "latest.json").read_bytes())
    assert release.delta is None


def test_program_klasoru_olmayan_dizin_reddedilir(tmp_path: Path) -> None:
    folder = tmp_path / "rastgele"
    folder.mkdir()
    (folder / "okuma.txt").write_text("merhaba", encoding="utf-8")
    assert main(["--dist", str(folder), "--out", str(tmp_path / "out"), "--version", "1.1.0"]) == 2


def test_ayni_icerikte_fark_paketi_uretilmez(tmp_path: Path) -> None:
    dist = _dist(tmp_path, "1.1.0")
    out = tmp_path / "release"
    code = main([
        "--dist", str(dist),
        "--out", str(out),
        "--previous", str(dist),
        "--previous-version", "1.1.0",
        "--version", "1.1.0",
    ])
    assert code == 0
    assert parse_manifest((out / "latest.json").read_bytes()).delta is None
    assert not list(out.glob("*delta.zip"))


def test_silinecekler_listesi_fark_paketinde_tasiniyor(tmp_path: Path) -> None:
    old = _dist(tmp_path, "1.0.0", {"_internal/gidecek.dll": "eski"})
    new = _dist(tmp_path, "1.1.0")
    changed, removed = diff_trees(tree_digests(old), tree_digests(new))
    package = write_delta(new, changed, removed, tmp_path / "delta.zip")
    with zipfile.ZipFile(package) as archive:
        payload = json.loads(archive.read(DELTA_MANIFEST).decode("utf-8"))
    assert payload["removed"] == ["_internal/gidecek.dll"]
