"""GİB 2026 Vergi Takvimi — Real Source Acquisition & Normalization (Faz 3 düzeltme).

TEMEL KURAL: Official calendar için source of truth yalnızca GİB'in yayımladığı gerçek takvimdir.
Bu araç:
  1. GİB'in resmi Vergi Takvimi API'sinden (https://gib.gov.tr/api/gibportal/vergiTakvimi/specification/listAll)
     doğrudan veri çeker (fail-closed).
  2. Raw snapshot'ı resources/source/gib/2026/ altında saklar (acquisition metadata ile).
  3. Raw veriyi normalize eder — tarih üretmez, GİB'in verdiği stopdate'i kullanır.
  4. Obligation mapping'i gerçek GİB taxType/subject/description'e göre yapar; e-Defter 4 alt tipe ayrılır.
  5. resources/seed/official_calendar_2026.json üretir ve validate eder.
  6. Raw → normalized lineage ve count'ları raporlar. Generated/fake event asla üretmez.

Kullanım:
  python tools/import_gib_calendar.py --year 2026
  python tools/import_gib_calendar.py --year 2026 --validate
  python tools/import_gib_calendar.py --year 2026 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
import urllib.request
import urllib.error

# Ensure console can handle utf-8 and invisible chars without cp1254 crash
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "resources" / "seed" / "official_calendar_2026.json"
DEFAULT_RAW_DIR = PROJECT_ROOT / "resources" / "source" / "gib" / "2026"

GIB_API_URL = "https://gib.gov.tr/api/gibportal/vergiTakvimi/specification/listAll"
GIB_WEB_URL = "https://gib.gov.tr/vergi-takvimi"
GIB_PDF_URL = "https://cdn.gib.gov.tr/api/gibportal-file/file/getFileResources?objectKey=arsiv/onceki-dokumanlar/2026_vergi_takvimi.pdf"

PARSER_VERSION = "2.0.0-real-gib-faz3"

# ---------------------------------------------------------------------------
# Obligation mapping — gerçek GİB taxonomy'ine göre
# ---------------------------------------------------------------------------

# e-Defter 4 alt tip için description keywordleri
EDEFTER_MAP = {
    "AYLIK_GELIR": "Aylık Yükleme Tercihinde Bulunmuş Gelir Vergisi",
    "AYLIK_DIGER": "Aylık Yükleme Tercihinde Bulunmuş Diğer",
    "GECICI_GELIR": "Geçici Vergi Dönemleri Bazında Yükleme Tercihinde Bulunmuş Gelir Vergisi",
    "GECICI_DIGER": "Geçici Vergi Dönemleri Bazında Yükleme Tercihinde Bulunmuş Diğer",
}


def map_obligation(raw: dict[str, Any]) -> str | None:
    tax = (raw.get("taxType") or "").strip()
    subject = (raw.get("subject") or "").strip()
    title = (raw.get("title") or "").strip()
    desc = (raw.get("description") or "").strip()

    # 1. MUHSGK — description contains MUHSGK, taxType is Gelir Vergisi or Gelir Vergisi,Kurumlar Vergisi
    if "Muhtasar ve Prim Hizmet Beyannamesi" in desc:
        return "GIB_MUHSGK"

    # 2. e-Defter — Vergi Usul Kanunu + Berat + Elektronik Defter
    if tax == "Vergi Usul Kanunu" and subject == "Berat" and "Elektronik Defter" in title:
        if EDEFTER_MAP["AYLIK_GELIR"] in desc:
            return "GIB_EDEFTER_AYLIK_GELIR"
        if EDEFTER_MAP["AYLIK_DIGER"] in desc:
            return "GIB_EDEFTER_AYLIK_DIGER"
        if EDEFTER_MAP["GECICI_GELIR"] in desc:
            return "GIB_EDEFTER_GECICI_GELIR"
        if EDEFTER_MAP["GECICI_DIGER"] in desc:
            return "GIB_EDEFTER_GECICI_DIGER"
        # fallback for Berat but not matching 4
        return "GIB_VUK_GENEL"

    # 3. Direct taxType mapping (existing + new)
    direct = {
        "Katma Değer Vergisi": "GIB_KDV",
        "Damga Vergisi": "GIB_DAMGA",
        "Kurum Geçici Vergisi": "GIB_GECICI_KURUMLAR",
        "Kurumlar Vergisi": "GIB_KURUMLAR",
        "Motorlu Taşıtlar Vergisi": "GIB_MTV",
        "Özel Tüketim Vergisi": "GIB_OZEL_TUKETIM",
        "Eğlence Vergisi": "GIB_EGLENCE",
        "Harçlar Kanunu": "GIB_HARCLAR",
        "Türkiye Turizm Tanıtım ve Geliştirme Ajansı Hakkında Kanun": "GIB_TURIZM",
        "Gelir Vergisi": "GIB_GELIR_VERGISI",
        "Veraset ve İntikal Vergisi": "GIB_VERASET",
        "Noterlerce Tahsil Edilen Vergi Resim ve Harçlar ile Değerli Kağıt Bedelleri": "GIB_NOTER",
        "Banka ve Sigorta Muameleleri Vergisi": "GIB_BSMV",
        "Özel İletişim Vergisi": "GIB_OIV",
        "Kaynak Kullanımını Destekleme Fonu": "GIB_KKDF",
        "Kaynak Kullanımını Destekleme Fonu ": "GIB_KKDF",
        "Şans Oyunları Vergisi": "GIB_SANS",
        "Elektrik ve Havagazı Tüketim Vergisi": "GIB_ELEKTRIK",
        "İlan ve Reklam Vergisi": "GIB_ILAN",
        "Yangın Sigortası Vergisi": "GIB_YANGIN",
        "Konaklama Vergisi": "GIB_KONAKLAMA",
        "7440 Sayılı Kanun": "GIB_7440",
        "Haberleşme Vergisi": "GIB_HABERLESME",
        "Dijital Hizmet Vergisi": "GIB_DIJITAL",
        "Çevre Kanunu,Vergi Usul Kanunu": "GIB_CEVRE_VUK",
        "Gelir Geçici Vergisi": "GIB_GELIR_GECICI",
        "Değerli Konut Vergisi": "GIB_DEGERLI_KONUT",
        "Yerel Asgari Tamamlayıcı Kurumlar Vergisi": "GIB_YEREL_ASGARI",
        "Küresel Asgari Tamamlayıcı Kurumlar Vergisi": "GIB_KURESEL_ASGARI",
        "Çevre Temizlik Vergisi": "GIB_CEVRE_TEMIZLIK",
        "Emlak Vergisi": "GIB_EMLAK",
        "Vergi Usul Kanunu": "GIB_VUK_BILDIRIM",  # non-Berat Vergi Usul -> bildirim
        "Gelir Vergisi,Kurumlar Vergisi": "GIB_MUHSGK",  # also MUHSGK, but already handled via desc, keep for safety
    }
    clean_tax = tax.strip()
    if clean_tax in direct:
        return direct[clean_tax]
    # handle with trailing space already covered
    return None


def fetch_gib_raw(year: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch raw GIB data for given year via API (daily-style payload for year). Returns (items, acquisition_meta)."""
    payload = {
        "globalOperator": "AND",
        "searchRequestListDTOS": [
            {
                "column": "startdate",
                "value": f"{year}-12-31T23:59:59",
                "joinTable": "subject",
                "operation": "LESS_THAN",
                "formatDate": True,
                "formatBoolean": False,
            },
            {
                "column": "stopdate",
                "value": f"{year}-01-01T00:00:00",
                "joinTable": "subject",
                "operation": "GREATER_THAN",
                "formatDate": True,
                "formatBoolean": False,
            },
        ],
    }
    url = f"{GIB_API_URL}?page=0&size=5000&sortFieldName=stopdate&sortType=ASC"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "OfficeReminder/1.0 (+https://gib.gov.tr/vergi-takvimi)",
            "Accept": "application/json",
        },
    )
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            if resp.status != 200:
                raise RuntimeError(f"GIB API HTTP {resp.status}")
            body = resp.read()
            raw_hash = hashlib.sha256(body).hexdigest()
            j = json.loads(body.decode("utf-8"))
            rc = j.get("resultContainer")
            items = rc if isinstance(rc, list) else rc.get("content", []) if isinstance(rc, dict) else []
            if not isinstance(items, list):
                raise ValueError(f"Unexpected resultContainer type: {type(items)}")
            meta = {
                "source_url": GIB_API_URL,
                "web_url": GIB_WEB_URL,
                "fetched_at": fetched_at,
                "request_payload": payload,
                "raw_content_hash": raw_hash,
                "raw_bytes": len(body),
                "items_fetched": len(items),
                "parser_version": PARSER_VERSION,
            }
            return items, meta
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GIB API HTTPError {e.code}: {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"GIB API fetch failed: {e}") from e


def fetch_pdf_snapshot(raw_dir: Path) -> dict[str, Any] | None:
    """Try to fetch yearly PDF snapshot (optional, not fail-closed for API)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = raw_dir / "2026_vergi_takvimi.pdf"
    try:
        req = urllib.request.Request(GIB_PDF_URL, headers={"User-Agent": "OfficeReminder/1.0"})
        with urllib.request.urlopen(req, timeout=40) as resp:
            if resp.status != 200:
                return {"error": f"HTTP {resp.status}"}
            data = resp.read()
            pdf_hash = hashlib.sha256(data).hexdigest()
            pdf_path.write_bytes(data)
            return {
                "pdf_url": GIB_PDF_URL,
                "pdf_path": str(pdf_path.relative_to(PROJECT_ROOT)),
                "pdf_hash": pdf_hash,
                "pdf_bytes": len(data),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        return {"error": str(e), "pdf_url": GIB_PDF_URL}


def normalize_events(raw_items: list[dict[str, Any]], year: int, acquisition_meta: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Normalize raw GIB items to official_calendar_events. No date generation — uses GIB stopdate.
    Returns (normalized_events, unmapped_items, stats).
    """
    normalized: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for raw in raw_items:
        raw_id = raw.get("id")
        tax = raw.get("taxType", "")
        subject = raw.get("subject", "")
        title = raw.get("title", "")
        desc = raw.get("description", "")
        period_desc = raw.get("periodDescription", "")
        start_raw = raw.get("startdate", "")
        stop_raw = raw.get("stopdate", "")

        # Parse dates: raw is ISO like "2026-01-08T00:00:00"
        try:
            # stopdate is due date
            stop_date = stop_raw.split("T")[0]  # YYYY-MM-DD
            start_date = start_raw.split("T")[0] if start_raw else None
            # validate
            date.fromisoformat(stop_date)
            if start_date:
                date.fromisoformat(start_date)
        except Exception:
            unmapped.append({**raw, "_reason": "invalid date"})
            continue

        obligation_code = map_obligation(raw)
        if obligation_code is None:
            unmapped.append(raw)
            continue

        # Use GIB's stopdate as both normal and effective — no weekend adjust per new rule
        normal_due = stop_date
        effective_due = stop_date

        # source_event_key: GIB_{id} ensures unique and traceable to raw
        source_event_key = f"GIB_{raw_id}"

        if source_event_key in seen_keys:
            # duplicate id — should not happen
            unmapped.append({**raw, "_reason": "duplicate source_event_key"})
            continue
        seen_keys.add(source_event_key)

        # period_key: use raw periodDescription as key, plus year for disambiguation if needed
        # Keep periodDescription as period_key/label for traceability
        period_key = period_desc.strip() if period_desc else f"ID_{raw_id}"
        period_label = period_desc.strip() if period_desc else period_key

        # Build provenance with full lineage
        provenance = {
            "acquisition": {
                "source_url": acquisition_meta["source_url"],
                "web_url": acquisition_meta["web_url"],
                "fetched_at": acquisition_meta["fetched_at"],
                "raw_content_hash": acquisition_meta["raw_content_hash"],
                "parser_version": PARSER_VERSION,
            },
            "raw": {
                "id": raw_id,
                "taxType": tax,
                "subject": subject,
                "title": title,
                "description": desc,
                "periodDescription": period_desc,
                "startdate": start_raw,
                "stopdate": stop_raw,
                "priority": raw.get("priority"),
            },
            "mapping": {
                "obligation_code": obligation_code,
                "mapped_from": f"{tax} | {subject}",
            },
            "note": "Real GIB data, no date generation. effective_due_date == GIB stopdate.",
        }

        # Eligibility metadata — subject/taxpayer/upload preference
        subject_kind = subject
        taxpayer_kind = None
        upload_preference = None
        filing_kind = None
        eligibility_tags: list[str] = []

        if obligation_code in ("GIB_EDEFTER_AYLIK_GELIR", "GIB_EDEFTER_AYLIK_DIGER", "GIB_EDEFTER_GECICI_GELIR", "GIB_EDEFTER_GECICI_DIGER"):
            if "AYLIK_GELIR" in obligation_code:
                taxpayer_kind = "GELIR"
                upload_preference = "MONTHLY"
            elif "AYLIK_DIGER" in obligation_code:
                taxpayer_kind = "DIGER"
                upload_preference = "MONTHLY"
            elif "GECICI_GELIR" in obligation_code:
                taxpayer_kind = "GELIR"
                upload_preference = "TEMPORARY_PERIOD"
            elif "GECICI_DIGER" in obligation_code:
                taxpayer_kind = "DIGER"
                upload_preference = "TEMPORARY_PERIOD"
            filing_kind = "BERAT"
            eligibility_tags = [taxpayer_kind, upload_preference, filing_kind]
        elif obligation_code == "GIB_KDV":
            # Distinguish KDV variants: Tevkifat vs Standard, and Standard monthly vs quarterly
            is_quarterly = period_desc.count("-") >= 2 or "Ekim-Kasım-Aralık" in period_desc or "Ocak-Şubat-Mart" in period_desc or "Nisan-Mayıs-Haziran" in period_desc or "Temmuz-Ağustos-Eylül" in period_desc
            is_tevkifat = "Tevkifat" in title
            if is_tevkifat:
                filing_kind = "TEVKIFAT"
                eligibility_tags = ["KDV_TEVKIFAT"]
            else:
                if is_quarterly:
                    filing_kind = "STANDARD_QUARTERLY"
                    eligibility_tags = ["KDV_STANDARD_QUARTERLY"]
                else:
                    filing_kind = "STANDARD_MONTHLY"
                    eligibility_tags = ["KDV_STANDARD_MONTHLY"]
        elif obligation_code == "GIB_MUHSGK":
            filing_kind = "BEYAN"
            eligibility_tags = ["MUHSGK"]
        else:
            filing_kind = subject
            eligibility_tags = [obligation_code]

        event = {
            "obligation_code": obligation_code,
            "source_kind": "GIB",
            "source_event_key": source_event_key,
            "title": title.strip(),
            "description": desc.strip(),
            "period_key": period_key,
            "period_label": period_label,
            "year": year,
            "normal_due_date": normal_due,
            "effective_due_date": effective_due,
            "due_time": None,
            "source_url": GIB_WEB_URL,
            "source_published_at": acquisition_meta["fetched_at"],
            "provenance": provenance,
            "subject_kind": subject_kind,
            "taxpayer_kind": taxpayer_kind,
            "filing_kind": filing_kind,
            "upload_preference": upload_preference,
            "eligibility_tags": eligibility_tags,
            # lineage helpers for tests
            "_raw_id": raw_id,
            "_raw_stopdate": stop_raw,
        }
        normalized.append(event)

    # Sort by effective_due_date then obligation_code for determinism
    normalized.sort(key=lambda e: (e["effective_due_date"], e["obligation_code"], e["source_event_key"]))

    stats = {
        "raw_total": len(raw_items),
        "normalized_total": len(normalized),
        "unmapped_total": len(unmapped),
        "obligation_counts": dict(Counter(e["obligation_code"] for e in normalized)),
        "taxType_counts": dict(Counter(r.get("taxType", "?") for r in raw_items)),
        "generated_count": 0,  # MUST be 0 per requirement
    }

    return normalized, unmapped, stats


def build_payload(year: int, normalized: list[dict[str, Any]], unmapped: list[dict[str, Any]], acquisition_meta: dict[str, Any], pdf_meta: dict[str, Any] | None) -> dict[str, Any]:
    # Remove internal helpers before hashing
    events_for_hash = []
    for e in normalized:
        # copy without _raw helpers
        ev = {k: v for k, v in e.items() if not k.startswith("_")}
        events_for_hash.append(ev)
    content_hash = hashlib.sha256(json.dumps(events_for_hash, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    payload = {
        "schema_version": 1,
        "year": year,
        "source": "GIB",
        "status": "POPULATED_REAL",
        "acquisition": acquisition_meta,
        "pdf_snapshot": pdf_meta,
        "parser_version": PARSER_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": content_hash,
        "notes": "Real GIB Vergi Takvimi verisinden normalize edildi. Tarih üretilmedi; GİB stopdate kullanıldı. e-Defter 4 alt tipe ayrıldı.",
        "counts": dict(Counter(e["obligation_code"] for e in normalized)),
        "total_events": len(normalized),
        "unmapped_count": len(unmapped),
        "unmapped": unmapped[:20],  # sample for debugging, full unmapped stored separately
        "generated_count": 0,
        "events": events_for_hash,
    }
    return payload


def validate_real_payload(payload: dict[str, Any], raw_items: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version 1 olmalı")
    if payload.get("generated_count", 0) != 0:
        errors.append("generated_count 0 olmalı (fabricated event yasak)")
    events = payload.get("events", [])
    if len(events) == 0:
        errors.append("events boş olamaz (real GIB verisi beklenir)")
    # Check that every event has provenance with raw lineage
    for idx, e in enumerate(events):
        if not e.get("provenance", {}).get("raw", {}).get("id"):
            errors.append(f"events[{idx}] raw lineage eksik")
        if e.get("provenance", {}).get("acquisition", {}).get("raw_content_hash") != payload.get("acquisition", {}).get("raw_content_hash"):
            errors.append(f"events[{idx}] raw_content_hash mismatch")
        # effective == normal (no weekend adjust) — must equal GIB stopdate
        # We can check that effective == normal and both are valid dates
        try:
            nd = date.fromisoformat(e["normal_due_date"])
            ed = date.fromisoformat(e["effective_due_date"])
            if nd != ed:
                errors.append(f"events[{idx}] normal != effective (GİB tarihi değiştirilmemeli) {e['source_event_key']}")
            if ed.weekday() >= 5:
                # Note: GİB's real due can be weekend — we do NOT adjust, so weekend is allowed
                # So we don't error on weekend, just warn? But requirement says effective initially equals GİB due, so weekend allowed
                pass
        except Exception as ve:
            errors.append(f"events[{idx}] date parse: {ve}")
        # unique key
    keys = [e["source_event_key"] for e in events]
    if len(keys) != len(set(keys)):
        errors.append("duplicate source_event_key")
    # Check that unmapped is reported, not silently dropped
    if payload.get("unmapped_count", 0) > 0 and len(payload.get("unmapped", [])) == 0:
        errors.append("unmapped var ama sample yok")
    # Check that total_events matches obligation counts sum
    if payload.get("total_events") != sum(payload.get("counts", {}).values()):
        errors.append("counts total mismatch")
    # Check that raw_total == normalized + unmapped (if we store raw)
    raw_total = payload.get("acquisition", {}).get("items_fetched", len(raw_items))
    if raw_total != len(events) + payload.get("unmapped_count", 0):
        errors.append(f"raw_total {raw_total} != normalized {len(events)} + unmapped {payload.get('unmapped_count')}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="GİB real takvim acquisition & normalization (Faz 3 düzeltme)")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--validate", action="store_true", help="Sadece validate et, yazma")
    parser.add_argument("--dry-run", action="store_true", help="Yazma, özet göster")
    args = parser.parse_args()

    year = args.year
    output: Path = args.output
    raw_dir: Path = args.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"[acquisition] GİB API'den {year} verisi çekiliyor...")
    try:
        raw_items, acquisition_meta = fetch_gib_raw(year)
    except Exception as e:
        print(f"[acquisition] FAILED (fail-closed): {e}")
        print("Mevcut official data overwrite edilmeyecek. Import başarısız.")
        return 3

    print(f"[acquisition] {len(raw_items)} raw items fetched, hash {acquisition_meta['raw_content_hash'][:12]}")

    # Save raw snapshot
    raw_snapshot_path = raw_dir / f"gib_api_raw_{year}.json"
    raw_payload = {
        "acquisition": acquisition_meta,
        "year": year,
        "raw_items": raw_items,
    }
    raw_snapshot_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[raw] Snapshot yazıldı: {raw_snapshot_path} ({raw_snapshot_path.stat().st_size} bytes)")

    # Try PDF snapshot (optional)
    pdf_meta = fetch_pdf_snapshot(raw_dir)
    if pdf_meta and "pdf_hash" in pdf_meta:
        print(f"[pdf] Snapshot: {pdf_meta['pdf_path']} hash {pdf_meta['pdf_hash'][:12]}")
    else:
        print(f"[pdf] Snapshot failed or skipped: {pdf_meta}")

    # Normalize
    normalized, unmapped, stats = normalize_events(raw_items, year, acquisition_meta)
    print(f"[normalize] raw {stats['raw_total']} -> normalized {stats['normalized_total']} (unmapped {stats['unmapped_total']})")
    print(f"[normalize] obligation breakdown:")
    for code, cnt in sorted(stats["obligation_counts"].items()):
        print(f"  {code}: {cnt}")
    if unmapped:
        print(f"[unmapped] {len(unmapped)} items (örnek 5):")
        for it in unmapped[:5]:
            print(f"  - {it.get('taxType')} | {it.get('subject')} | {it.get('title')[:60]}")

    if stats["generated_count"] != 0:
        print("FATAL: generated_count 0 olmalı!")
        return 2

    payload = build_payload(year, normalized, unmapped, acquisition_meta, pdf_meta)
    # Also save full unmapped to separate file for audit
    if unmapped:
        unmapped_path = raw_dir / f"gib_unmapped_{year}.json"
        unmapped_path.write_text(json.dumps(unmapped, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[unmapped] Full list yazıldı: {unmapped_path}")

    errors = validate_real_payload(payload, raw_items)
    if errors:
        print("VALIDATION FAILED (fail-closed, dosyaya yazılmayacak):")
        for e in errors:
            print(f"  - {e}")
        return 2
    else:
        print(f"Validation OK: {len(normalized)} events, generated 0, unmapped {len(unmapped)}")

    if args.validate:
        print("Validate modu: dosyaya yazılmadı.")
        return 0
    if args.dry_run:
        print(f"Dry-run: {output} yazılmadı.")
        return 0

    # Fail-closed check: if payload has errors, don't overwrite existing seed
    # Write to output
    output.parent.mkdir(parents=True, exist_ok=True)
    # Also save acquisition lineage separately
    lineage_path = raw_dir / f"lineage_{year}.json"
    lineage_path.write_text(json.dumps({
        "acquisition": acquisition_meta,
        "pdf_snapshot": pdf_meta,
        "stats": stats,
        "payload_hash": payload["content_hash"],
        "generated_at": payload["generated_at"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[lineage] Yazıldı: {lineage_path}")

    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[seed] Yazıldı: {output} ({len(normalized)} events, hash {payload['content_hash'][:12]})")
    print(f"[seed] Raw → normalized lineage kanıtlandı: raw {len(raw_items)} -> normalized {len(normalized)} + unmapped {len(unmapped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
