"""Orchestrates the GİB and SGK official-source checks.

Each source is fail-closed and independent: one failing must never stop the
other, and neither may overwrite local data on a suspicious response. After a
run, every official date change that companies are actually subject to is
announced through the real notification channel — a delivery row is written
only once the notification was shown.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from database.connection import Database

logger = logging.getLogger("office_reminder.sync")

SYNC_INTERVAL_HOURS = 6
# Only revisions detected recently are announced; a historical backfill should
# not produce a burst of toasts.
ANNOUNCE_WINDOW_DAYS = 14


class OfficialUpdateService:
    def __init__(
        self,
        database: Database,
        raw_dir: Path | None = None,
        notifier=None,
    ) -> None:
        self.database = database
        if raw_dir is None:
            from app.paths import get_runtime_root

            raw_dir = get_runtime_root() / "data" / "official_sources"
        self.raw_dir = Path(raw_dir)
        self.notifier = notifier

    # ------------------------------------------------------------------ scheduling
    def should_sync(self, source_code: str, hours: int = SYNC_INTERVAL_HOURS) -> bool:
        """True when this source has not been checked *online* recently.

        Only `last_success_at` counts. `last_successful_sync_at` is also written
        by the bundled-seed import, and treating that as a check would leave a
        fresh install claiming the calendar was verified against GİB when it
        never contacted it.
        """
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT last_success_at FROM official_source_state WHERE source_code = ?",
                (source_code,),
            ).fetchone()
        if row is None:
            return True
        last = row["last_success_at"]
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        except ValueError:
            return True
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last_dt) > timedelta(hours=hours)

    # ------------------------------------------------------------------ sources
    def sync_gib(self, year: int | None = None, timeout: int = 30) -> dict[str, Any]:
        year = year or datetime.now().year  # business year is local, not UTC
        from services.gib_sync_service import GibSyncService

        service = GibSyncService(self.database, raw_dir=self.raw_dir / "gib")
        try:
            result = service.sync(year, timeout=timeout)
        except Exception as exc:
            logger.warning("GİB sync failed for %s: %s", year, exc)
            return {"status": "FAILED", "error": str(exc), "source_code": f"GIB_{year}"}
        if result.get("changed", 0) > 0:
            result["announced"] = self.announce_revisions("GIB")
        return result

    def sync_sgk(self, max_pages: int = 3) -> dict[str, Any]:
        from services.sgk_notice_service import SgkNoticeService

        service = SgkNoticeService(self.database, raw_dir=self.raw_dir / "sgk")
        try:
            result = service.sync(max_pages=max_pages)
        except Exception as exc:
            logger.warning("SGK notice sync failed: %s", exc)
            return {"status": "FAILED", "error": str(exc), "source_code": "SGK_NOTICES"}
        if result.get("auto_applied", 0) > 0:
            result["announced"] = self.announce_revisions("SGK")
        return result

    def sync_all(self, years: list[int] | None = None) -> dict[str, Any]:
        now = datetime.now()
        if years is None:
            years = [now.year]
            if now.month >= 10:  # next year's calendar is published in Q4
                years.append(now.year + 1)

        results: dict[str, Any] = {"gib": {}, "sgk": {}}
        for year in years:
            code = f"GIB_{year}"
            if self.should_sync(code):
                results["gib"][str(year)] = self.sync_gib(year)
            else:
                results["gib"][str(year)] = {"status": "SKIPPED", "reason": "recently synced"}

        if self.should_sync("SGK_NOTICES"):
            results["sgk"] = self.sync_sgk()
        else:
            results["sgk"] = {"status": "SKIPPED", "reason": "recently synced"}
        return results

    # ------------------------------------------------------------------ announcements
    def announce_revisions(self, source_kind: str | None = None, today: date | None = None) -> int:
        """Show a Windows notification for each new official date change.

        One notification per (company, revision). Companies are only told about
        obligations they are actually subject to, and the delivery row is
        written by the notification service after the toast was shown, so a
        failed notification is retried on the next run instead of being lost.
        """
        if self.notifier is None:
            return 0

        today = today or date.today()
        floor = (today - timedelta(days=ANNOUNCE_WINDOW_DAYS)).isoformat()
        shown = 0

        with self.database.session() as connection:
            query = """
                SELECT r.id AS revision_id, r.old_due_date, r.new_due_date,
                       oce.id AS event_id, oce.source_kind, ot.name AS obligation_name, ot.code AS obligation_code
                FROM official_calendar_revisions r
                JOIN official_calendar_events oce ON oce.id = r.official_event_id
                JOIN obligation_types ot ON ot.id = oce.obligation_type_id
                WHERE substr(r.detected_at, 1, 10) >= ?
                  AND r.new_due_date >= ?
            """
            # A revision is news only while its new date is still ahead. A new
            # install's first sync detects every change of the year at once;
            # without this it announced "31 Mart → 7 Nisan" in September.
            params: list = [floor, today.isoformat()]
            if source_kind:
                query += " AND oce.source_kind = ?"
                params.append(source_kind)
            query += " ORDER BY r.detected_at DESC LIMIT 50"
            revisions = connection.execute(query, tuple(params)).fetchall()

            pending: list[tuple[int, str, Any]] = []
            for revision in revisions:
                companies = connection.execute(
                    """
                    SELECT DISTINCT v.company_id, v.company_name
                    FROM v_active_official_company_events v
                    WHERE v.official_event_id = ?
                    """,
                    (revision["event_id"],),
                ).fetchall()
                pending.extend((row["company_id"], row["company_name"], revision) for row in companies)

        for company_id, company_name, revision in pending:
            try:
                if self.notifier.notify_official_revision(
                    event_id=revision["event_id"],
                    company_id=company_id,
                    company_name=company_name,
                    obligation_name=revision["obligation_name"],
                    old_due=date.fromisoformat(revision["old_due_date"]),
                    new_due=date.fromisoformat(revision["new_due_date"]),
                    source=revision["source_kind"],
                    revision_id=revision["revision_id"],
                ):
                    shown += 1
            except Exception:
                logger.warning("Revision notification failed", exc_info=True)
        return shown

    # ------------------------------------------------------------------ reads
    def status_summary(self) -> list[dict]:
        """One row per official source, shaped for the Settings screen.

        GİB and SGK each get exactly one row. The SGK row reports the *online
        announcement* check (source_code SGK_NOTICES) — not the locally computed
        SGK 4/a rule calendar, which would otherwise look like a successful
        online sync that never happened.
        """
        state = {row["source_code"]: row for row in self.get_sync_state()}

        gib_codes = sorted((code for code in state if code.startswith("GIB_")), reverse=True)
        gib = state.get(gib_codes[0]) if gib_codes else None
        sgk = state.get("SGK_NOTICES")

        with self.database.session() as connection:
            pending = connection.execute(
                "SELECT COUNT(*) AS c FROM official_notices WHERE status = 'NEEDS_REVIEW'"
            ).fetchone()["c"]
            rule_years = connection.execute(
                "SELECT COUNT(*) AS c FROM official_source_state WHERE source_code LIKE 'SGK_4A_%' AND status='SYNCED'"
            ).fetchone()["c"]

        # `last_success_at` is written only by an online check. The seed import
        # writes `last_successful_sync_at`, so the two must not be conflated:
        # a bundled calendar is loaded, not verified against the source.
        gib_online = (gib or {}).get("last_success_at")
        gib_seeded = (gib or {}).get("last_successful_sync_at")
        gib_detail = f"{len(gib_codes)} yıl izleniyor" if gib_codes else "Henüz veri yok"
        if not gib_online and gib_seeded:
            gib_detail = f"{gib_detail} · paketle gelen takvim yüklü, henüz çevrimiçi doğrulanmadı"

        return [
            {
                "code": "GIB",
                "label": "GİB Vergi Takvimi",
                "status": (gib or {}).get("status", "NEVER_SYNCED") if gib_online else "NEVER_SYNCED",
                "last_success_at": gib_online,
                "last_attempt_at": (gib or {}).get("last_attempt_at"),
                "last_error": (gib or {}).get("last_error"),
                "detail": gib_detail,
                "pending_review": 0,
            },
            {
                "code": "SGK",
                "label": "SGK Duyuruları",
                "status": (sgk or {}).get("status", "NEVER_SYNCED"),
                "last_success_at": (sgk or {}).get("last_success_at"),
                "last_attempt_at": (sgk or {}).get("last_attempt_at"),
                "last_error": (sgk or {}).get("last_error"),
                "detail": f"SGK 4/a kural takvimi: {rule_years} yıl üretildi",
                "pending_review": int(pending),
            },
        ]

    def list_revisions(self, limit: int = 100) -> list[dict]:
        """Official date changes, newest first, for the history view."""
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT r.id, r.detected_at, r.old_due_date, r.new_due_date, r.reason, r.source_url,
                       oce.title, oce.source_event_key, oce.source_kind, oce.period_label,
                       ot.name AS obligation_name
                FROM official_calendar_revisions r
                JOIN official_calendar_events oce ON oce.id = r.official_event_id
                JOIN obligation_types ot ON ot.id = oce.obligation_type_id
                ORDER BY r.detected_at DESC, r.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_pending_reviews(self, limit: int = 50) -> list[dict]:
        """Announcements that changed something but need a human decision."""
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT n.id, n.title, n.published_at, n.source_url, n.scope_kind, n.classification,
                       f.finding_kind, f.obligation_code, f.old_due_date, f.new_due_date, f.reason
                FROM official_notices n
                LEFT JOIN official_notice_findings f ON f.notice_id = n.id AND f.status = 'NEEDS_REVIEW'
                WHERE n.status = 'NEEDS_REVIEW'
                ORDER BY n.published_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_sync_state(self) -> list[dict]:
        with self.database.session() as connection:
            rows = connection.execute("SELECT * FROM official_source_state ORDER BY source_code").fetchall()
        return [dict(row) for row in rows]

    def get_recent_runs(self, limit: int = 10) -> list[dict]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM official_sync_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_notices(self, status: str | None = None, limit: int = 20) -> list[dict]:
        with self.database.session() as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM official_notices WHERE status = ? ORDER BY published_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM official_notices ORDER BY published_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]
