"""Bir sürümü yayına hazırlar: tam paket, fark paketi ve manifest.

Elle yürütülen bir yayın süreci er geç kayar — özet bir sürüm eskiye kalır,
boyut yanlış yazılır, fark paketi bir önceki sürümden değil iki öncekinden
üretilir. Burada üçü de aynı ölçümden çıkıyor.

Kullanım:

    python tools/make_release.py --dist dist/OfficeReminder --out dist/release
    python tools/make_release.py --dist dist/OfficeReminder --out dist/release \\
        --previous dist/OfficeReminder-1.0.0 --previous-version 1.0.0 \\
        --notes "Mini sayaç eklendi."

`--previous`, bir önceki sürümün **açılmış** paket klasörüdür. Verilmezse
yalnızca tam paket üretilir ve manifestte fark paketi yer almaz; o zaman
herkes tam paketi iner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.update_swap import DELTA_MANIFEST  # noqa: E402

#: İndirme adresleri bu kalıptan üretilir; varlıklar `gh release create` ile
#: aynı etikete yüklenir.
ASSET_URL = (
    "https://github.com/C4L1nn/office-reminder-releases/"
    "releases/download/v{version}/{name}"
)

TOP_LEVEL = "OfficeReminder"


def digest_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def tree_digests(root: Path) -> dict[str, str]:
    """Klasördeki her dosyanın göreli yolu -> sha256."""
    root = Path(root)
    return {
        str(path.relative_to(root)).replace("\\", "/"): digest_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def diff_trees(old: dict[str, str], new: dict[str, str]) -> tuple[list[str], list[str]]:
    """(fark pakete girecek dosyalar, silinecek dosyalar).

    Değişen ve yeni eklenen dosyalar pakete girer; eskide olup yenide olmayan
    her yol silinecekler listesine düşer. İkisi ayrı tutulmak zorunda: bir
    dosyanın *kalktığını* "değişen dosyalar" listesiyle anlatmanın yolu yok.
    """
    changed = sorted(path for path, sha in new.items() if old.get(path) != sha)
    removed = sorted(set(old) - set(new))
    return changed, removed


def write_full(dist: Path, destination: Path) -> Path:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(dist.rglob("*")):
            if path.is_file():
                archive.write(path, f"{TOP_LEVEL}/{path.relative_to(dist)}")
    return destination


def write_delta(dist: Path, changed: list[str], removed: list[str], destination: Path) -> Path:
    """Fark paketi: yalnızca değişen dosyalar, artı silinecekler listesi.

    Dosyalar tepe klasöre sarılmaz; paket kurulu klasörün kopyası *üzerine*
    serilecek, kendi başına bir program klasörü değil.
    """
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in changed:
            archive.write(dist / relative, relative)
        archive.writestr(
            DELTA_MANIFEST,
            json.dumps({"removed": removed}, ensure_ascii=False, indent=2),
        )
    return destination


def build_manifest(
    version: str,
    full_path: Path,
    delta_path: Path | None,
    previous_version: str | None,
    notes: str,
    released: str,
    min_version: str,
) -> dict:
    manifest = {
        "schema": 1,
        "version": version,
        "released": released,
        "notes": notes,
        "min_version": min_version,
        "full": {
            "url": ASSET_URL.format(version=version, name=full_path.name),
            "sha256": digest_file(full_path),
            "size": full_path.stat().st_size,
        },
    }
    if delta_path is not None and previous_version:
        manifest["delta"] = {
            "from": previous_version,
            "url": ASSET_URL.format(version=version, name=delta_path.name),
            "sha256": digest_file(delta_path),
            "size": delta_path.stat().st_size,
        }
    return manifest


def main(argv: list[str] | None = None) -> int:
    from datetime import date

    parser = argparse.ArgumentParser(description="Sürüm paketlerini ve manifesti üretir")
    parser.add_argument("--dist", required=True, type=Path, help="Yeni paket klasörü")
    parser.add_argument("--out", required=True, type=Path, help="Çıktı klasörü")
    parser.add_argument("--previous", type=Path, help="Bir önceki sürümün paket klasörü")
    parser.add_argument("--previous-version", help="Bir önceki sürümün numarası")
    parser.add_argument("--notes", default="", help="Sürüm notu (kullanıcıya gösterilir)")
    parser.add_argument("--min-version", default="1.0.0")
    parser.add_argument("--version", help="Varsayılan: app/version.py")
    args = parser.parse_args(argv)

    if not args.dist.is_dir():
        print(f"Paket klasörü yok: {args.dist}", file=sys.stderr)
        return 2
    if not (args.dist / "OfficeReminder.exe").is_file():
        print(f"{args.dist} bir program klasörüne benzemiyor", file=sys.stderr)
        return 2

    version = args.version
    if not version:
        from app.version import APP_VERSION

        version = APP_VERSION

    args.out.mkdir(parents=True, exist_ok=True)
    full_path = args.out / f"OfficeReminder-{version}-win64.zip"
    write_full(args.dist, full_path)
    print(f"tam paket    : {full_path.name}  {full_path.stat().st_size / 1048576:.1f} MB")

    delta_path = None
    if args.previous:
        if not args.previous_version:
            print("--previous verildiğinde --previous-version de gerekir", file=sys.stderr)
            return 2
        if not args.previous.is_dir():
            print(f"Önceki paket klasörü yok: {args.previous}", file=sys.stderr)
            return 2
        changed, removed = diff_trees(tree_digests(args.previous), tree_digests(args.dist))
        if not changed and not removed:
            print("önceki sürümle aynı içerik; fark paketi üretilmedi")
        else:
            delta_path = args.out / (
                f"OfficeReminder-{args.previous_version}-to-{version}-delta.zip"
            )
            write_delta(args.dist, changed, removed, delta_path)
            print(
                f"fark paketi  : {delta_path.name}  "
                f"{delta_path.stat().st_size / 1048576:.1f} MB  "
                f"({len(changed)} değişen, {len(removed)} silinen)"
            )

    manifest = build_manifest(
        version=version,
        full_path=full_path,
        delta_path=delta_path,
        previous_version=args.previous_version,
        notes=args.notes,
        released=date.today().isoformat(),
        min_version=args.min_version,
    )
    manifest_path = args.out / "latest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"manifest     : {manifest_path}")

    # Manifest, kendi ürettiğimiz doğrulayıcıdan geçmeden yayına gitmesin.
    from services.update_service import parse_manifest

    parse_manifest(manifest_path.read_bytes())
    print("manifest doğrulandı")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
