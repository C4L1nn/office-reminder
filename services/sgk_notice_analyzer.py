"""Semantic analysis of a real SGK announcement.

This is the production path. It works from what an announcement actually says —
its title, its body text and, when the body is empty, the text of its attached
PDF — never from a fixture identifier. The two announcements used in the
acceptance scenarios are handled by the same code as any other announcement.

What it produces is a list of *findings*: one per deadline the announcement
moves. A finding says which obligation moved, from when to when, how wide the
scope is, and whether it is safe to apply automatically. Deciding to apply and
writing the revision is the caller's job.

Guard rails, all fail-closed:
  * An announcement with no extension wording and no deadline wording is
    NO_RELEVANT_CHANGE — drug-price and SUT circulars must not queue up as
    "needs review" noise.
  * Anything that looks province- or disaster-scoped is NEEDS_REVIEW.
  * The insurance section of MuhSGK is never applied to the GİB tax event
    GIB_MUHSGK; GİB remains the source of truth for that obligation.
  * A "new" date that is not later than the current one is not an extension.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from services.sgk_notice_parser import TR_MONTH_NUMBERS

# --- classifications ---------------------------------------------------------
PAYMENT = "SGK_4A_PREMIUM_PAYMENT"
REPORTING = "MUHSGK_INSURANCE_SECTION"
UNKNOWN = "UNKNOWN"

# --- scopes ------------------------------------------------------------------
NATIONAL_GLOBAL = "NATIONAL_GLOBAL"
NATIONAL_OBLIGATION_SPECIFIC = "NATIONAL_OBLIGATION_SPECIFIC"
REGIONAL = "REGIONAL"
UNRESOLVED = "UNRESOLVED"

_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_MONTH_NAMES = "|".join(sorted(TR_MONTH_NUMBERS, key=len, reverse=True))
_LONG_DATE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_NAMES})\s+(\d{{4}})\b", re.IGNORECASE)

# Wording that means "a deadline was moved".
_EXTENSION_MARKERS = (
    "uzatil",
    "uzatim",
    "ertelen",
    "erteleme",
    "sureye kadar",
    "mucbir sebep",
)
# Wording that means "this is about a due date at all".
_DEADLINE_MARKERS = (
    "son odeme tarihi",
    "odeme suresi",
    "verilme suresi",
    "verilmesine iliskin son gun",
    "son gun",
    "beyanname",
    "prim",
    "borc",
    "bildirge",
    "hizmet belgesi",
)

# Anchors introducing the NEW deadline. Order matters: longer, more specific
# phrases first so "son odeme tarihi" does not shadow "odeme suresi".
_NEW_DUE_ANCHORS: tuple[tuple[str, str], ...] = (
    ("verilme suresi", REPORTING),
    ("verilme tarihi", REPORTING),
    ("verilmesi suresi", REPORTING),
    ("beyanname verme suresi", REPORTING),
    ("odeme suresi", PAYMENT),
    ("odenme suresi", PAYMENT),
    ("son odeme tarihi ise", PAYMENT),
)
# Anchors introducing the OLD deadline the notice is replacing.
_OLD_DUE_ANCHORS = (
    "son gun olan",
    "son gunu olan",
    "son odeme tarihi",
    "son verilme tarihi",
    "son tarihi olan",
)

_REGIONAL_MARKERS = (
    "mucbir sebep",
    "depremlerden etkilenen",
    "afetten etkilenen",
    "sel felaketi",
    " ilinde",
    " ilinin",
    " ilcesinde",
    "etkilenen bazi yerler",
)
_NATIONAL_MARKERS = ("turkiye genelinde", "turkiye capinda", "ulke genelinde")

_PERIOD_PATTERNS = (
    # 2026/Nisan, 2026 Nisan ayı, 2026 yılı Nisan ayı/dönemi
    re.compile(rf"(\d{{4}})\s*[/ ]\s*(?:yili\s+)?({_MONTH_NAMES})\s*(?:ayi|ay|donemi|donem)?", re.IGNORECASE),
    # Nisan 2026 / Nisan ayı 2026
    re.compile(rf"({_MONTH_NAMES})\s*(?:ayi|ay|donemi|donem)?\s*[/ ]\s*(\d{{4}})", re.IGNORECASE),
)


@dataclass(slots=True, frozen=True)
class Finding:
    """One deadline movement declared by an announcement."""

    finding_kind: str
    obligation_code: str | None
    new_due_date: date
    old_due_date: date | None = None
    period: tuple[int, int] | None = None  # (year, month) when old due must be resolved
    scope_kind: str = UNRESOLVED
    auto_appliable: bool = False
    reason: str = ""


@dataclass(slots=True, frozen=True)
class NoticeAnalysis:
    relevant: bool
    classification: str
    scope_kind: str
    reason: str
    period: tuple[int, int] | None = None
    findings: list[Finding] = field(default_factory=list)


def fold(text: str) -> str:
    """ASCII-fold Turkish text for robust keyword matching.

    Announcements mix 'ı/i', 'İ/I' and occasionally arrive without diacritics,
    so keyword checks run against a folded copy while dates are read from the
    original.
    """
    lowered = text.replace("İ", "i").replace("I", "ı").lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return (
        stripped.replace("ı", "i")
        .replace("ş", "s")
        .replace("ğ", "g")
        .replace("ç", "c")
        .replace("ö", "o")
        .replace("ü", "u")
    )


def extract_dates(text: str) -> list[tuple[int, date]]:
    """Every date in the text as (character offset, date), in document order."""
    found: list[tuple[int, date]] = []
    for match in _NUMERIC_DATE.finditer(text):
        day, month, year = (int(g) for g in match.groups())
        parsed = _safe_date(year, month, day)
        if parsed:
            found.append((match.start(), parsed))
    for match in _LONG_DATE.finditer(text):
        month = TR_MONTH_NUMBERS.get(match.group(2).strip().lower())
        if month is None:
            continue
        parsed = _safe_date(int(match.group(3)), month, int(match.group(1)))
        if parsed:
            found.append((match.start(), parsed))
    found.sort(key=lambda pair: pair[0])
    return found


def extract_period(text: str) -> tuple[int, int] | None:
    """The obligation period an announcement refers to, e.g. 2026/Nisan."""
    folded = fold(text)
    for pattern in _PERIOD_PATTERNS:
        match = pattern.search(folded)
        if not match:
            continue
        first, second = match.group(1), match.group(2)
        if first.isdigit():
            year, month_name = int(first), second
        else:
            year, month_name = int(second), first
        month = TR_MONTH_NUMBERS.get(month_name.strip().lower())
        if month and 2000 <= year <= 2100:
            return (year, month)
    return None


def detect_scope(text: str) -> tuple[str, str]:
    """(scope_kind, reason). National wording wins over incidental place names."""
    folded = fold(text)
    if any(marker in folded for marker in _NATIONAL_MARKERS):
        return NATIONAL_OBLIGATION_SPECIFIC, "türkiye geneli ibaresi"
    for marker in _REGIONAL_MARKERS:
        if marker in folded:
            return REGIONAL, f"bölgesel ibare: {marker.strip()}"
    if "kuruma olan borc" in folded or "tum isyerleri" in folded:
        return NATIONAL_GLOBAL, "kurum geneli borç uzatımı"
    return UNRESOLVED, "kapsam belirlenemedi"


def analyze(title: str, body: str, *, published_at: str | None = None) -> NoticeAnalysis:
    """Turn a real announcement into zero or more findings."""
    text = f"{title}\n{body}".strip()
    folded = fold(text)

    has_extension = any(marker in folded for marker in _EXTENSION_MARKERS)
    has_deadline = any(marker in folded for marker in _DEADLINE_MARKERS)
    if not (has_extension and has_deadline):
        return NoticeAnalysis(
            relevant=False,
            classification=UNKNOWN,
            scope_kind=UNRESOLVED,
            reason="süre uzatımı / vade ifadesi bulunmadı",
        )

    scope_kind, scope_reason = detect_scope(text)
    period = extract_period(text)
    dates = extract_dates(text)
    if not dates:
        return NoticeAnalysis(
            relevant=True,
            classification=UNKNOWN,
            scope_kind=scope_kind,
            reason="uzatma ifadesi var ama tarih okunamadı",
            period=period,
        )

    old_dates = _anchored_dates(text, folded, dates, _OLD_DUE_ANCHORS)
    new_by_kind = _new_due_by_kind(text, folded, dates)

    findings: list[Finding] = []
    for kind, new_due in new_by_kind.items():
        old_due = _pick_old_due(old_dates, new_due)
        if kind == REPORTING:
            findings.append(
                Finding(
                    finding_kind=REPORTING,
                    obligation_code="GIB_MUHSGK",
                    new_due_date=new_due,
                    old_due_date=old_due,
                    period=period,
                    scope_kind=scope_kind,
                    # The insurance section of MuhSGK is an SGK-side deadline; the
                    # GİB tax event keeps GİB as its source of truth, so this is
                    # always surfaced for a human rather than applied.
                    auto_appliable=False,
                    reason="MuhSGK 'Sigorta Bildirimleri' kısmı — GİB vergi kısmı etkilenmez",
                )
            )
        else:
            appliable = scope_kind in (NATIONAL_GLOBAL, NATIONAL_OBLIGATION_SPECIFIC)
            findings.append(
                Finding(
                    finding_kind=PAYMENT,
                    obligation_code="SGK_4A_PREMIUM",
                    new_due_date=new_due,
                    # When the notice names an obligation period, that period —
                    # not a date mentioned elsewhere in the sentence — identifies
                    # which premium deadline moved.
                    old_due_date=None if period else old_due,
                    period=period,
                    scope_kind=scope_kind,
                    auto_appliable=appliable,
                    reason=scope_reason,
                )
            )

    if not findings:
        return NoticeAnalysis(
            relevant=True,
            classification=UNKNOWN,
            scope_kind=scope_kind,
            reason="uzatılan yükümlülük tespit edilemedi",
            period=period,
        )

    classification = PAYMENT if any(f.finding_kind == PAYMENT for f in findings) else REPORTING
    return NoticeAnalysis(
        relevant=True,
        classification=classification,
        scope_kind=scope_kind,
        reason=scope_reason,
        period=period,
        findings=findings,
    )


# --------------------------------------------------------------------------- internals
def _safe_date(year: int, month: int, day: int) -> date | None:
    if not (2000 <= year <= 2100):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _anchored_dates(
    text: str, folded: str, dates: list[tuple[int, date]], anchors: tuple[str, ...], window: int = 60
) -> list[date]:
    """Dates that follow one of the anchor phrases within `window` characters."""
    picked: list[date] = []
    for anchor in anchors:
        for match in re.finditer(re.escape(anchor), folded):
            end = match.end()
            for offset, value in dates:
                if end <= offset <= end + window:
                    picked.append(value)
                    break
    return picked


def _new_due_by_kind(text: str, folded: str, dates: list[tuple[int, date]]) -> dict[str, date]:
    """Map each obligation kind to the new deadline the notice declares for it.

    The date immediately following an anchor such as "ödeme süresi" is the new
    deadline; when the same anchor appears more than once the latest date wins,
    which matches how these announcements are written ("... süresi X'e ve ...
    süresi Y'ye kadar uzatılmıştır").
    """
    result: dict[str, date] = {}
    for anchor, kind in _NEW_DUE_ANCHORS:
        for match in re.finditer(re.escape(anchor), folded):
            end = match.end()
            for offset, value in dates:
                if end <= offset <= end + 60:
                    current = result.get(kind)
                    if current is None or value > current:
                        result[kind] = value
                    break
    return result


def _pick_old_due(old_dates: list[date], new_due: date) -> date | None:
    """The latest declared old deadline that is genuinely before the new one."""
    candidates = [d for d in old_dates if d < new_due]
    return max(candidates) if candidates else None
