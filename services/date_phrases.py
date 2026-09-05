"""Turning what an accountant types into a date.

Picking "3 Ekim" out of a calendar popup takes four clicks; typing "3 ekim"
takes four keystrokes, and the office types dates all day. This parses the
phrases people actually use and refuses everything else — a guess that lands
on the wrong month is worse than no answer at all.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta

from services.formatting import TR_MONTHS, lower_tr

#: Monday-first, matching `date.weekday()`.
WEEKDAYS = (
    ("pazartesi",),
    ("salı", "sali"),
    ("çarşamba", "carsamba"),
    ("perşembe", "persembe"),
    ("cuma",),
    ("cumartesi",),
    ("pazar",),
)

#: Small numbers are as often written out as typed.
WORD_NUMBERS = {
    "bir": 1, "iki": 2, "üç": 3, "uc": 3, "dört": 4, "dort": 4, "beş": 5,
    "bes": 5, "altı": 6, "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9,
    "on": 10, "onbeş": 15, "on beş": 15, "yirmi": 20, "otuz": 30,
}

_MONTH_LOOKUP = {lower_tr(name): index + 1 for index, name in enumerate(TR_MONTHS)}
#: Month names typed without their Turkish letters.
_MONTH_LOOKUP.update({
    "subat": 2, "agustos": 8, "eylul": 9, "kasim": 11, "aralik": 12, "mayis": 5,
})


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _add_months(value: date, count: int) -> date:
    """Same day next month, clamped when the month is shorter."""
    index = value.year * 12 + (value.month - 1) + count
    year, month = index // 12, index % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _count(text: str) -> int | None:
    text = text.strip()
    if text.isdigit():
        return int(text)
    return WORD_NUMBERS.get(text)


def _weekday_index(word: str) -> int | None:
    for index, names in enumerate(WEEKDAYS):
        if word in names:
            return index
    return None


def parse_date_phrase(text: str, today: date | None = None) -> date | None:
    """The date a phrase means, or None when it means nothing certain.

    Returning None is a real answer: the caller shows that nothing was
    understood rather than silently filling in a date the user did not ask for.
    """
    if not text:
        return None
    today = today or date.today()
    phrase = lower_tr(" ".join(text.split()))
    if not phrase:
        return None

    # -------------------------------------------------------------- landmarks
    fixed = {
        "bugün": 0, "bugun": 0,
        "yarın": 1, "yarin": 1,
        "öbür gün": 2, "obur gun": 2, "ertesi gün": 2, "ertesi gun": 2,
        "dün": -1, "dun": -1,
    }
    if phrase in fixed:
        return today + timedelta(days=fixed[phrase])

    if phrase in ("ay sonu", "ayın sonu", "ayin sonu", "ayın son günü", "ayin son gunu"):
        return _month_end(today.year, today.month)
    if phrase in ("gelecek ay sonu", "önümüzdeki ay sonu", "onumuzdeki ay sonu"):
        following = _add_months(today.replace(day=1), 1)
        return _month_end(following.year, following.month)
    if phrase in ("haftaya", "gelecek hafta", "önümüzdeki hafta", "onumuzdeki hafta"):
        return today + timedelta(days=7)
    if phrase in ("gelecek ay", "önümüzdeki ay", "onumuzdeki ay"):
        return _add_months(today, 1)
    if phrase in ("gelecek yıl", "gelecek yil", "önümüzdeki yıl", "onumuzdeki yil"):
        return _add_months(today, 12)

    # ------------------------------------------------------------- "N x sonra"
    match = re.fullmatch(r"(.+?)\s+(gün|gun|hafta|ay|yıl|yil)\s+(sonra|sonras[ıi])", phrase)
    if match:
        count = _count(match.group(1))
        if count is None:
            return None
        unit = match.group(2)
        if unit in ("gün", "gun"):
            return today + timedelta(days=count)
        if unit == "hafta":
            return today + timedelta(weeks=count)
        if unit == "ay":
            return _add_months(today, count)
        return _add_months(today, count * 12)

    # ------------------------------------------------------------- weekday
    words = phrase.split()
    if 1 <= len(words) <= 2:
        target = _weekday_index(words[-1])
        if target is not None:
            # A bare weekday means the coming one; today is never meant.
            ahead = (target - today.weekday()) % 7 or 7
            if len(words) == 2:
                qualifier = words[0]
                if qualifier in ("gelecek", "önümüzdeki", "onumuzdeki", "sonraki", "haftaya"):
                    # "gelecek salı" is next week's Tuesday, not this week's.
                    ahead += 7
                elif qualifier not in ("bu", "gelen"):
                    return None
            return today + timedelta(days=ahead)

    # --------------------------------------------------------- "15 ekim [2027]"
    match = re.fullmatch(r"(\d{1,2})\s+([a-zçğıöşü]+)(?:\s+(\d{4}))?", phrase)
    if match:
        month = _MONTH_LOOKUP.get(match.group(2))
        if month is None:
            return None
        day = int(match.group(1))
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            found = date(year, month, day)
        except ValueError:
            return None
        # A bare "15 ekim" that has already passed means next year.
        if match.group(3) is None and found < today:
            try:
                found = date(year + 1, month, day)
            except ValueError:
                return None
        return found

    # ------------------------------------------------- "15.10", "15.10.2026"
    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?", phrase)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        raw_year = match.group(3)
        if raw_year is None:
            year = today.year
        else:
            year = int(raw_year)
            if year < 100:
                year += 2000
        try:
            found = date(year, month, day)
        except ValueError:
            return None
        if raw_year is None and found < today:
            try:
                found = date(year + 1, month, day)
            except ValueError:
                return None
        return found

    return None


#: Longest phrase worth trying, in words ("3 gün sonra", "15 ekim 2027").
_WINDOW = 3


def extract_date(text: str, today: date | None = None) -> tuple[date, str] | None:
    """Find a date inside a longer sentence, and say which words carried it.

    Used where the text was written for a human rather than for a form — a
    sticky note, a line pasted from an e-mail. Windows are tried longest-first
    so "15 ekim 2027" wins over the "15 ekim" inside it, and scanning stops at
    the first hit rather than guessing between several.
    """
    if not text:
        return None
    today = today or date.today()
    words = " ".join(text.split()).split(" ")
    for start in range(len(words)):
        for size in range(min(_WINDOW, len(words) - start), 0, -1):
            phrase = " ".join(words[start : start + size]).strip(".,;:!?()[]")
            if not phrase:
                continue
            found = parse_date_phrase(phrase, today)
            if found is not None:
                return found, phrase
    return None


def describe(value: date) -> str:
    """How the parsed date is echoed back, so a wrong guess is visible."""
    from services.formatting import TR_WEEKDAYS_SHORT

    return (
        f"{value.day} {TR_MONTHS[value.month - 1]} {value.year}"
        f" {TR_WEEKDAYS_SHORT[value.weekday()]}"
    )


__all__ = ["WORD_NUMBERS", "describe", "extract_date", "parse_date_phrase"]
