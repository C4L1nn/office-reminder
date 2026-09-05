"""SGK announcement discovery and processing.

Pipeline, with every page handled in its own iteration:

    for page in pages:
        fetch -> validate -> parse -> dedup -> watermark

then, per new/changed notice:

    detail fetch -> body (or attachment text) -> analyze -> findings
                 -> match official events -> revision (or NEEDS_REVIEW)

The business rules live in :mod:`services.sgk_notice_analyzer` and operate on
what an announcement says. No rule is keyed on an announcement identifier, so a
newly published announcement is processed exactly like the ones used in tests.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from database.connection import Database
from services.document_text import extract_pdf_text, is_pdf
from services.sgk_notice_analyzer import (
    NATIONAL_GLOBAL,
    NATIONAL_OBLIGATION_SPECIFIC,
    PAYMENT,
    REPORTING,
    Finding,
    NoticeAnalysis,
    analyze,
)
from services.sgk_notice_parser import (
    BASE_URL,
    NoticeDetail,
    NoticeLink,
    parse_detail_page,
    parse_list_page,
    parse_page_numbers,
)

logger = logging.getLogger("office_reminder.sgk")

SOURCE_CODE = "SGK_NOTICES"
USER_AGENT = "OfficeReminder/1.0 (+https://www.sgk.gov.tr/duyuru)"

# "Sigorta Primleri Genel Müdürlüğü" publishes the premium/declaration deadline
# announcements this app cares about.
SGK_LIST_URL = f"{BASE_URL}/duyuru/index/SIGORTA-PRIMLERI-GENEL-MUDURLUGU-2026-04-09-02-52-13"
MAX_PAGES = 3
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


class SgkNoticeService:
    def __init__(
        self,
        database: Database,
        raw_dir: Path | None = None,
        list_url: str = SGK_LIST_URL,
        fetcher=None,
    ) -> None:
        self.database = database
        if raw_dir is None:
            from app.paths import get_runtime_root

            raw_dir = get_runtime_root() / "data" / "official_sources" / "sgk"
        self.raw_dir = Path(raw_dir)
        self.list_url = list_url
        # Injectable so the production pipeline can be exercised against saved
        # snapshots of the real pages without touching the network.
        self._fetch = fetcher or _http_get

    # ------------------------------------------------------------------ discovery
    def discover_notices(self, max_pages: int = MAX_PAGES) -> list[NoticeLink]:
        """Walk the announcement list, one page per iteration.

        Each page is fetched, validated, parsed and deduplicated on its own; the
        watermark (newest announcement already stored) stops the walk once a page
        contains nothing newer.
        """
        watermark = self.get_watermark()
        found: dict[str, NoticeLink] = {}

        first_html = self._fetch_text(self._page_url(0))
        if first_html is None:
            return []
        pages = [p for p in parse_page_numbers(first_html) if p < max_pages] or [0]

        for page in pages:
            html = first_html if page == 0 else self._fetch_text(self._page_url(page))
            if not html or "/duyuru/detay/" not in html:
                logger.info("SGK list page %s unusable, stopping walk", page)
                break

            links = parse_list_page(html)
            if not links:
                logger.info("SGK list page %s parsed 0 cards, stopping walk", page)
                break

            fresh = 0
            for link in links:
                if link.source_notice_key in found:
                    continue
                found[link.source_notice_key] = link
                if watermark is None or link.published_at >= watermark:
                    fresh += 1

            # Pages are newest-first: once a whole page predates the watermark
            # there is nothing new further back.
            if watermark is not None and fresh == 0:
                break

        return sorted(found.values(), key=lambda n: n.published_at, reverse=True)

    def get_watermark(self) -> str | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT MAX(published_at) AS newest FROM official_notices WHERE provider='SGK'"
            ).fetchone()
        return row["newest"] if row and row["newest"] else None

    def _page_url(self, page: int) -> str:
        # The site's pager is 0-based: ?page=0 is the first page.
        separator = "&" if "?" in self.list_url else "?"
        return f"{self.list_url}{separator}page={page}"

    def _fetch_text(self, url: str) -> str | None:
        try:
            body, _headers = self._fetch(url)
        except Exception as exc:
            logger.warning("SGK fetch failed for %s: %s", url, exc)
            return None
        return body.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ detail
    def fetch_detail(self, link: NoticeLink) -> NoticeDetail:
        html = self._fetch_text(link.source_url)
        if html is None:
            return NoticeDetail(title=link.title, published_at=link.published_at)
        self._snapshot(f"details/{link.source_notice_key}.html", html.encode("utf-8"))
        detail = parse_detail_page(html)
        detail.title = detail.title or link.title
        detail.published_at = detail.published_at or link.published_at
        return detail

    def attachment_text(self, link: NoticeLink, detail: NoticeDetail) -> str:
        """Text of the announcement's PDF attachments, '' when unavailable."""
        chunks: list[str] = []
        for attachment in detail.attachments:
            try:
                payload, headers = self._fetch(attachment["url"])
            except Exception as exc:
                logger.info("SGK attachment fetch failed (%s): %s", attachment["url"], exc)
                continue
            if len(payload) > MAX_ATTACHMENT_BYTES:
                logger.info("SGK attachment too large, skipped: %s", attachment["url"])
                continue
            content_type = headers.get("content-type") if headers else None
            if not is_pdf(attachment.get("filename"), content_type):
                continue
            digest = hashlib.sha256(payload).hexdigest()
            path = self._snapshot(
                f"attachments/{link.source_notice_key}_{digest[:8]}.pdf", payload
            )
            if path is None:
                continue
            text = extract_pdf_text(path)
            if text:
                chunks.append(text)
        return "\n".join(chunks)

    def _snapshot(self, relative: str, payload: bytes) -> Path | None:
        try:
            path = self.raw_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            return path
        except OSError:
            logger.warning("Could not write SGK snapshot %s", relative, exc_info=True)
            return None

    # ------------------------------------------------------------------ processing
    def process_notice(
        self,
        link: NoticeLink,
        detail: NoticeDetail | None = None,
        attachment_text: str | None = None,
    ) -> dict[str, Any]:
        """Analyze one announcement and persist the outcome."""
        detail = detail if detail is not None else self.fetch_detail(link)
        body = detail.body or ""
        if len(body) < 40:
            # Body-less announcements keep their text in the attached PDF.
            extra = attachment_text if attachment_text is not None else self.attachment_text(link, detail)
            if extra:
                body = f"{body}\n{extra}".strip()

        title = detail.title or link.title
        published_at = detail.published_at or link.published_at
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

        previous = self._existing(link.source_notice_key)
        if previous and previous["body_hash"] == body_hash and previous["status"] != "DETECTED":
            # Same text, already concluded: re-reading it must not re-apply anything.
            return {
                "status": previous["status"],
                "reason": "unchanged",
                "reprocessed": False,
                "findings": 0,
                "applied": 0,
                "notice_id": previous["id"],
            }

        analysis = analyze(title, body, published_at=published_at)
        notice_id = self._upsert_notice(
            link, title, published_at, body_hash, analysis, status="DETECTED"
        )

        findings = [self._apply_finding(notice_id, finding, title, link.source_url) for finding in analysis.findings]
        status = self._aggregate_status(analysis, findings)
        self._set_status(notice_id, status)

        return {
            "status": status,
            "classification": analysis.classification,
            "scope_kind": analysis.scope_kind,
            "reason": analysis.reason,
            "reprocessed": True,
            "findings": len(findings),
            "applied": sum(1 for f in findings if f["status"] == "AUTO_APPLIED"),
            "notice_id": notice_id,
        }

    @staticmethod
    def _aggregate_status(analysis: NoticeAnalysis, findings: list[dict]) -> str:
        if not analysis.relevant:
            return "NO_RELEVANT_CHANGE"
        if not findings:
            return "NEEDS_REVIEW"
        if any(f["status"] == "NEEDS_REVIEW" for f in findings):
            return "NEEDS_REVIEW"
        if all(f["status"] == "NO_MATCH" for f in findings):
            return "NEEDS_REVIEW"
        return "AUTO_APPLIED"

    def _apply_finding(self, notice_id: int, finding: Finding, title: str, source_url: str) -> dict:
        """Match a finding to official events and, when safe, write the revision."""
        if finding.finding_kind == REPORTING:
            # Never touch GIB_MUHSGK: its dates come from the GİB calendar.
            matched = self._find_gib_muhsgk(finding.old_due_date)
            return self._record_finding(
                notice_id,
                finding,
                status="NEEDS_REVIEW",
                matched_event_id=matched,
                revision_id=None,
                reason="MuhSGK sigorta bildirimleri kısmı — GİB vergi eventine otomatik uygulanmaz",
            )

        if not finding.auto_appliable:
            return self._record_finding(
                notice_id, finding, status="NEEDS_REVIEW", reason=f"kapsam: {finding.scope_kind}"
            )

        targets = self._match_payment_events(finding)
        if not targets:
            return self._record_finding(
                notice_id, finding, status="NO_MATCH", reason="eşleşen SGK 4/a eventi bulunamadı"
            )

        applied: list[tuple[int, int]] = []
        skipped: list[str] = []
        for event_id, event_key, current_due in targets:
            if finding.new_due_date <= date.fromisoformat(current_due):
                # An extension must move a deadline later; anything else is not
                # this announcement's business.
                skipped.append(event_key)
                continue
            revision_id = self._create_revision(
                event_id, current_due, finding.new_due_date, title, source_url
            )
            if revision_id is not None:
                applied.append((event_id, revision_id))

        if not applied:
            return self._record_finding(
                notice_id,
                finding,
                status="NO_MATCH" if not skipped else "IGNORED",
                reason="uygulanabilir event yok (yeni tarih mevcut vadeden ileri değil)",
            )

        first_event, first_revision = applied[0]
        return self._record_finding(
            notice_id,
            finding,
            status="AUTO_APPLIED",
            matched_event_id=first_event,
            revision_id=first_revision,
            reason=f"{len(applied)} event güncellendi",
            extra={"applied_event_ids": [e for e, _ in applied], "skipped": skipped},
        )

    def _match_payment_events(self, finding: Finding) -> list[tuple[int, str, str]]:
        """SGK 4/a events this finding refers to, as (id, key, effective_due)."""
        with self.database.session() as connection:
            if finding.period:
                year, month = finding.period
                rows = connection.execute(
                    """
                    SELECT id, source_event_key, effective_due_date
                    FROM official_calendar_events
                    WHERE source_kind='SGK'
                      AND is_withdrawn = 0
                      AND obligation_type_id = (SELECT id FROM obligation_types WHERE code='SGK_4A_PREMIUM')
                      AND source_event_key LIKE ?
                    """,
                    (f"SGK_4A_{year:04d}_{month:02d}_%",),
                ).fetchall()
            elif finding.old_due_date:
                stamp = finding.old_due_date.isoformat()
                rows = connection.execute(
                    """
                    SELECT id, source_event_key, effective_due_date
                    FROM official_calendar_events
                    WHERE source_kind='SGK'
                      AND is_withdrawn = 0
                      AND obligation_type_id = (SELECT id FROM obligation_types WHERE code='SGK_4A_PREMIUM')
                      AND (effective_due_date = ? OR normal_due_date = ?)
                    """,
                    (stamp, stamp),
                ).fetchall()
            else:
                rows = []
        return [(r["id"], r["source_event_key"], r["effective_due_date"]) for r in rows]

    def _find_gib_muhsgk(self, due: date | None) -> int | None:
        if due is None:
            return None
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT id FROM official_calendar_events
                WHERE source_kind='GIB'
                  AND obligation_type_id = (SELECT id FROM obligation_types WHERE code='GIB_MUHSGK')
                  AND effective_due_date = ?
                LIMIT 1
                """,
                (due.isoformat(),),
            ).fetchone()
        return row["id"] if row else None

    def _create_revision(
        self, event_id: int, old_due: str, new_due: date, title: str, source_url: str
    ) -> int | None:
        stamp = new_due.isoformat()
        with self.database.session() as connection:
            existing = connection.execute(
                "SELECT id FROM official_calendar_revisions WHERE official_event_id=? AND new_due_date=?",
                (event_id, stamp),
            ).fetchone()
            if existing:
                return None
            cursor = connection.execute(
                """
                INSERT INTO official_calendar_revisions
                    (official_event_id, old_due_date, new_due_date, reason, source_url, raw_reference_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    old_due,
                    stamp,
                    f"SGK duyurusu: {title[:120]}",
                    source_url,
                    json.dumps({"old_due": old_due, "new_due": stamp}, ensure_ascii=False),
                ),
            )
            revision_id = int(cursor.lastrowid)
            # normal_due_date stays untouched; only the effective date moves.
            connection.execute(
                "UPDATE official_calendar_events SET effective_due_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (stamp, event_id),
            )
        return revision_id

    # ------------------------------------------------------------------ persistence
    def _existing(self, key: str):
        with self.database.session() as connection:
            return connection.execute(
                "SELECT id, body_hash, status FROM official_notices WHERE provider='SGK' AND source_notice_key=?",
                (key,),
            ).fetchone()

    def _upsert_notice(
        self,
        link: NoticeLink,
        title: str,
        published_at: str | None,
        body_hash: str,
        analysis: NoticeAnalysis,
        status: str,
    ) -> int:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO official_notices
                    (provider, source_notice_key, title, published_at, source_url, raw_hash, body_hash,
                     classification, scope_kind, scope_json, status, acquired_at, details_json)
                VALUES ('SGK', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, source_notice_key) DO UPDATE SET
                    title = excluded.title,
                    published_at = excluded.published_at,
                    source_url = excluded.source_url,
                    raw_hash = excluded.raw_hash,
                    body_hash = excluded.body_hash,
                    classification = excluded.classification,
                    scope_kind = excluded.scope_kind,
                    scope_json = excluded.scope_json,
                    status = excluded.status,
                    acquired_at = excluded.acquired_at,
                    details_json = excluded.details_json
                """,
                (
                    link.source_notice_key,
                    title,
                    published_at,
                    link.source_url,
                    body_hash,
                    body_hash,
                    analysis.classification,
                    analysis.scope_kind,
                    json.dumps({"period": analysis.period}, ensure_ascii=False),
                    status,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps({"reason": analysis.reason, "relevant": analysis.relevant}, ensure_ascii=False),
                ),
            )
            row = connection.execute(
                "SELECT id FROM official_notices WHERE provider='SGK' AND source_notice_key=?",
                (link.source_notice_key,),
            ).fetchone()
            notice_id = int(row["id"])
            # Findings are recomputed from the current text on every change.
            connection.execute("DELETE FROM official_notice_findings WHERE notice_id=?", (notice_id,))
        return notice_id

    def _set_status(self, notice_id: int, status: str) -> None:
        with self.database.session() as connection:
            connection.execute(
                "UPDATE official_notices SET status=?, processed_at=? WHERE id=?",
                (status, datetime.now(timezone.utc).isoformat(), notice_id),
            )

    def _record_finding(
        self,
        notice_id: int,
        finding: Finding,
        *,
        status: str,
        matched_event_id: int | None = None,
        revision_id: int | None = None,
        reason: str = "",
        extra: dict | None = None,
    ) -> dict:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO official_notice_findings
                    (notice_id, finding_kind, obligation_code, old_due_date, new_due_date,
                     scope_kind, status, matched_event_id, revision_id, reason, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notice_id,
                    finding.finding_kind,
                    finding.obligation_code,
                    finding.old_due_date.isoformat() if finding.old_due_date else None,
                    finding.new_due_date.isoformat(),
                    finding.scope_kind,
                    status,
                    matched_event_id,
                    revision_id,
                    reason or finding.reason,
                    json.dumps(
                        {"period": finding.period, **(extra or {})}, ensure_ascii=False
                    ),
                ),
            )
        return {
            "finding_kind": finding.finding_kind,
            "status": status,
            "revision_id": revision_id,
            "matched_event_id": matched_event_id,
        }

    # ------------------------------------------------------------------ orchestration
    def sync(self, max_pages: int = MAX_PAGES) -> dict:
        """Full run, recorded in official_sync_runs / official_source_state."""
        started_at = datetime.now(timezone.utc).isoformat()
        run_id = self._start_run(started_at)
        stats = {
            "source_code": SOURCE_CODE,
            "discovered": 0,
            "processed": 0,
            "auto_applied": 0,
            "needs_review": 0,
            "no_change": 0,
            "unchanged": 0,
            "status": "FAILED",
        }
        error: str | None = None

        try:
            links = self.discover_notices(max_pages=max_pages)
            stats["discovered"] = len(links)
            if not links:
                raise RuntimeError("SGK duyuru listesi okunamadı veya boş döndü")

            for link in links:
                try:
                    result = self.process_notice(link)
                except Exception as exc:  # one bad notice must not fail the run
                    logger.warning("SGK notice processing failed for %s: %s", link.source_notice_key, exc)
                    continue
                if not result.get("reprocessed"):
                    # Already-concluded announcement whose text has not changed.
                    stats["unchanged"] += 1
                    continue
                stats["processed"] += 1
                stats["auto_applied"] += result.get("applied", 0)
                if result["status"] == "NEEDS_REVIEW":
                    stats["needs_review"] += 1
                elif result["status"] == "NO_RELEVANT_CHANGE":
                    stats["no_change"] += 1

            stats["status"] = "UPDATED" if stats["auto_applied"] else "SYNCED"
        except Exception as exc:
            error = str(exc)
            logger.warning("SGK notice sync failed: %s", exc)
        finally:
            self._finish_run(run_id, stats, error)
            self._write_source_state(stats, error)

        if error:
            stats["error"] = error
        return stats

    def _start_run(self, started_at: str) -> int:
        with self.database.session() as connection:
            cursor = connection.execute(
                "INSERT INTO official_sync_runs (source_code, source_kind, started_at, status) "
                "VALUES (?, 'SGK', ?, 'RUNNING')",
                (SOURCE_CODE, started_at),
            )
            return int(cursor.lastrowid)

    def _finish_run(self, run_id: int, stats: dict, error: str | None) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                UPDATE official_sync_runs
                SET finished_at=?, status=?, items_seen=?, items_changed=?, items_unchanged=?,
                    error_message=?, details_json=?
                WHERE id=?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    "FAILED" if error else stats["status"],
                    stats["discovered"],
                    stats["auto_applied"],
                    stats["no_change"],
                    error,
                    json.dumps(stats, ensure_ascii=False),
                    run_id,
                ),
            )

    def _write_source_state(self, stats: dict, error: str | None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.session() as connection:
            if error:
                connection.execute(
                    """
                    INSERT INTO official_source_state (source_code, source_kind, status, last_attempt_at, last_error, details_json)
                    VALUES (?, 'SGK', 'FAILED', ?, ?, ?)
                    ON CONFLICT(source_code) DO UPDATE SET
                        status='FAILED', last_attempt_at=excluded.last_attempt_at,
                        last_error=excluded.last_error, details_json=excluded.details_json
                    """,
                    (SOURCE_CODE, now, error, json.dumps(stats, ensure_ascii=False)),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO official_source_state
                        (source_code, source_kind, status, last_attempt_at, last_success_at,
                         last_successful_sync_at, last_checked_at, last_changed_at, last_error, details_json)
                    VALUES (?, 'SGK', ?, ?, ?, ?, ?, ?, NULL, ?)
                    ON CONFLICT(source_code) DO UPDATE SET
                        status=excluded.status,
                        last_attempt_at=excluded.last_attempt_at,
                        last_success_at=excluded.last_success_at,
                        last_successful_sync_at=excluded.last_successful_sync_at,
                        last_checked_at=excluded.last_checked_at,
                        last_changed_at=COALESCE(excluded.last_changed_at, official_source_state.last_changed_at),
                        last_error=NULL,
                        details_json=excluded.details_json
                    """,
                    (
                        SOURCE_CODE,
                        stats["status"],
                        now,
                        now,
                        now,
                        now,
                        now if stats["auto_applied"] else None,
                        json.dumps(stats, ensure_ascii=False),
                    ),
                )

    # ------------------------------------------------------------------ reads
    def list_notices(self, status: str | None = None, limit: int = 50) -> list[dict]:
        with self.database.session() as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM official_notices WHERE provider='SGK' AND status=? "
                    "ORDER BY published_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM official_notices WHERE provider='SGK' ORDER BY published_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_findings(self, notice_id: int) -> list[dict]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM official_notice_findings WHERE notice_id=? ORDER BY id", (notice_id,)
            ).fetchall()
        return [dict(row) for row in rows]


def _http_get(url: str, timeout: int = 20) -> tuple[bytes, dict]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise urllib.error.HTTPError(url, response.status, "unexpected status", response.headers, None)
        return response.read(), dict(response.headers)


def snapshot_fetcher(mapping: dict[str, bytes]):
    """Fetcher backed by saved snapshots — used to test the production pipeline."""

    def fetch(url: str, timeout: int = 20) -> tuple[bytes, dict]:
        if url not in mapping:
            raise urllib.error.URLError(f"no snapshot for {url}")
        payload = mapping[url]
        content_type = "application/pdf" if payload[:4] == b"%PDF" else "text/html; charset=utf-8"
        return payload, {"content-type": content_type}

    return fetch
