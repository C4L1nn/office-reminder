"""Pure HTML parsers for the SGK announcement site.

Deliberately network-free so the production parser can be exercised against
saved snapshots of the real pages. Everything here maps 1:1 to markup that
sgk.gov.tr actually serves:

  list page   /duyuru/index/<unit-id>?page=<0-based>
              <a href="/duyuru/detay/<slug>" class="announcement-card ...">
                <div class="date-day">20</div>
                <div class="date-month">Mayıs</div>
                <div class="date-year">2026</div>
                <div class="announcement-content">
                  <div class="announcement-title ...">TITLE</div>

  detail page /duyuru/detay/<slug>
              <div class="... announcement-detail-title"><h1 ...>TITLE</h1>
              <span class="announcement-detail-date"> 1 Temmuz 2026 Çarşamba</span>
              <hr class="border-gray-300 mb-8">  ← body starts here
              <a href="/Download/DownloadFile?f=...&d=...">  ← attachments
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from dataclasses import dataclass, field

BASE_URL = "https://www.sgk.gov.tr"

TR_MONTH_NUMBERS = {
    "ocak": 1,
    "şubat": 2,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "agustos": 8,
    "eylül": 9,
    "eylul": 9,
    "ekim": 10,
    "kasım": 11,
    "kasim": 11,
    "aralık": 12,
    "aralik": 12,
}

_CARD = re.compile(
    r'<a\s+href="(?P<href>/duyuru/detay/[^"]+)"[^>]*class="[^"]*announcement-card[^"]*".*?'
    r'date-day[^>]*>\s*(?P<day>\d{1,2})\s*</div>.*?'
    r'date-month[^>]*>\s*(?P<month>[^<]+?)\s*</div>.*?'
    r'date-year[^>]*>\s*(?P<year>\d{4})\s*</div>.*?'
    r'announcement-title[^>]*>(?P<title>.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)

_PAGE_LINK = re.compile(r'href="[^"]*[?&]page=(\d+)"')
_TAG = re.compile(r"<[^>]+>")
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_DETAIL_TITLE = re.compile(
    r'announcement-detail-title.*?<h1[^>]*>(.*?)</h1>', re.DOTALL | re.IGNORECASE
)
_DETAIL_DATE = re.compile(r'announcement-detail-date[^>]*>(.*?)</span>', re.DOTALL | re.IGNORECASE)
_BODY_START = re.compile(r'<hr\s+class="border-gray-300[^"]*"\s*/?>', re.IGNORECASE)
_BODY_END = re.compile(r"<!--\s*GLightbox|<!--\s*Dosyalar|class=\"document-item", re.IGNORECASE)
_DOWNLOAD = re.compile(r'href="(/Download/DownloadFile\?[^"]+)"', re.IGNORECASE)
_DIRECT_FILE = re.compile(r'href="([^"]+\.(?:pdf|docx?|xlsx?))(?:\?[^"]*)?"', re.IGNORECASE)
_DOC_NAME = re.compile(
    r'class="document-item.*?<span[^>]*>(.*?)</span>', re.DOTALL | re.IGNORECASE
)


@dataclass(slots=True, frozen=True)
class NoticeLink:
    source_notice_key: str
    title: str
    published_at: str  # YYYY-MM-DD
    source_url: str
    href: str


@dataclass(slots=True)
class NoticeDetail:
    title: str | None = None
    published_at: str | None = None
    body: str = ""
    attachments: list[dict[str, str]] = field(default_factory=list)


#: sgk.gov.tr double-encodes Turkish letters in some announcement titles
#: ("&amp;#xD6;denecek"), so a single unescape leaves a literal "&#xD6;" on
#: screen. Two passes clear that; the bound stops a pathological string from
#: looping.
_MAX_UNESCAPE_PASSES = 3


def clean_text(raw: str) -> str:
    """Strip markup and entities, collapse whitespace."""
    without_scripts = _SCRIPT_OR_STYLE.sub(" ", raw)
    text = _TAG.sub(" ", without_scripts)
    for _ in range(_MAX_UNESCAPE_PASSES):
        decoded = html_lib.unescape(text)
        if decoded == text:
            break
        text = decoded
    text = text.replace("\xa0", " ").replace("​", "")
    return re.sub(r"\s+", " ", text).strip()


def notice_key_from_href(href: str) -> str:
    """Stable, collision-free key derived from the canonical detail URL slug.

    Slugs end with a publish timestamp, so a plain prefix truncation would make
    two long announcements from different dates share one key. When the slug has
    to be shortened, a digest of the full slug is appended instead.
    """
    slug = href.rstrip("/").split("/")[-1]
    normalized = re.sub(r"[^0-9A-Za-zğüşöçıİĞÜŞÖÇ]+", "_", slug).strip("_").upper()
    if len(normalized) <= 96:
        return f"SGK_{normalized}"
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:10].upper()
    return f"SGK_{normalized[:84]}_{digest}"


def parse_list_page(html: str) -> list[NoticeLink]:
    """Every announcement card on one list page, in document order."""
    results: list[NoticeLink] = []
    seen: set[str] = set()
    for match in _CARD.finditer(html):
        href = html_lib.unescape(match.group("href"))
        month = TR_MONTH_NUMBERS.get(html_lib.unescape(match.group("month")).strip().lower())
        if month is None:
            continue
        try:
            published = f"{int(match.group('year')):04d}-{month:02d}-{int(match.group('day')):02d}"
        except ValueError:
            continue
        key = notice_key_from_href(href)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            NoticeLink(
                source_notice_key=key,
                title=clean_text(match.group("title")),
                published_at=published,
                source_url=f"{BASE_URL}{href}" if href.startswith("/") else href,
                href=href,
            )
        )
    return results


def parse_page_numbers(html: str) -> list[int]:
    """0-based page indices advertised by the pager, always including page 0."""
    pages = {0}
    for value in _PAGE_LINK.findall(html):
        try:
            pages.add(int(value))
        except ValueError:
            continue
    return sorted(pages)


def parse_detail_page(html: str) -> NoticeDetail:
    detail = NoticeDetail()

    title_match = _DETAIL_TITLE.search(html)
    if title_match:
        detail.title = clean_text(title_match.group(1))

    date_match = _DETAIL_DATE.search(html)
    if date_match:
        detail.published_at = _parse_long_tr_date(clean_text(date_match.group(1)))

    start = _BODY_START.search(html)
    if start:
        rest = html[start.end() :]
        end = _BODY_END.search(rest)
        detail.body = clean_text(rest[: end.start()] if end else rest[:20000])

    names = [clean_text(name) for name in _DOC_NAME.findall(html)]
    seen_urls: set[str] = set()
    for index, href in enumerate(_DOWNLOAD.findall(html)):
        url = _absolute(html_lib.unescape(href))
        if url in seen_urls:
            continue
        seen_urls.add(url)
        detail.attachments.append(
            {"url": url, "filename": names[index] if index < len(names) else _filename_from(url)}
        )
    for href in _DIRECT_FILE.findall(html):
        url = _absolute(html_lib.unescape(href))
        if url in seen_urls or "/cdn/" in url:
            continue
        seen_urls.add(url)
        detail.attachments.append({"url": url, "filename": _filename_from(url)})

    return detail


def _absolute(href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"{BASE_URL}{href}"
    return f"{BASE_URL}/{href}"


def _filename_from(url: str) -> str:
    tail = url.split("/")[-1].split("?")[0]
    return tail or "ek"


def _parse_long_tr_date(text: str) -> str | None:
    """'1 Temmuz 2026 Çarşamba' -> '2026-07-01'."""
    match = re.search(r"(\d{1,2})\s+([A-Za-zğüşöçıİĞÜŞÖÇ]+)\s+(\d{4})", text)
    if not match:
        return None
    month = TR_MONTH_NUMBERS.get(match.group(2).strip().lower())
    if month is None:
        return None
    return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(1)):02d}"
