from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.holiday_service import HolidayService

RULE_CODE = "SGK_4A_STANDARD"
RULE_VERSION = "1.0.0-rule"


class SgkRuleEngine:
    """SGK 4/a prim standart vadelerini üretmek için kural motoru (year-agnostic).

    Mevzuat: 5510 sayılı Kanun — 4/a primleri takip eden ayın sonuna kadar ödenir.
    - Normal vade: ilgili ayın son günü (following_month_end)
    - Effective vade: hafta sonu veya Türkiye resmi tatili ise bir sonraki iş günü
    - Wage period:
        * MONTHLY_1_END:  ayın 1'i–son günü ücret alanlar (varsayılan)
        * MONTHLY_15_14:  ayın 15'i–takip eden ayın 14'ü ücret alanlar
      Her iki period için de vade takip eden ayın sonudur (period bitiş + ~14-16 gün),
      ancak period etiketleri farklıdır ve şirket profiline göre filtrelenir.
    - Özel süre uzatımları bu motorun çıktısını overwrite etmez; official_calendar_revisions ile override edilir.
    - MUHSGK (GIB_MUHSGK) ile çakışmaz: SGK engine MUHSGK üretmez.
    - Year-agnostic: Kural yıl bağımsız, holiday verisi eksikse fail-closed.
    """

    RULE_CODE = RULE_CODE
    RULE_VERSION = RULE_VERSION

    @staticmethod
    def following_month_end(period_year: int, period_month: int) -> date:
        if period_month == 12:
            year, month = period_year + 1, 1
        else:
            year, month = period_year, period_month + 1
        last_day = monthrange(year, month)[1]
        return date(year, month, last_day)

    @staticmethod
    def move_weekend_to_next_weekday(value: date) -> date:
        # Legacy weekend-only guard (tatil hariç)
        while value.weekday() >= 5:
            value += timedelta(days=1)
        return value

    @staticmethod
    def adjust_for_holidays(value: date, holiday_service: HolidayService | None = None) -> date:
        """Hafta sonu + resmi tatil için bir sonraki iş gününe ötele."""
        if holiday_service is None:
            # Fallback to weekend only
            return SgkRuleEngine.move_weekend_to_next_weekday(value)
        return holiday_service.adjust_to_next_working_day(value)

    @classmethod
    def generate_for_period(
        cls,
        period_year: int,
        period_month: int,
        holiday_service: HolidayService | None = None,
        wage_period: str = "MONTHLY_1_END",
    ) -> dict | None:
        """Generate single period. Returns None if holiday data missing (fail-closed)."""
        # Validate wage_period
        if wage_period not in ("MONTHLY_1_END", "MONTHLY_15_14"):
            raise ValueError(f"Unknown wage_period: {wage_period}")

        # Correct due calculation per SGK rule (resmî):
        # - MONTHLY_1_END: period month's following month end
        # - MONTHLY_15_14: period END (14th next month) -> following calendar month 14th
        #   e.g., 2026-01 with 15_14 => END 2026-02-14 => due 2026-03-14
        if wage_period == "MONTHLY_1_END":
            normal = cls.following_month_end(period_year, period_month)
        else:  # MONTHLY_15_14
            # Compute period END: next month's 14th
            if period_month == 12:
                end_year, end_month = period_year + 1, 1
            else:
                end_year, end_month = period_year, period_month + 1
            # Due is END's next month 14th
            if end_month == 12:
                due_year, due_month = end_year + 1, 1
            else:
                due_year, due_month = end_year, end_month + 1
            normal = date(due_year, due_month, 14)

        # Fail-closed: check if holiday data exists for normal's year and effective's year
        if holiday_service is not None:
            # Check if we have any holiday data for the due year (normal and potential effective year)
            # If no data for that year, skip generation
            years_to_check = {normal.year}
            # Also check next year for potential effective after adjustment (e.g., Dec due Jan next year)
            # We need to check if holiday data exists for those years
            for y in list(years_to_check):
                if not holiday_service.list_holidays(year=y):
                    # No holiday data for this year -> fail-closed, skip this event
                    return None
            # Also check effective year after adjustment might be next year
            effective_year = normal.year
            # Quick check: if normal is Dec 31 and it's weekend, effective could be next year
            # So we should also check next year if normal month is Dec
            if normal.month == 1 and period_month == 12:
                # Due is Jan next year, check next year holidays
                if not holiday_service.list_holidays(year=normal.year):
                    return None

        effective = cls.adjust_for_holidays(normal, holiday_service)

        # For 15_14, adjust period key/label
        if wage_period == "MONTHLY_1_END":
            period_key = f"{period_year:04d}-{period_month:02d}"
            period_label = f"{period_year} / {period_month:02d} (1–Ay Sonu)"
            source_event_key = f"SGK_4A_{period_year}_{period_month:02d}_1END"
            title = f"SGK 4/a Prim Ödemesi — {period_label}"
            eligibility = ["SGK_4A_1END"]
        else:  # MONTHLY_15_14
            # Period is 15th to 14th next month
            # e.g., Jan 2026 15_14 => 2026-01-15 to 2026-02-14
            if period_month == 12:
                end_year, end_month = period_year + 1, 1
            else:
                end_year, end_month = period_year, period_month + 1
            period_key = f"{period_year:04d}-{period_month:02d}-15_{end_year:04d}-{end_month:02d}-14"
            period_label = f"{period_year}/{period_month:02d} 15 – {end_year}/{end_month:02d} 14"
            source_event_key = f"SGK_4A_{period_year}_{period_month:02d}_15_14"
            title = f"SGK 4/a Prim Ödemesi (15–14) — {period_label}"
            eligibility = ["SGK_4A_15_14"]

        # For year-agnostic, also check effective year holidays after adjustment
        # If effective year differs from normal year and that year's holidays missing, fail
        if holiday_service is not None and effective.year != normal.year:
            if not holiday_service.list_holidays(year=effective.year):
                return None

        return {
            "obligation_code": "SGK_4A_PREMIUM",
            "source_kind": "SGK",
            "source_event_key": source_event_key,
            "title": title,
            "period_key": period_key,
            "period_label": period_label,
            "year": period_year,
            "normal_due_date": normal.isoformat(),
            "effective_due_date": effective.isoformat(),
            "due_time": None,
            "source_url": "https://www.sgk.gov.tr",
            "period_year": period_year,
            "period_month": period_month,
            "wage_period": wage_period,
            "rule_code": cls.RULE_CODE,
            "rule_version": cls.RULE_VERSION,
            "provenance": {
                "generator": "SgkRuleEngine",
                "rule_code": cls.RULE_CODE,
                "rule_version": cls.RULE_VERSION,
                "wage_period": wage_period,
                "period": period_key,
                "normal_due_date": normal.isoformat(),
                "effective_due_date": effective.isoformat(),
                "adjustment": "weekend+holiday->next-working-day" if normal != effective else "none",
            },
            "subject_kind": "Ödeme",
            "eligibility_tags": eligibility,
            "taxpayer_kind": None,
            "filing_kind": wage_period,
            "upload_preference": None,
        }

    @classmethod
    def generate_for_year(
        cls,
        year: int,
        holiday_service: HolidayService | None = None,
        wage_periods: list[str] | None = None,
    ) -> list[dict]:
        if wage_periods is None:
            wage_periods = ["MONTHLY_1_END"]
        events: list[dict] = []
        for wage in wage_periods:
            for month in range(1, 13):
                ev = cls.generate_for_period(year, month, holiday_service, wage_period=wage)
                if ev is None:
                    continue
                events.append(ev)
        events.sort(key=lambda e: e["effective_due_date"])
        return events

    @classmethod
    def is_muhsgk_guard(cls, obligation_code: str) -> bool:
        """MUHSGK guard: SGK engine GIB_MUHSGK üretmemeli."""
        return obligation_code == "GIB_MUHSGK"
