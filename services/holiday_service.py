from __future__ import annotations

from datetime import date, timedelta

from database.connection import Database


class HolidayService:
    """Türkiye resmi tatil takvimi servisi — DB'deki holidays_tr tablosundan okur.

    Ayrı katmanda tutulur, SGK kural motoru içine hardcode edilmez (Faz 4 gereği).
    Yarım gün tatiller (is_full_day=0) SGK vade ertelemesi için tam gün sayılmaz;
    ancak ihtiyaç olursa ayrıca ele alınabilir. Şu an sadece tam günler erteler.
    """

    def __init__(self, database: Database) -> None:
        self._holiday_cache: dict[int, set] = {}
        self.database = database

    def is_holiday(self, d: date) -> bool:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT 1 FROM holidays_tr WHERE holiday_date = ? AND is_full_day = 1",
                (d.isoformat(),),
            ).fetchone()
            return row is not None

    def is_non_working_day(self, d: date) -> bool:
        # Weekend + holiday
        if d.weekday() >= 5:
            return True
        return self.is_holiday(d)

    def holiday_dates(self, year: int) -> set:
        """Every holiday in a year, read once and kept.

        The table is a few dozen fixed rows per year; querying it per day
        turned a 300-day span into 300 round trips (measured at ~1 second).
        """
        cached = self._holiday_cache.get(year)
        if cached is None:
            # Only full-day holidays stop work; a half day is still a working
            # day, which is what `is_holiday` has always meant.
            cached = {
                date.fromisoformat(row["holiday_date"])
                for row in self.list_holidays(year=year)
                if row["is_full_day"]
            }
            self._holiday_cache[year] = cached
        return cached

    def working_days_between(self, start: date, end: date) -> int:
        """Working days from `start` (exclusive) to `end` (inclusive).

        What an accountant actually has to work with: a deadline 24 calendar
        days away can be 15 working days away once a bayram falls in between,
        and that is the number that decides whether the work fits.
        """
        if end <= start:
            return 0
        years = {year: self.holiday_dates(year) for year in range(start.year, end.year + 1)}
        count = 0
        day = start
        while day < end:
            day = day + timedelta(days=1)
            if day.weekday() >= 5:
                continue
            if day in years.get(day.year, ()):
                continue
            count += 1
        return count

    def adjust_to_next_working_day(self, d: date) -> date:
        """Hafta sonu veya tam gün resmi tatili ise bir sonraki iş gününe ötele."""
        from datetime import timedelta

        cur = d
        # Guard against infinite loop (e.g., long holiday)
        for _ in range(10):
            if cur.weekday() >= 5:
                cur += timedelta(days=1)
                continue
            if self.is_holiday(cur):
                cur += timedelta(days=1)
                continue
            break
        return cur

    def list_holidays(self, year: int | None = None) -> list[dict]:
        with self.database.session() as connection:
            if year is not None:
                rows = connection.execute(
                    "SELECT holiday_date, name, kind, is_full_day FROM holidays_tr WHERE substr(holiday_date,1,4)=? ORDER BY holiday_date",
                    (str(year),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT holiday_date, name, kind, is_full_day FROM holidays_tr ORDER BY holiday_date"
                ).fetchall()
            return [dict(r) for r in rows]
