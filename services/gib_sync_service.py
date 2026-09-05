from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from database.connection import Database
from services.gib_parser import PARSER_VERSION, map_obligation

GIB_API_URL = "https://gib.gov.tr/api/gibportal/vergiTakvimi/specification/listAll"
GIB_WEB_URL = "https://gib.gov.tr/vergi-takvimi"


class GibSyncService:
    """GIB calendar sync — ONLINE → SNAPSHOT → VALIDATE → NORMALIZE → DIFF → REVISION (fail-closed)."""

    def __init__(self, database: Database, raw_dir: Path | None = None) -> None:
        self.database = database
        from app.paths import get_runtime_root

        if raw_dir is None:
            raw_dir = get_runtime_root() / "data" / "official_sources" / "gib"
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _fetch_raw(self, year: int, timeout: int = 30) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        import urllib.request
        import urllib.error

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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(f"GIB API HTTP {resp.status}")
            body = resp.read()
            j = json.loads(body.decode("utf-8"))
            rc = j.get("resultContainer")
            items = rc if isinstance(rc, list) else rc.get("content", []) if isinstance(rc, dict) else []
            canonical_raw = sorted(items, key=lambda x: x.get("id", 0))
            raw_canonical_hash = hashlib.sha256(
                json.dumps(canonical_raw, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            transport_hash = hashlib.sha256(body).hexdigest()
            meta = {
                "source_url": GIB_API_URL,
                "web_url": GIB_WEB_URL,
                "fetched_at": fetched_at,
                "request_payload": payload,
                "raw_content_hash": raw_canonical_hash,
                "raw_transport_hash": transport_hash,
                "raw_bytes": len(body),
                "items_fetched": len(items),
                "parser_version": PARSER_VERSION,
                "http_status": resp.status,
            }
            return items, meta

    def _validate_raw(self, raw_items: list[dict[str, Any]]) -> list[str]:
        errors: list[str] = []
        if not isinstance(raw_items, list):
            errors.append("raw_items not list")
            return errors
        seen: set[int] = set()
        for idx, raw in enumerate(raw_items):
            if not isinstance(raw, dict):
                errors.append(f"raw[{idx}] not dict")
                continue
            if raw.get("id") is None:
                errors.append(f"raw[{idx}] missing id")
            elif raw["id"] in seen:
                errors.append(f"raw[{idx}] duplicate id {raw['id']}")
            else:
                seen.add(raw["id"])
            for field in ["title", "taxType", "subject", "periodDescription", "startdate", "stopdate"]:
                if not raw.get(field):
                    errors.append(f"raw[{idx}] missing {field}")
            for df in ["startdate", "stopdate"]:
                try:
                    date.fromisoformat(raw[df].split("T")[0])
                except Exception:
                    errors.append(f"raw[{idx}] {df} invalid {raw.get(df)}")
            try:
                stop_year = int(raw["stopdate"][:4])
                if stop_year < 2020 or stop_year > 2030:
                    errors.append(f"raw[{idx}] stop year out of range {stop_year}")
            except Exception:
                pass
        return errors

    def _normalize(self, raw_items: list[dict[str, Any]], year: int, acquisition_meta: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
            try:
                stop_date = stop_raw.split("T")[0]
                date.fromisoformat(stop_date)
            except Exception:
                unmapped.append({**raw, "_reason": "invalid date"})
                continue
            obligation_code = map_obligation(raw)
            if obligation_code is None:
                unmapped.append(raw)
                continue
            source_event_key = f"GIB_{raw_id}"
            if source_event_key in seen_keys:
                unmapped.append({**raw, "_reason": "duplicate"})
                continue
            seen_keys.add(source_event_key)
            period_key = period_desc.strip() if period_desc else f"ID_{raw_id}"
            period_label = period_desc.strip() if period_desc else period_key

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
                "mapping": {"obligation_code": obligation_code, "mapped_from": f"{tax} | {subject}"},
                "note": "Real GIB data, no date generation.",
            }

            event = {
                "obligation_code": obligation_code,
                "source_kind": "GIB",
                "source_event_key": source_event_key,
                "title": title.strip(),
                "description": desc.strip(),
                "period_key": period_key,
                "period_label": period_label,
                "year": year,
                "normal_due_date": stop_date,
                "effective_due_date": stop_date,
                "due_time": None,
                "source_url": GIB_WEB_URL,
                "source_published_at": acquisition_meta["fetched_at"],
                "provenance": provenance,
                "subject_kind": subject_kind,
                "taxpayer_kind": taxpayer_kind,
                "filing_kind": filing_kind,
                "upload_preference": upload_preference,
                "eligibility_tags": eligibility_tags,
            }
            normalized.append(event)
        normalized.sort(key=lambda e: (e["effective_due_date"], e["obligation_code"], e["source_event_key"]))
        return normalized, unmapped

    def _load_existing_events(self, year: int) -> dict[str, dict]:
        with self.database.session() as conn:
            rows = conn.execute(
                "SELECT * FROM official_calendar_events WHERE year = ? AND source_kind='GIB'", (year,)
            ).fetchall()
            return {r["source_event_key"]: dict(r) for r in rows}

    def sync(self, year: int, timeout: int = 30) -> dict:
        """Run full GIB sync for given year. Returns stats dict. Fail-closed on any validation error."""
        from datetime import datetime, timezone

        started_at = datetime.now(timezone.utc).isoformat()
        source_code = f"GIB_{year}"
        http_status = None
        raw_hash = None
        normalized_hash = None
        items_seen = 0
        added = 0
        changed = 0
        missing = 0
        unchanged = 0
        status = "FAILED"
        error_msg = None

        with self.database.session() as conn:
            conn.execute(
                "INSERT INTO official_sync_runs (source_code, source_kind, started_at, status) VALUES (?, 'GIB', ?, 'RUNNING')",
                (source_code, started_at),
            )
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        try:
            raw_items, acquisition_meta = self._fetch_raw(year, timeout=timeout)
            http_status = acquisition_meta.get("http_status", 200)
            raw_hash = acquisition_meta["raw_content_hash"]
            items_seen = len(raw_items)

            raw_errors = self._validate_raw(raw_items)
            if raw_errors:
                raise ValueError(f"Raw validation failed: {raw_errors[:3]}")

            normalized, unmapped = self._normalize(raw_items, year, acquisition_meta)
            if year == datetime.now().year and len(normalized) == 0:
                raise ValueError(f"Suspicious 0 items for current year {year} (fail-closed)")

            with self.database.session() as conn:
                prev = conn.execute(
                    "SELECT last_content_hash FROM official_source_state WHERE source_code = ?", (source_code,)
                ).fetchone()
                prev_hash = prev["last_content_hash"] if prev and prev["last_content_hash"] else None

            import hashlib, json

            canonical_for_hash = []
            for ev in normalized:
                ev_copy = {k: v for k, v in ev.items() if k not in ("source_published_at", "provenance")}
                prov = ev.get("provenance", {})
                raw = prov.get("raw", {}) if isinstance(prov, dict) else {}
                canonical_prov = {
                    "raw": {"id": raw.get("id"), "taxType": raw.get("taxType"), "stopdate": raw.get("stopdate")},
                    "mapping": prov.get("mapping", {}) if isinstance(prov, dict) else {},
                }
                ev_copy["provenance_canonical"] = canonical_prov
                canonical_for_hash.append(ev_copy)
            canonical_for_hash.sort(key=lambda x: x["source_event_key"])
            normalized_hash = hashlib.sha256(
                json.dumps(canonical_for_hash, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()

            existing = self._load_existing_events(year)
            existing_keys = set(existing.keys())
            new_keys = {e["source_event_key"] for e in normalized}
            normalized_by_key = {e["source_event_key"]: e for e in normalized}

            is_unchanged = prev_hash and prev_hash == normalized_hash
            if is_unchanged:
                status = "UNCHANGED"
                with self.database.session() as conn:
                    now = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        "UPDATE official_source_state SET last_checked_at = ?, last_attempt_at = ?, status = ? WHERE source_code = ?",
                        (now, now, status, source_code),
                    )
            else:
                # Snapshot only if changed
                raw_snapshot_path = self.raw_dir / f"gib_api_raw_{year}_{raw_hash[:8]}.json"
                raw_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                raw_snapshot_path.write_text(
                    json.dumps(
                        {"acquisition": acquisition_meta, "year": year, "raw_items": raw_items},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                norm_snapshot_path = self.raw_dir / f"gib_normalized_{year}_{normalized_hash[:8]}.json"
                norm_snapshot_path.write_text(
                    json.dumps(
                        {"year": year, "normalized": normalized, "unmapped": unmapped},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

            # Diff handling (even for UNCHANGED, we need to handle missing/withdrawn)
            added_keys = new_keys - existing_keys
            missing_keys = existing_keys - new_keys
            common_keys = new_keys & existing_keys

            # For UNCHANGED, added/changed will be 0, but missing may still be >0 (pending -> withdrawn)
            if not is_unchanged:
                for key in added_keys:
                    ev = normalized_by_key[key]
                    with self.database.session() as conn:
                        ot = conn.execute("SELECT id FROM obligation_types WHERE code = ?", (ev["obligation_code"],)).fetchone()
                        if ot is None:
                            continue
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO official_calendar_events (
                                obligation_type_id, source_kind, source_event_key,
                                title, period_key, period_label, year,
                                normal_due_date, effective_due_date, due_time,
                                source_url, source_published_at, provenance_json,
                                subject_kind, taxpayer_kind, filing_kind, upload_preference, eligibility_tags
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                ot["id"],
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
                                ev["source_published_at"],
                                json.dumps(ev["provenance"], ensure_ascii=False),
                                ev.get("subject_kind"),
                                ev.get("taxpayer_kind"),
                                ev.get("filing_kind"),
                                ev.get("upload_preference"),
                                json.dumps(ev.get("eligibility_tags"), ensure_ascii=False) if ev.get("eligibility_tags") else None,
                            ),
                        )
                        if conn.execute("SELECT changes()").fetchone()[0] > 0:
                            added += 1
                        else:
                            unchanged += 1

                for key in common_keys:
                    ev = normalized_by_key[key]
                    existing_row = existing[key]
                    if ev["effective_due_date"] != existing_row["effective_due_date"]:
                        with self.database.session() as conn:
                            rev_exists = conn.execute(
                                "SELECT 1 FROM official_calendar_revisions WHERE official_event_id = ? AND new_due_date = ?",
                                (existing_row["id"], ev["effective_due_date"]),
                            ).fetchone()
                            if rev_exists:
                                unchanged += 1
                                continue
                            conn.execute(
                                """
                                INSERT INTO official_calendar_revisions
                                    (official_event_id, old_due_date, new_due_date, reason, source_url, source_published_at, raw_reference_json)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    existing_row["id"],
                                    existing_row["effective_due_date"],
                                    ev["effective_due_date"],
                                    f"GIB official update for {ev['period_label']}",
                                    ev["source_url"],
                                    ev["source_published_at"],
                                    json.dumps({"raw_hash": raw_hash, "source_event_key": key}, ensure_ascii=False),
                                ),
                            )
                            conn.execute(
                                "UPDATE official_calendar_events SET effective_due_date = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (ev["effective_due_date"], existing_row["id"]),
                            )
                            changed += 1
                    else:
                        unchanged += 1
            else:
                # For UNCHANGED, all common are unchanged
                unchanged += len(common_keys)
                # Added is 0 as new_keys == existing_keys

            # Handle MISSING (both for changed and unchanged, for pending -> withdrawn)
            for key in missing_keys:
                existing_row = existing[key]
                with self.database.session() as conn:
                    cur_missing = existing_row.get("missing_since")
                    if cur_missing is None:
                        conn.execute(
                            "UPDATE official_calendar_events SET missing_since = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (datetime.now(timezone.utc).isoformat(), existing_row["id"]),
                        )
                        missing += 1
                    else:
                        conn.execute(
                            "UPDATE official_calendar_events SET is_withdrawn = 1, withdrawn_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (datetime.now(timezone.utc).isoformat(), existing_row["id"]),
                        )
                        missing += 1

            # Recovery for withdrawn that reappears (should be in added_keys but our added logic already handled, but for UNCHANGED case, check common withdrawn)
            for key in common_keys:
                existing_row = existing[key]
                if existing_row.get("is_withdrawn"):
                    with self.database.session() as conn:
                        conn.execute(
                            "UPDATE official_calendar_events SET is_withdrawn = 0, withdrawn_at = NULL, missing_since = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (existing_row["id"],),
                        )

            if not is_unchanged:
                status = "UPDATED" if (added > 0 or changed > 0) else "UNCHANGED"
                now = datetime.now(timezone.utc).isoformat()
                with self.database.session() as conn:
                    conn.execute(
                        """
                        INSERT INTO official_source_state
                            (source_code, source_kind, last_seed_version, last_content_hash, last_successful_sync_at, last_checked_at, last_attempt_at, last_success_at, last_changed_at, status, details_json)
                        VALUES (?, 'GIB', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source_code) DO UPDATE SET
                            last_content_hash = excluded.last_content_hash,
                            last_successful_sync_at = excluded.last_successful_sync_at,
                            last_checked_at = excluded.last_checked_at,
                            last_attempt_at = excluded.last_attempt_at,
                            last_success_at = excluded.last_success_at,
                            last_changed_at = excluded.last_changed_at,
                            status = excluded.status,
                            details_json = excluded.details_json
                        """,
                        (
                            source_code,
                            PARSER_VERSION,
                            normalized_hash,
                            now,
                            now,
                            now,
                            now,
                            now if status == "UPDATED" else None,
                            status,
                            json.dumps(
                                {"items_seen": items_seen, "added": added, "changed": changed, "missing": missing, "unchanged": unchanged},
                                ensure_ascii=False,
                            ),
                        ),
                    )

        except Exception as e:
            error_msg = str(e)
            status = "FAILED"
            http_status = None
            try:
                with self.database.session() as conn:
                    now = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        """
                        INSERT INTO official_source_state
                            (source_code, source_kind, status, last_attempt_at, last_error, details_json)
                        VALUES (?, 'GIB', ?, ?, ?, ?)
                        ON CONFLICT(source_code) DO UPDATE SET
                            status = excluded.status,
                            last_attempt_at = excluded.last_attempt_at,
                            last_error = excluded.last_error,
                            details_json = excluded.details_json
                        """,
                        (
                            source_code,
                            status,
                            now,
                            error_msg,
                            json.dumps({"error": error_msg}, ensure_ascii=False),
                        ),
                    )
            except Exception:
                pass
            raise

        finally:
            finished_at = datetime.now(timezone.utc).isoformat()
            with self.database.session() as conn:
                conn.execute(
                    """
                    UPDATE official_sync_runs SET finished_at = ?, status = ?, http_status = ?, raw_hash = ?, normalized_hash = ?, items_seen = ?, items_added = ?, items_changed = ?, items_missing = ?, items_unchanged = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (
                        finished_at,
                        status,
                        http_status,
                        raw_hash,
                        normalized_hash,
                        items_seen,
                        added,
                        changed,
                        missing,
                        unchanged,
                        error_msg,
                        run_id,
                    ),
                )

        return {
            "source_code": source_code,
            "status": status,
            "items_seen": items_seen,
            "added": added,
            "changed": changed,
            "missing": missing,
            "unchanged": unchanged,
            "raw_hash": raw_hash,
            "normalized_hash": normalized_hash,
        }
