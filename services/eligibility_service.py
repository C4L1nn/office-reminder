from __future__ import annotations

import json
from typing import Any

from database.connection import Database


class EligibilityService:
    """Generic eligibility engine for company -> official event projection.

    - Each official event may have `eligibility_tags` (JSON array) that describes which
      profile variant it belongs to (e.g., KDV: ["KDV_STANDARD_MONTHLY"]).
    - Each company_obligations row may have `settings_json` that describes which
      variants the company is eligible for (e.g., {"kdv_variants": ["KDV_STANDARD_MONTHLY", "KDV_TEVKIFAT"]}).
    - If an event has no eligibility_tags (NULL/empty), it is visible to any company with that obligation (no extra profile needed).
    - If an event has tags but the company's profile is missing/empty, the event is considered `needs_profile` (fail-safe, not shown as normal).
    - Future obligations can reuse the same generic logic by adding tags and profile keys; no obligation-specific if chains in UI/service.

    For now, only GIB_KDV requires profile (3 variants). Other obligations fall back to simple boolean.
    """

    # Obligations that require profile beyond boolean
    PROFILE_REQUIRED = {"GIB_KDV", "SGK_4A_PREMIUM"}

    def __init__(self, database: Database) -> None:
        self.database = database

    def load_settings(self, pairs: set) -> dict:
        """Settings for many (company, obligation) pairs in one query.

        The eligibility check runs once per official row, and asking per row
        opened a connection per row — measured at 168 connections for a single
        dashboard refresh with twenty companies.
        """
        if not pairs:
            return {}
        companies = sorted({company_id for company_id, _code in pairs})
        codes = sorted({code for _company_id, code in pairs})
        placeholders_c = ",".join("?" * len(companies))
        placeholders_o = ",".join("?" * len(codes))
        found: dict = {}
        with self.database.session() as connection:
            rows = connection.execute(
                f"""
                SELECT co.company_id, ot.code, co.settings_json
                FROM company_obligations co
                JOIN obligation_types ot ON ot.id = co.obligation_type_id
                WHERE co.is_active = 1
                  AND co.company_id IN ({placeholders_c})
                  AND ot.code IN ({placeholders_o})
                """,
                (*companies, *codes),
            ).fetchall()
        for row in rows:
            settings = None
            if row["settings_json"]:
                try:
                    settings = json.loads(row["settings_json"])
                except Exception:
                    settings = None
            found[(row["company_id"], row["code"])] = settings
        return found

    def get_company_obligation_settings(self, company_id: int, obligation_code: str) -> dict[str, Any] | None:
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT co.settings_json, ot.code
                FROM company_obligations co
                JOIN obligation_types ot ON ot.id = co.obligation_type_id
                WHERE co.company_id = ? AND ot.code = ? AND co.is_active = 1
                """,
                (company_id, obligation_code),
            ).fetchone()
            if row is None or not row["settings_json"]:
                return None
            try:
                return json.loads(row["settings_json"])
            except Exception:
                return None

    def is_event_eligible(
        self,
        company_id: int,
        obligation_code: str,
        event_eligibility_tags: list[str] | None,
        event_subject_kind: str | None = None,
        settings_map: dict | None = None,
    ) -> tuple[bool, str]:
        """Check if event is eligible for company.

        Returns (is_eligible, reason) where reason is 'eligible', 'needs_profile', 'ineligible' etc.
        """
        # No tags -> always eligible if obligation is active
        if not event_eligibility_tags:
            return True, "eligible_no_tags"

        # Only KDV currently requires profile
        if obligation_code not in self.PROFILE_REQUIRED:
            # For other obligations, even if they have tags (like e-Defter subtypes already filtered by code),
            # we don't require extra profile beyond the code itself.
            # The 4 e-Defter codes are separate, so their events' tags are informational only.
            return True, "eligible_no_profile_required"

        # For profile-required obligations, check company's settings
        # `settings_map` lets a caller that already loaded every pair in one
        # query skip the per-row lookup; the behaviour is identical either way.
        if settings_map is not None and (company_id, obligation_code) in settings_map:
            settings = settings_map[(company_id, obligation_code)]
        else:
            settings = self.get_company_obligation_settings(company_id, obligation_code)
        if settings is None:
            return False, "needs_profile"

        allowed: list[str] | None = None
        if isinstance(settings, dict):
            if obligation_code == "GIB_KDV":
                # KDV variants
                if "kdv_variants" in settings:
                    allowed = settings["kdv_variants"]
                elif "allowed_eligibility_tags" in settings:
                    allowed = settings["allowed_eligibility_tags"]
                elif "variants" in settings:
                    allowed = settings["variants"]
                elif "allowed_tags" in settings:
                    allowed = settings["allowed_tags"]
                # Also handle legacy single string
                elif "kdv_standard_monthly" in settings or "kdv_tevkifat" in settings:
                    # fallback
                    allowed = []
            elif obligation_code == "SGK_4A_PREMIUM":
                # SGK wage period
                if "wage_period" in settings:
                    wp = settings["wage_period"]
                    # Map wage_period to eligibility tag
                    mapping = {
                        "MONTHLY_1_END": "SGK_4A_1END",
                        "MONTHLY_15_14": "SGK_4A_15_14",
                    }
                    tag = mapping.get(wp)
                    if tag:
                        allowed = [tag]
                    # Also handle wage_periods plural
                    elif isinstance(wp, list):
                        allowed = [mapping.get(x, x) for x in wp]
                if allowed is None and "wage_periods" in settings:
                    wps = settings["wage_periods"]
                    mapping = {
                        "MONTHLY_1_END": "SGK_4A_1END",
                        "MONTHLY_15_14": "SGK_4A_15_14",
                    }
                    allowed = [mapping.get(x, x) for x in wps if isinstance(wps, list)]
                if allowed is None and "allowed_eligibility_tags" in settings:
                    allowed = settings["allowed_eligibility_tags"]
                if allowed is None and "variants" in settings:
                    allowed = settings["variants"]
            else:
                # Generic for future
                if "allowed_eligibility_tags" in settings:
                    allowed = settings["allowed_eligibility_tags"]
                elif "variants" in settings:
                    allowed = settings["variants"]

        if not allowed:
            return False, "needs_profile"

        # Event is eligible if all its required tags are subset of allowed
        required = set(event_eligibility_tags)
        allowed_set = set(allowed)
        if required.issubset(allowed_set):
            return True, "eligible"
        if any(tag in allowed_set for tag in required):
            return True, "eligible_partial"
        return False, "ineligible"

    def get_needs_profile_events(self, company_id: int, obligation_code: str) -> list[dict[str, Any]]:
        """Return events for this company+obligation that are in needs_profile state (for reporting)."""
        # This would be used to report unresolved events
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT oce.*, ot.code as obligation_code
                FROM official_calendar_events oce
                JOIN obligation_types ot ON ot.id = oce.obligation_type_id
                WHERE ot.code = ? AND oce.is_active = 1
                ORDER BY oce.effective_due_date
                """,
                (obligation_code,),
            ).fetchall()
            needs = []
            for r in rows:
                tags = None
                if r["eligibility_tags"]:
                    try:
                        tags = json.loads(r["eligibility_tags"])
                    except Exception:
                        tags = None
                eligible, reason = self.is_event_eligible(company_id, obligation_code, tags, r["subject_kind"])
                if reason == "needs_profile":
                    needs.append(dict(r))
            return needs
