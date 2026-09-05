from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from database.connection import Database
from services.holiday_service import HolidayService
from services.sgk_rule_engine import SgkRuleEngine


class SgkCalendarService:
    """SGK 4/a prim takvimi generation + official override handling.

    - Rule-generated SGK events: source_kind=SGK, rule_code/version, normal/effective ayrımı
    - Override: official_calendar_revisions + effective_due_date update, normal korunur
    - MUHSGK guard: SGK engine asla GIB_MUHSGK üretmez (GIB_MUHSGK → GİB official)
    """

    def __init__(self, database: Database, holiday_service: HolidayService | None = None) -> None:
        self.database = database
        self.holiday_service = holiday_service or HolidayService(database)

    def generate_and_import(self, year: int | None = None, wage_periods: list[str] | None = None) -> int:
        # Year-agnostic: if not provided, use current year
        if year is None:
            year = datetime.now(timezone.utc).year
        if wage_periods is None:
            # Default to 1_END for backward compat; caller can request both for full coverage
            wage_periods = ["MONTHLY_1_END"]

        # Fail-closed: check holiday data exists for this year and next year (for Dec due in Jan)
        # If not, do not generate and mark source_state as NEEDS_DATA
        years_needed = {year, year + 1}
        missing_years = []
        for y in years_needed:
            if not self.holiday_service.list_holidays(year=y):
                missing_years.append(y)
        if missing_years:
            with self.database.session() as conn:
                now = datetime.now(timezone.utc).isoformat()
                for y in missing_years:
                    conn.execute(
                        """
                        INSERT INTO official_source_state
                            (source_code, source_kind, last_seed_version, last_content_hash, last_successful_sync_at, last_checked_at, status, details_json)
                        VALUES (?, 'SGK', ?, '', ?, ?, 'NEEDS_DATA', ?)
                        ON CONFLICT(source_code) DO UPDATE SET
                            last_checked_at = excluded.last_checked_at,
                            status = 'NEEDS_DATA',
                            details_json = excluded.details_json
                        """,
                        (
                            f"SGK_4A_{y}",
                            SgkRuleEngine.RULE_VERSION,
                            now,
                            now,
                            json.dumps({"error": f"Holiday data missing for {y}", "year": y}, ensure_ascii=False),
                        ),
                    )
            return 0

        # Guard: ensure SGK_4A_PREMIUM obligation exists
        with self.database.session() as conn:
            row = conn.execute("SELECT id FROM obligation_types WHERE code='SGK_4A_PREMIUM'").fetchone()
            if row is None:
                raise ValueError("SGK_4A_PREMIUM obligation_type bulunamadı")

        events = SgkRuleEngine.generate_for_year(year, self.holiday_service, wage_periods=wage_periods)

        # MUHSGK guard: filter out any event that would be GIB_MUHSGK (should be 0 anyway)
        events = [e for e in events if not SgkRuleEngine.is_muhsgk_guard(e["obligation_code"])]

        inserted = 0
        with self.database.session() as connection:
            for ev in events:
                # Double-check: never insert GIB_MUHSGK via SGK engine
                if ev["obligation_code"] == "GIB_MUHSGK":
                    continue
                obligation = connection.execute(
                    "SELECT id FROM obligation_types WHERE code = ?", (ev["obligation_code"],)
                ).fetchone()
                if obligation is None:
                    raise ValueError(f"Bilinmeyen obligation_code: {ev['obligation_code']}")

                # Check for existing official GIB_MUHSGK duplicate guard:
                # If there's already a GIB_MUHSGK event for same period, skip SGK generation for that period? No, SGK_4A is different period, so not duplicate.
                # But ensure we don't create duplicate SGK event for same period
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO official_calendar_events (
                        obligation_type_id, source_kind, source_event_key,
                        title, period_key, period_label, year,
                        normal_due_date, effective_due_date, due_time,
                        source_url, source_published_at, provenance_json,
                        subject_kind, eligibility_tags, rule_code, rule_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obligation["id"],
                        ev["source_kind"],
                        ev["source_event_key"],
                        ev["title"],
                        ev["period_key"],
                        ev["period_label"],
                        ev["year"],
                        ev["normal_due_date"],
                        ev["effective_due_date"],
                        ev["due_time"],
                        ev["source_url"],
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps(ev["provenance"], ensure_ascii=False),
                        ev.get("subject_kind"),
                        json.dumps(ev.get("eligibility_tags"), ensure_ascii=False) if ev.get("eligibility_tags") else None,
                        ev.get("rule_code"),
                        ev.get("rule_version"),
                    ),
                )
                inserted += int(cursor.rowcount > 0)

            # Update official_source_state for SGK
            now = datetime.now(timezone.utc).isoformat()
            # Content hash for SGK year
            import hashlib
            content = json.dumps([e["source_event_key"] for e in events], sort_keys=True).encode("utf-8")
            chash = hashlib.sha256(content).hexdigest()
            connection.execute(
                """
                INSERT INTO official_source_state
                    (source_code, source_kind, last_seed_version, last_content_hash, last_successful_sync_at, last_checked_at, status, details_json)
                VALUES (?, 'SGK', ?, ?, ?, ?, 'SYNCED', ?)
                ON CONFLICT(source_code) DO UPDATE SET
                    last_seed_version = excluded.last_seed_version,
                    last_content_hash = excluded.last_content_hash,
                    last_successful_sync_at = excluded.last_successful_sync_at,
                    last_checked_at = excluded.last_checked_at,
                    status = excluded.status,
                    details_json = excluded.details_json
                """,
                (
                    f"SGK_4A_{year}",
                    SgkRuleEngine.RULE_VERSION,
                    chash,
                    now,
                    now,
                    json.dumps({"year": year, "total_events": len(events), "inserted": inserted}, ensure_ascii=False),
                ),
            )

        return inserted

    def apply_official_override(
        self,
        source_event_key: str,
        new_effective_date: date,
        reason: str,
        source_url: str,
        source_published_at: str | None = None,
    ) -> bool:
        """SGK resmi duyuru ile tarih uzatımı — fail-closed, revision saklanır."""
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT id, normal_due_date, effective_due_date FROM official_calendar_events WHERE source_event_key = ? AND source_kind='SGK'",
                (source_event_key,),
            ).fetchone()
            if row is None:
                raise ValueError(f"SGK event bulunamadı: {source_event_key}")
            old_effective = row["effective_due_date"]
            normal = row["normal_due_date"]
            event_id = row["id"]

            if new_effective_date.isoformat() == old_effective:
                return False  # no change

            # Create revision
            connection.execute(
                """
                INSERT INTO official_calendar_revisions
                    (official_event_id, old_due_date, new_due_date, reason, source_url, source_published_at, raw_reference_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    old_effective,
                    new_effective_date.isoformat(),
                    reason,
                    source_url,
                    source_published_at,
                    json.dumps({"normal_due_date": normal, "old_effective": old_effective, "new_effective": new_effective_date.isoformat()}, ensure_ascii=False),
                ),
            )
            # Update effective_due_date, keep normal
            connection.execute(
                "UPDATE official_calendar_events SET effective_due_date = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_effective_date.isoformat(), event_id),
            )
            return True

    def get_event(self, source_event_key: str) -> dict | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM official_calendar_events WHERE source_event_key = ?", (source_event_key,)
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def list_for_year(self, year: int) -> list[dict]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM official_calendar_events WHERE source_kind='SGK' AND year = ? ORDER BY effective_due_date",
                (year,),
            ).fetchall()
            return [dict(r) for r in rows]
