"""Turkish presentation helpers shared by the UI and the notification texts.

Kept in the service layer on purpose: a Windows toast and a table cell must
never disagree about how a date or a remaining-days label is worded.
"""

from __future__ import annotations

from datetime import date

TR_MONTHS = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)

TR_MONTHS_SHORT = ("Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara")

CATEGORY_LABELS: dict[str, str] = {
    "GENERAL": "Genel",
    "VEHICLE_INSPECTION": "Araç Muayenesi",
    "TRAFFIC_INSURANCE": "Trafik Sigortası",
    "KASKO": "Kasko",
    "RENT": "Kira",
    "CONTRACT": "Sözleşme",
    "LICENSE": "Ruhsat",
    "SUBSCRIPTION": "Abonelik",
    "SPECIAL_PAYMENT": "Özel Ödeme",
    "PERSONNEL_DOC": "Personel Belgesi",
    "CUSTOM_REMINDER": "Serbest Hatırlatma",
}

RECURRENCE_LABELS: dict[str, str] = {
    "NONE": "—",
    "MONTHLY": "Aylık",
    "QUARTERLY": "3 Aylık",
    "SEMIANNUAL": "6 Aylık",
    "YEARLY": "Yıllık",
    "CUSTOM": "Özel",
}

SOURCE_LABELS: dict[str, str] = {
    "GIB": "GİB",
    "SGK": "SGK",
    "MANUEL": "Manuel",
    "MANUAL": "Manuel",
}


def short_date(value: date) -> str:
    """08.09.2026 — dense, for table cells."""
    return value.strftime("%d.%m.%Y")


def long_date(value: date) -> str:
    """8 Eylül 2026 — for notifications and detail panes."""
    return f"{value.day} {TR_MONTHS[value.month - 1]} {value.year}"


def day_month(value: date) -> str:
    """8 Eylül — for compact before/after pairs."""
    return f"{value.day} {TR_MONTHS[value.month - 1]}"


def category_label(code: str | None) -> str:
    if not code:
        return "—"
    return CATEGORY_LABELS.get(code, code.replace("_", " ").title())


def recurrence_label(code: str | None) -> str:
    if not code:
        return "—"
    return RECURRENCE_LABELS.get(code, code.title())


def source_label(code: str | None) -> str:
    if not code:
        return "—"
    return SOURCE_LABELS.get(code, code)


def remaining_label(days: int) -> str:
    """Human wording for a signed day delta."""
    if days < 0:
        return f"{-days} gün gecikti"
    if days == 0:
        return "Bugün"
    if days == 1:
        return "Yarın"
    return f"{days} gün"


def due_sentence(days: int, due: date) -> str:
    """One sentence a person would actually say about a deadline."""
    if days < 0:
        return f"{-days} gün gecikti. Son tarih: {long_date(due)}"
    if days == 0:
        return f"Bugün son gün. Son tarih: {long_date(due)}"
    if days == 1:
        return f"Son güne 1 gün kaldı. Son tarih: {long_date(due)}"
    return f"Son tarihe {days} gün kaldı. Son tarih: {long_date(due)}"


def title_with_plate(title: str, plate: str | None) -> str:
    """Append the plate only when the title does not already carry it.

    Vehicle reminders are often named after the plate, and showing it twice
    ("Araç Muayenesi — 35 ABC 123 · 35 ABC 123") reads as a bug.
    """
    if not plate:
        return title
    normalized_title = " ".join(title.split()).casefold()
    normalized_plate = " ".join(plate.split()).casefold()
    if normalized_plate in normalized_title:
        return title
    return f"{title}  ·  {plate}"


TR_WEEKDAYS_SHORT = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")


def upper_tr(text: str) -> str:
    """Uppercase the Turkish way.

    Python maps "i" to "I", which is wrong here: "Ekim" becomes "EKIM" and
    "Geciken" becomes "GECIKEN". Turkish needs the dotted capital.
    """
    return text.replace("i", "İ").replace("ı", "I").upper()


def lower_tr(text: str) -> str:
    """Lowercase the Turkish way.

    Python maps "I" to "i" and "İ" to "i̇" (an i with a combining dot), so a
    typed "EKİM" would never match "ekim" without this.
    """
    return text.replace("I", "ı").replace("İ", "i").lower()



def weekday_short(value: date) -> str:
    return TR_WEEKDAYS_SHORT[value.weekday()]


def table_date(value: date) -> str:
    """08.09 Sal — the weekday matters: a deadline on a weekend changes plans."""
    return f"{value.strftime('%d.%m')} {weekday_short(value)}"


def is_weekend(value: date) -> bool:
    return value.weekday() >= 5


def date_group(value: date, today: date) -> str:
    """Bucket a due date into the heading a person would use for it."""
    delta = (value - today).days
    if delta < 0:
        return "GECİKEN"
    if delta == 0:
        return "BUGÜN"
    if delta == 1:
        return "YARIN"
    # Rest of the current week (Monday-based), then next week, then by month.
    days_to_sunday = 6 - today.weekday()
    if delta <= days_to_sunday:
        return "BU HAFTA"
    if delta <= days_to_sunday + 7:
        return "GELECEK HAFTA"
    if value.year == today.year and value.month == today.month:
        return "BU AY"
    return f"{upper_tr(TR_MONTHS[value.month - 1])} {value.year}"


#: Legal forms that repeat on every Turkish company name and carry no
#: distinguishing information in a narrow table column.
LEGAL_SUFFIXES = (
    "SANAYİ VE TİCARET LİMİTED ŞİRKETİ",
    "SANAYİ VE TİCARET ANONİM ŞİRKETİ",
    "SANAYİ VE TİCARET LTD. ŞTİ.",
    "SANAYİ VE TİCARET A.Ş.",
    "LİMİTED ŞİRKETİ",
    "ANONİM ŞİRKETİ",
    "SAN. VE TİC. LTD. ŞTİ.",
    "SAN. VE TİC. A.Ş.",
    "SAN. TİC. LTD. ŞTİ.",
    "SAN. TİC. A.Ş.",
    "LTD. ŞTİ.",
    "LTD.ŞTİ.",
    "A.Ş.",
    "LTD.",
)


def short_company_name(name: str | None) -> str:
    """Drop the repeated legal form so the distinctive part fits the column.

    "AYKUT MÜHENDİSLİK SANAYİ VE TİCARET LTD. ŞTİ." becomes
    "AYKUT MÜHENDİSLİK" — the full name stays in the tooltip.
    """
    if not name:
        return "Genel"
    trimmed = " ".join(name.split())
    upper = upper_tr(trimmed)
    for suffix in LEGAL_SUFFIXES:
        if upper.endswith(suffix):
            trimmed = trimmed[: len(trimmed) - len(suffix)].rstrip(" ,.-")
            break
    return trimmed or name
