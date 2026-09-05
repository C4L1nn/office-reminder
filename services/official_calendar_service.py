from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from database.connection import Database


class OfficialCalendarSeedService:
    def __init__(self, database: Database, seed_dir: Path) -> None:
        self.database = database
        self.seed_dir = Path(seed_dir)

    def _validate_event(self, event: dict) -> None:
        required = ["obligation_code", "source_kind", "source_event_key", "title", "year", "normal_due_date", "effective_due_date", "source_url"]
        for field in required:
            if not event.get(field):
                raise ValueError(f"Event missing {field}: {event.get('source_event_key')}")
        if event["source_kind"] not in ("GIB", "SGK"):
            raise ValueError(f"source_kind must be GIB or SGK: {event['source_event_key']}")
        # date checks
        try:
            normal = date.fromisoformat(event["normal_due_date"])
            effective = date.fromisoformat(event["effective_due_date"])
        except Exception as e:
            raise ValueError(f"Invalid date for {event['source_event_key']}: {e}") from e
        if effective < normal:
            raise ValueError(f"effective < normal for {event['source_event_key']}")
        # For GIB, weekend is allowed (real GİB due can be weekend, no adjust)
        # For SGK, effective should not be weekend (adjusted)
        if event["source_kind"] == "SGK" and effective.weekday() >= 5:
            raise ValueError(f"SGK effective on weekend for {event['source_event_key']}: {effective}")
        if not event.get("provenance"):
            raise ValueError(f"provenance missing for {event['source_event_key']}")

    def import_seed(self, filename: str) -> int:
        path = self.seed_dir / filename
        if not path.exists():
            return 0

        payload = json.loads(path.read_text(encoding="utf-8"))
        events = payload.get("events", [])
        if not isinstance(events, list):
            raise ValueError("events must be list")

        # Fail-closed: validate before touching DB
        # Check that payload is for expected year and not placeholder
        status = payload.get("status", "")
        if status == "PLACEHOLDER_NOT_POPULATED":
            # empty seed, nothing to do
            return 0
        if len(events) == 0:
            return 0

        # Validate each event (provenance required per PLAN.md:371)
        for ev in events:
            self._validate_event(ev)

        # Content hash for official_source_state
        content_hash = payload.get("content_hash")
        if not content_hash:
            content_hash = hashlib.sha256(json.dumps(events, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

        inserted = 0

        with self.database.session() as connection:
            for event in events:
                obligation = connection.execute(
                    "SELECT id FROM obligation_types WHERE code = ?",
                    (event["obligation_code"],),
                ).fetchone()
                if obligation is None:
                    raise ValueError(f"Bilinmeyen obligation_code: {event['obligation_code']}")

                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO official_calendar_events (
                        obligation_type_id, source_kind, source_event_key,
                        title, period_key, period_label, year,
                        normal_due_date, effective_due_date, due_time,
                        source_url, source_published_at, provenance_json,
                        subject_kind, taxpayer_kind, filing_kind, upload_preference, eligibility_tags, rule_code, rule_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obligation["id"],
                        event["source_kind"],
                        event["source_event_key"],
                        event["title"],
                        event.get("period_key"),
                        event.get("period_label"),
                        event["year"],
                        event["normal_due_date"],
                        event.get("effective_due_date", event["normal_due_date"]),
                        event.get("due_time"),
                        event["source_url"],
                        event.get("source_published_at"),
                        json.dumps(event.get("provenance", {}), ensure_ascii=False),
                        event.get("subject_kind"),
                        event.get("taxpayer_kind"),
                        event.get("filing_kind"),
                        event.get("upload_preference"),
                        json.dumps(event.get("eligibility_tags"), ensure_ascii=False) if event.get("eligibility_tags") is not None else None,
                        event.get("rule_code"),
                        event.get("rule_version"),
                    ),
                )
                inserted += int(cursor.rowcount > 0)

            # Update official_source_state (idempotent)
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO official_source_state
                    (source_code, source_kind, last_seed_version, last_content_hash, last_successful_sync_at, last_checked_at, status, details_json)
                VALUES (?, 'GIB', ?, ?, ?, ?, 'SYNCED', ?)
                ON CONFLICT(source_code) DO UPDATE SET
                    last_seed_version = excluded.last_seed_version,
                    last_content_hash = excluded.last_content_hash,
                    last_successful_sync_at = excluded.last_successful_sync_at,
                    last_checked_at = excluded.last_checked_at,
                    status = excluded.status,
                    details_json = excluded.details_json
                """,
                (
                    f"GIB_{payload.get('year', 2026)}",
                    payload.get("generator", "seed"),
                    content_hash,
                    now,
                    now,
                    json.dumps(
                        {
                            "filename": filename,
                            "total_events": len(events),
                            "counts": payload.get("counts", {}),
                            "year": payload.get("year"),
                            "inserted": inserted,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

        return inserted

    def get_source_state(self, source_code: str) -> dict | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM official_source_state WHERE source_code = ?", (source_code,)
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def validate_seed_file(self, filename: str) -> list[str]:
        """Validate without importing, return error list (empty = ok)."""
        path = self.seed_dir / filename
        if not path.exists():
            return [f"Dosya bulunamadı: {filename}"]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            return [f"JSON parse hatası: {e}"]
        errors: list[str] = []
        if payload.get("schema_version") != 1:
            errors.append("schema_version 1 olmalı")
        events = payload.get("events", [])
        if not events:
            errors.append("events boş")
        keys: set[str] = set()
        for idx, e in enumerate(events):
            for f in ["obligation_code", "source_kind", "source_event_key", "title", "year"]:
                if not e.get(f):
                    errors.append(f"events[{idx}] {f} eksik")
            key = e.get("source_event_key")
            if key in keys:
                errors.append(f"duplicate key {key}")
            keys.add(key)
            try:
                self._validate_event(e)
            except ValueError as ve:
                errors.append(str(ve))
        return errors
