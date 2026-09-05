from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from database.connection import Database
from database.repositories.companies import CompanyRecord, CompanyRepository
from database.repositories.obligations import (
    CompanyObligationRecord,
    CompanyObligationRepository,
    ObligationTypeRecord,
    ObligationTypeRepository,
)
from database.repositories.vehicles import VehicleRecord, VehicleRepository

KDV_VARIANTS = ("KDV_STANDARD_MONTHLY", "KDV_STANDARD_QUARTERLY", "KDV_TEVKIFAT")
SGK_WAGE_PERIODS = ("MONTHLY_1_END", "MONTHLY_15_14")


@dataclass(slots=True, frozen=True)
class ObligationProfile:
    """Everything needed to render or persist a company's obligation profile."""

    obligation_type_ids: set[int] = field(default_factory=set)
    kdv_variants: list[str] = field(default_factory=list)
    sgk_wage_period: str | None = None


class CompanyService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repo = CompanyRepository(database)
        self.obligation_types = ObligationTypeRepository(database)
        self.company_obligations = CompanyObligationRepository(database)
        self.vehicles = VehicleRepository(database)

    # ------------------------------------------------------------------ companies
    def list_active(self) -> list[CompanyRecord]:
        return self.repo.list_active()

    def list_all(self) -> list[CompanyRecord]:
        return self.repo.list_all()

    def get_by_id(self, company_id: int) -> CompanyRecord | None:
        return self.repo.get_by_id(company_id)

    def create(self, name: str, tax_number: str | None = None, notes: str | None = None) -> int:
        clean_tax = tax_number.strip() if tax_number and tax_number.strip() else None
        if clean_tax and not clean_tax.isdigit():
            # allow alphanumeric tax? For Turkey tax numbers are digits; but be permissive
            pass
        try:
            return self.repo.create(name, clean_tax, notes)
        except Exception as e:
            if "UNIQUE" in str(e) or "unique" in str(e).lower():
                raise ValueError(f"Vergi numarası zaten kayıtlı: {clean_tax}") from e
            raise

    def update(self, company_id: int, **kwargs) -> bool:
        try:
            return self.repo.update(company_id, **kwargs)
        except Exception as e:
            if "UNIQUE" in str(e):
                raise ValueError("Vergi numarası zaten kayıtlı.") from e
            raise

    def set_active(self, company_id: int, is_active: bool) -> bool:
        return self.repo.set_active(company_id, is_active)

    def delete(self, company_id: int) -> bool:
        # hard delete not recommended; we soft via set_active but allow hard if no dependencies?
        # Use set_active false instead; but provide hard delete for completeness
        with self.database.session() as connection:
            cursor = connection.execute("DELETE FROM companies WHERE id = ?", (company_id,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------ obligations
    def list_obligation_types(self, only_active: bool = True) -> list[ObligationTypeRecord]:
        return self.obligation_types.list_all(only_active=only_active)

    def grouped_obligation_types(self) -> dict[str, list[ObligationTypeRecord]]:
        return self.obligation_types.grouped_by_category(only_active=True)

    def get_company_obligations(self, company_id: int) -> list[CompanyObligationRecord]:
        return self.company_obligations.list_for_company(company_id)

    def get_assigned_obligation_ids(self, company_id: int) -> set[int]:
        return self.company_obligations.get_assigned_ids(company_id)

    def set_company_obligations(
        self,
        company_id: int,
        obligation_type_ids: list[int],
        *,
        enabled_from: date | None = None,
    ) -> None:
        self.save_obligation_profile(company_id, obligation_type_ids, enabled_from=enabled_from)

    # ------------------------------------------------------------------ obligation profile (atomic)
    def save_obligation_profile(
        self,
        company_id: int,
        obligation_type_ids: list[int],
        *,
        kdv_variants: list[str] | None = None,
        sgk_wage_period: str | None = None,
        enabled_from: date | None = None,
    ) -> None:
        """Persist the company's obligation set and its profile in ONE transaction.

        The obligation rows and the profile that qualifies them (KDV variants,
        SGK wage period) are written together, so a first-time selection can
        never lose its profile because the row did not exist yet.
        """
        if kdv_variants is not None:
            for variant in kdv_variants:
                if variant not in KDV_VARIANTS:
                    raise ValueError(f"Geçersiz KDV varyantı: {variant}")
        if sgk_wage_period is not None and sgk_wage_period not in SGK_WAGE_PERIODS:
            raise ValueError(f"Geçersiz ücret dönemi: {sgk_wage_period}")

        by_code = {ot.code: ot.id for ot in self.obligation_types.list_all()}
        settings: dict[int, str | None] = {}
        if kdv_variants is not None and "GIB_KDV" in by_code:
            settings[by_code["GIB_KDV"]] = json.dumps({"kdv_variants": kdv_variants}, ensure_ascii=False)
        if sgk_wage_period is not None and "SGK_4A_PREMIUM" in by_code:
            settings[by_code["SGK_4A_PREMIUM"]] = json.dumps(
                {"wage_period": sgk_wage_period}, ensure_ascii=False
            )

        # Default to the start of the calendar year the obligation is added in, so a
        # company onboarded mid-year still shows that year's full official calendar.
        # Overdue reporting uses company_obligations.created_at instead, so nothing
        # from before onboarding is ever reported as late.
        stamp = (enabled_from or date(date.today().year, 1, 1)).isoformat()
        self.company_obligations.replace_profile(
            company_id,
            [int(x) for x in obligation_type_ids],
            settings_by_type_id=settings,
            enabled_from=stamp,
        )

    def get_obligation_profile(self, company_id: int) -> ObligationProfile:
        """Read back everything the obligation dialog needs, in one call."""
        assigned = self.company_obligations.get_assigned_ids(company_id)
        return ObligationProfile(
            obligation_type_ids=assigned,
            kdv_variants=self.get_kdv_profile(company_id) or [],
            sgk_wage_period=self.get_sgk_wage_period(company_id),
        )

    def profile_gaps(self, company_id: int) -> list[str]:
        """Obligation codes the company selected but did not finish configuring."""
        gaps: list[str] = []
        codes = {r.code for r in self.company_obligations.list_active_for_company(company_id)}
        if "GIB_KDV" in codes and not self.get_kdv_profile(company_id):
            gaps.append("GIB_KDV")
        if "SGK_4A_PREMIUM" in codes and not self.get_sgk_wage_period(company_id):
            gaps.append("SGK_4A_PREMIUM")
        return gaps

    def get_kdv_profile(self, company_id: int) -> list[str] | None:
        raw = self.company_obligations.get_settings_json(company_id, "GIB_KDV")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        variants = data.get("kdv_variants") or data.get("allowed_eligibility_tags") or data.get("variants")
        return variants or None

    def set_kdv_profile(self, company_id: int, variants: list[str]) -> bool:
        """Update only the KDV profile of a company that already has GIB_KDV."""
        for variant in variants:
            if variant not in KDV_VARIANTS:
                raise ValueError(f"Geçersiz KDV variant: {variant}")
        assigned = self.company_obligations.get_assigned_ids(company_id)
        kdv = self.obligation_types.get_by_code("GIB_KDV")
        if kdv is None or kdv.id not in assigned:
            return False
        self.company_obligations.replace_profile(
            company_id,
            sorted(assigned),
            settings_by_type_id={kdv.id: json.dumps({"kdv_variants": variants}, ensure_ascii=False)},
        )
        return True

    def get_sgk_wage_period(self, company_id: int) -> str | None:
        raw = self.company_obligations.get_settings_json(company_id, "SGK_4A_PREMIUM")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        wage = data.get("wage_period")
        if wage:
            return wage
        periods = data.get("wage_periods") or []
        return periods[0] if periods else None

    def set_sgk_wage_period(self, company_id: int, wage_period: str) -> bool:
        if wage_period not in SGK_WAGE_PERIODS:
            raise ValueError(f"Geçersiz wage_period: {wage_period}")
        assigned = self.company_obligations.get_assigned_ids(company_id)
        sgk = self.obligation_types.get_by_code("SGK_4A_PREMIUM")
        if sgk is None or sgk.id not in assigned:
            return False
        self.company_obligations.replace_profile(
            company_id,
            sorted(assigned),
            settings_by_type_id={sgk.id: json.dumps({"wage_period": wage_period}, ensure_ascii=False)},
        )
        return True

    def upcoming_for_company(self, company_id: int, limit: int = 6, horizon_days: int = 60) -> list:
        """The company's next obligations, official and manual together."""
        from services.reminder_service import ReminderService

        items = ReminderService(self.database).list_due(
            horizon_days=horizon_days, company_id=company_id
        )
        return items[:limit]

    def list_summaries(self) -> dict[int, dict]:
        """Counts for every company at once, keyed by company id.

        The list on the Şirketler screen shows a count line per row; asking
        per row meant four queries times however many clients the office has,
        and each of those opens its own connection.
        """
        summaries: dict[int, dict] = {}
        with self.database.session() as connection:
            for table, key, clause in (
                ("company_obligations", "obligations", ""),
                ("vehicles", "vehicles", " AND is_active = 1"),
                ("manual_reminders", "manual_open", " AND status = 'OPEN'"),
                ("v_active_official_company_events", "official_active", ""),
            ):
                rows = connection.execute(
                    f"SELECT company_id, COUNT(*) AS c FROM {table}"
                    f" WHERE company_id IS NOT NULL{clause} GROUP BY company_id"
                ).fetchall()
                for row in rows:
                    summaries.setdefault(int(row["company_id"]), {})[key] = int(row["c"])
        for values in summaries.values():
            for key in ("obligations", "vehicles", "manual_open", "official_active"):
                values.setdefault(key, 0)
        return summaries

    def get_company_summary(self, company_id: int) -> dict:
        """Return counts for UI: obligations, vehicles, manual reminders."""
        obligations = self.company_obligations.count_for_company(company_id)
        vehicles = len(self.vehicles.list_all(company_id=company_id, only_active=True))
        with self.database.session() as connection:
            manual_open = connection.execute(
                "SELECT COUNT(*) as c FROM manual_reminders WHERE company_id = ? AND status='OPEN'", (company_id,)
            ).fetchone()["c"]
            official_active = connection.execute(
                "SELECT COUNT(*) as c FROM v_active_official_company_events WHERE company_id = ?", (company_id,)
            ).fetchone()["c"]
        return {
            "obligations": obligations,
            "vehicles": vehicles,
            "manual_open": int(manual_open),
            "official_active": int(official_active),
        }

    # ------------------------------------------------------------------ vehicles
    def list_vehicles(self, company_id: int | None = None, only_active: bool = False) -> list[VehicleRecord]:
        return self.vehicles.list_all(company_id=company_id, only_active=only_active)

    def create_vehicle(self, **kwargs) -> int:
        return self.vehicles.create(**kwargs)

    def update_vehicle(self, vehicle_id: int, **kwargs) -> bool:
        return self.vehicles.update(vehicle_id, **kwargs)

    def set_vehicle_active(self, vehicle_id: int, is_active: bool) -> bool:
        return self.vehicles.set_active(vehicle_id, is_active)

    def get_vehicle(self, vehicle_id: int) -> VehicleRecord | None:
        return self.vehicles.get_by_id(vehicle_id)

    def delete_vehicle(self, vehicle_id: int) -> bool:
        return self.vehicles.delete(vehicle_id)
