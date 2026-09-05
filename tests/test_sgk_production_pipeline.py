"""Production SGK pipeline exercised against real sgk.gov.tr snapshots.

No fixture identifier drives any business rule here: the service is fed the
exact bytes the real site served and must reach the right conclusion from the
announcement text alone.
"""

from __future__ import annotations

from datetime import date

import pytest

from services.sgk_notice_analyzer import PAYMENT, REPORTING, analyze
from services.sgk_notice_parser import parse_detail_page, parse_list_page, parse_page_numbers
from services.sgk_notice_service import SGK_LIST_URL, SgkNoticeService, snapshot_fetcher

LIST_URL_PAGE0 = f"{SGK_LIST_URL}?page=0"

KEY_20260520 = (
    "SGK_2026NISAN_AYIDONEMI_MUHTASAR_VE_PRIM_HIZMET_BEYANNAMELERININ_VE_AYLIK_PRIM_VE_HIZMET_BELG"
)
KEY_20260331 = "SGK_KURUMA_OLAN_BORCLARIN_SON_ODEME_TARIHININ_UZATILMASINA_DAIR_BASIN_DUYURUSU_2026_03_31_06_39_45"


def _snapshots(fixture_dir):
    """URL -> bytes map covering list, both details and the real PDF attachment."""
    list_html = (fixture_dir / "list_sigorta_primleri_page0.html").read_bytes()
    mapping = {LIST_URL_PAGE0: list_html}

    links = {link.published_at: link for link in parse_list_page(list_html.decode("utf-8"))}
    detail_files = {
        "2026-05-20": "detail_20260520_muhsgk_aphb.html",
        "2026-03-31": "detail_20260331_borc_uzatma.html",
        "2025-12-26": "detail_20251226_regional_mucbir.html",
    }
    for published, filename in detail_files.items():
        if published in links:
            mapping[links[published].source_url] = (fixture_dir / filename).read_bytes()

    detail = parse_detail_page(
        (fixture_dir / "detail_20260331_borc_uzatma.html").read_text(encoding="utf-8")
    )
    for attachment in detail.attachments:
        mapping[attachment["url"]] = (fixture_dir / "attachment_20260331_borc_uzatma.pdf").read_bytes()
    return mapping, links


# ---------------------------------------------------------------- list parsing
def test_real_list_page_parses_every_card(sgk_fixture_dir):
    html = (sgk_fixture_dir / "list_sigorta_primleri_page0.html").read_text(encoding="utf-8")
    links = parse_list_page(html)

    assert len(links) == 10, "gerçek liste sayfasında 10 duyuru kartı var"
    keys = {link.source_notice_key for link in links}
    assert len(keys) == 10, "slug anahtarları çakışmamalı"
    assert all(link.source_url.startswith("https://www.sgk.gov.tr/duyuru/detay/") for link in links)
    assert {link.published_at for link in links} >= {"2026-05-20", "2026-03-31"}
    # Titles come back as readable Turkish, not HTML entities.
    title = next(link.title for link in links if link.published_at == "2026-03-31")
    assert title.startswith("Kuruma Olan Borçların")
    assert "&#x" not in title


def test_pagination_is_zero_based_and_discovered_from_markup(sgk_fixture_dir):
    html = (sgk_fixture_dir / "list_sigorta_primleri_page0.html").read_text(encoding="utf-8")
    pages = parse_page_numbers(html)
    assert pages[0] == 0, "site sayfalaması 0 tabanlı"
    assert len(pages) > 1


def test_every_page_is_parsed_not_only_the_last(sgk_fixture_dir):
    """Regression: the walk used to fetch N pages but parse only the last one."""
    list_html = (sgk_fixture_dir / "list_sigorta_primleri_page0.html").read_bytes()
    page1_html = list_html.replace(
        b"/duyuru/detay/Iskolu-Kodlarinin-Guncellenmesi",
        b"/duyuru/detay/Sayfa2-Ozel-Duyuru",
    )
    fetched: list[str] = []

    def fetcher(url, timeout=20):
        fetched.append(url)
        if url.endswith("page=0"):
            return list_html, {"content-type": "text/html"}
        if url.endswith("page=1"):
            return page1_html, {"content-type": "text/html"}
        raise RuntimeError("unexpected url")

    service = SgkNoticeService.__new__(SgkNoticeService)
    service.database = None
    service.list_url = SGK_LIST_URL
    service._fetch = fetcher
    service.get_watermark = lambda: None  # type: ignore[method-assign]

    links = SgkNoticeService.discover_notices(service, max_pages=2)
    keys = {link.source_notice_key for link in links}

    assert f"{SGK_LIST_URL}?page=0" in fetched and f"{SGK_LIST_URL}?page=1" in fetched
    assert any("ISKOLU_KODLARININ" in key for key in keys), "1. sayfanın kartları kaybolmamalı"
    assert any("SAYFA2_OZEL_DUYURU" in key for key in keys), "2. sayfanın kartları da parse edilmeli"


# ---------------------------------------------------------------- detail parsing
def test_real_detail_page_yields_body_and_attachment(sgk_fixture_dir):
    detail = parse_detail_page(
        (sgk_fixture_dir / "detail_20260520_muhsgk_aphb.html").read_text(encoding="utf-8")
    )
    assert detail.published_at == "2026-05-20"
    assert "Sigorta Bildirimleri" in detail.body
    assert "26.05.2026" in detail.body
    assert detail.attachments and detail.attachments[0]["url"].startswith(
        "https://www.sgk.gov.tr/Download/DownloadFile"
    )


def test_body_less_notice_falls_back_to_pdf_text(sgk_fixture_dir, qt_app):
    from services.document_text import extract_pdf_text

    detail = parse_detail_page(
        (sgk_fixture_dir / "detail_20260331_borc_uzatma.html").read_text(encoding="utf-8")
    )
    assert len(detail.body) < 40, "bu duyurunun HTML gövdesi boş; metin PDF ekinde"

    text = extract_pdf_text(sgk_fixture_dir / "attachment_20260331_borc_uzatma.pdf")
    assert "31/03/2026" in text and "07/04/2026" in text


# ---------------------------------------------------------------- analysis
def test_20_may_notice_produces_two_findings(sgk_fixture_dir):
    detail = parse_detail_page(
        (sgk_fixture_dir / "detail_20260520_muhsgk_aphb.html").read_text(encoding="utf-8")
    )
    analysis = analyze(detail.title or "", detail.body)

    assert analysis.relevant
    assert analysis.period == (2026, 4)
    by_kind = {f.finding_kind: f for f in analysis.findings}

    payment = by_kind[PAYMENT]
    assert payment.new_due_date == date(2026, 6, 5)
    assert payment.auto_appliable is True

    reporting = by_kind[REPORTING]
    assert reporting.old_due_date == date(2026, 5, 26)
    assert reporting.new_due_date == date(2026, 6, 3)
    assert reporting.auto_appliable is False, "MuhSGK sigorta kısmı GİB eventine otomatik uygulanmaz"


def test_31_march_notice_reads_dates_from_its_pdf(sgk_fixture_dir, qt_app):
    from services.document_text import extract_pdf_text

    detail = parse_detail_page(
        (sgk_fixture_dir / "detail_20260331_borc_uzatma.html").read_text(encoding="utf-8")
    )
    text = extract_pdf_text(sgk_fixture_dir / "attachment_20260331_borc_uzatma.pdf")
    analysis = analyze(detail.title or "", text)

    assert len(analysis.findings) == 1
    finding = analysis.findings[0]
    assert finding.finding_kind == PAYMENT
    assert finding.old_due_date == date(2026, 3, 31)
    assert finding.new_due_date == date(2026, 4, 7)
    assert finding.auto_appliable is True


def test_regional_force_majeure_notice_is_never_auto_applied(sgk_fixture_dir):
    detail = parse_detail_page(
        (sgk_fixture_dir / "detail_20251226_regional_mucbir.html").read_text(encoding="utf-8")
    )
    analysis = analyze(detail.title or "", detail.body)

    assert analysis.scope_kind == "REGIONAL"
    assert all(not f.auto_appliable for f in analysis.findings)


@pytest.mark.parametrize(
    "title",
    [
        "Bedeli Ödenecek İlaçlar Listesinde Yapılan Düzenlemeler Hakkında Duyuru 2026/27",
        "29/06/2026 SUT Değişiklik Tebliği İşlenmiş Güncel 2013 SUT",
        "İşkolu Kodlarının Güncellenmesi",
    ],
)
def test_unrelated_notices_are_not_flagged_for_review(title):
    analysis = analyze(title, "")
    assert analysis.relevant is False


# ---------------------------------------------------------------- full pipeline
def test_pipeline_applies_31_march_extension(seeded_db, sgk_fixture_dir, tmp_path, qt_app):
    mapping, links = _snapshots(sgk_fixture_dir)
    service = SgkNoticeService(
        seeded_db, raw_dir=tmp_path / "sgk", fetcher=snapshot_fetcher(mapping)
    )

    with seeded_db.session() as conn:
        before = conn.execute(
            "SELECT id, effective_due_date FROM official_calendar_events "
            "WHERE source_event_key = 'SGK_4A_2026_02_1END'"
        ).fetchone()
    assert before["effective_due_date"] == "2026-03-31"

    result = service.process_notice(links["2026-03-31"])
    assert result["status"] == "AUTO_APPLIED"

    with seeded_db.session() as conn:
        after = conn.execute(
            "SELECT normal_due_date, effective_due_date FROM official_calendar_events WHERE id = ?",
            (before["id"],),
        ).fetchone()
        revisions = conn.execute(
            "SELECT old_due_date, new_due_date FROM official_calendar_revisions WHERE official_event_id = ?",
            (before["id"],),
        ).fetchall()

    assert after["effective_due_date"] == "2026-04-07"
    assert after["normal_due_date"] == "2026-03-31", "normal vade değişmez"
    assert [(r["old_due_date"], r["new_due_date"]) for r in revisions] == [("2026-03-31", "2026-04-07")]


def test_pipeline_20_may_mixed_outcome(seeded_db, sgk_fixture_dir, tmp_path, qt_app):
    mapping, links = _snapshots(sgk_fixture_dir)
    service = SgkNoticeService(
        seeded_db, raw_dir=tmp_path / "sgk", fetcher=snapshot_fetcher(mapping)
    )

    result = service.process_notice(links["2026-05-20"])
    assert result["status"] == "NEEDS_REVIEW", "karma sonuç: bir bulgu inceleme bekliyor"

    findings = {f["finding_kind"]: f for f in service.list_findings(result["notice_id"])}

    payment = findings[PAYMENT]
    assert payment["status"] == "AUTO_APPLIED"
    assert payment["new_due_date"] == "2026-06-05"

    reporting = findings[REPORTING]
    assert reporting["status"] == "NEEDS_REVIEW"
    assert reporting["old_due_date"] == "2026-05-26"
    assert reporting["new_due_date"] == "2026-06-03"

    with seeded_db.session() as conn:
        april = conn.execute(
            "SELECT effective_due_date FROM official_calendar_events WHERE source_event_key='SGK_4A_2026_04_1END'"
        ).fetchone()
        muhsgk_revisions = conn.execute(
            """
            SELECT COUNT(*) AS c FROM official_calendar_revisions r
            JOIN official_calendar_events e ON e.id = r.official_event_id
            JOIN obligation_types t ON t.id = e.obligation_type_id
            WHERE t.code = 'GIB_MUHSGK'
            """
        ).fetchone()

    assert april["effective_due_date"] == "2026-06-05"
    assert muhsgk_revisions["c"] == 0, "GIB_MUHSGK GİB kaynaklıdır, SGK duyurusuyla değişmez"


def test_pipeline_is_idempotent_and_records_sync_state(seeded_db, sgk_fixture_dir, tmp_path, qt_app):
    mapping, _links = _snapshots(sgk_fixture_dir)
    service = SgkNoticeService(
        seeded_db, raw_dir=tmp_path / "sgk", fetcher=snapshot_fetcher(mapping)
    )

    first = service.sync(max_pages=1)
    second = service.sync(max_pages=1)

    assert first["discovered"] == 10
    assert first["auto_applied"] >= 1
    assert second["auto_applied"] == 0, "ikinci çalıştırmada yeni revision üretilmemeli"

    with seeded_db.session() as conn:
        revisions = conn.execute("SELECT COUNT(*) AS c FROM official_calendar_revisions").fetchone()["c"]
        state = conn.execute(
            "SELECT status, last_success_at, last_error FROM official_source_state WHERE source_code='SGK_NOTICES'"
        ).fetchone()
        runs = conn.execute(
            "SELECT COUNT(*) AS c FROM official_sync_runs WHERE source_code='SGK_NOTICES'"
        ).fetchone()["c"]

    assert revisions == 2, "31 Mart + 20 Mayıs ödeme uzatımları, tekrar edilmeden"
    assert state["status"] in ("SYNCED", "UPDATED")
    assert state["last_success_at"] and state["last_error"] is None
    assert runs == 2


def test_failed_sync_records_error_state(seeded_db, tmp_path):
    def broken(url, timeout=20):
        raise OSError("network down")

    service = SgkNoticeService(seeded_db, raw_dir=tmp_path / "sgk", fetcher=broken)
    result = service.sync()

    assert result["status"] == "FAILED"
    with seeded_db.session() as conn:
        state = conn.execute(
            "SELECT status, last_error, last_success_at FROM official_source_state WHERE source_code='SGK_NOTICES'"
        ).fetchone()
    assert state["status"] == "FAILED"
    assert state["last_error"]
    assert state["last_success_at"] is None, "başarısız kontrol başarılı sayılmaz"


def test_double_encoded_titles_are_fully_decoded() -> None:
    """sgk.gov.tr writes "&amp;#xD6;" for "Ö" on some announcement pages.

    A single unescape leaves the literal "&#xD6;" in the title, which is what
    the office saw in the pending-review list.
    """
    from services.sgk_notice_parser import clean_text

    raw = "Bedeli &amp;#xD6;denecek &amp;#x130;la&amp;#xE7;lar Listesinde Yap&amp;#x131;lan"
    assert clean_text(raw) == "Bedeli Ödenecek İlaçlar Listesinde Yapılan"


def test_single_encoded_titles_still_decode() -> None:
    from services.sgk_notice_parser import clean_text

    assert clean_text("Bedeli &#xD6;denecek") == "Bedeli Ödenecek"
    assert clean_text("2026/Nisan Ay&#x131;") == "2026/Nisan Ayı"


def test_an_ampersand_in_a_title_survives() -> None:
    """Repeated unescaping must not eat legitimate text."""
    from services.sgk_notice_parser import clean_text

    assert clean_text("A &amp; B Ortakl&#x131;k") == "A & B Ortaklık"


def test_repeated_decoding_is_bounded() -> None:
    """A pathological string stops instead of looping."""
    from services.sgk_notice_parser import _MAX_UNESCAPE_PASSES, clean_text

    assert _MAX_UNESCAPE_PASSES >= 2
    deep = "&amp;" * 10 + "#xD6;"
    result = clean_text(deep)
    assert result.count("&amp;") < 10
