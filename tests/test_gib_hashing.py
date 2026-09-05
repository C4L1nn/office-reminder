import hashlib
import json
from pathlib import Path

import pytest

from database.connection import Database
from database.migrations import MigrationRunner


def test_gib_canonical_hash_stable(tmp_path: Path) -> None:
    # Same semantic payload with different key order should have same canonical hash
    payload1 = {"b": 2, "a": 1, "items": [{"id": 2, "title": "B"}, {"id": 1, "title": "A"}]}
    payload2 = {"a": 1, "b": 2, "items": [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]}

    def canonical_hash(items):
        sorted_items = sorted(items, key=lambda x: x["id"])
        return hashlib.sha256(json.dumps(sorted_items, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    h1 = canonical_hash(payload1["items"])
    h2 = canonical_hash(payload2["items"])
    assert h1 == h2

    # Also test that GIB sync's normalized hash is stable for same raw data
    from services.gib_sync_service import GibSyncService

    db = Database(tmp_path / "hash.db")
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    MigrationRunner(db, migrations).run()
    svc = GibSyncService(db, raw_dir=tmp_path / "gib")
    # Use same raw data twice with different fetched_at
    raw_items = [{"id": 1, "title": "Test", "taxType": "Katma Değer Vergisi", "subject": "Beyan ve Ödeme", "periodDescription": "Test", "startdate": "2026-01-01T00:00:00", "stopdate": "2026-01-31T00:00:00", "priority": 1}]
    meta1 = {"source_url": "https://gib.gov.tr", "web_url": "https://gib.gov.tr/vergi-takvimi", "fetched_at": "2026-01-01T00:00:00+00:00", "raw_content_hash": "abc", "parser_version": "test"}
    meta2 = {**meta1, "fetched_at": "2026-01-02T00:00:00+00:00"}
    norm1, _ = svc._normalize(raw_items, 2026, meta1)
    norm2, _ = svc._normalize(raw_items, 2026, meta2)
    # Compute canonical hash as service does
    def norm_hash(normalized):
        canonical = []
        for ev in normalized:
            ev_copy = {k: v for k, v in ev.items() if k not in ("source_published_at", "provenance")}
            prov = ev.get("provenance", {})
            raw = prov.get("raw", {}) if isinstance(prov, dict) else {}
            canonical_prov = {"raw": {"id": raw.get("id"), "taxType": raw.get("taxType"), "stopdate": raw.get("stopdate")}, "mapping": prov.get("mapping", {}) if isinstance(prov, dict) else {}}
            ev_copy["provenance_canonical"] = canonical_prov
            canonical.append(ev_copy)
        canonical.sort(key=lambda x: x["source_event_key"])
        return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    assert norm_hash(norm1) == norm_hash(norm2)
