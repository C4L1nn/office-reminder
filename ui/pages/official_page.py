from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QTableWidgetItem, QVBoxLayout, QWidget

from services.formatting import short_date
from services.official_update_service import OfficialUpdateService
from ui.shell import Page
from ui.theme import tokens
from ui.widgets import (
    Badge,
    Card,
    TableStack,
    align_headers,
    button,
    cell_widget,
    configure_columns,
    label,
)

STATUS_TONES = {
    "SYNCED": ("Güncel", "success"),
    "UNCHANGED": ("Güncel", "success"),
    "UPDATED": ("Güncellendi", "accent"),
    "NEEDS_REVIEW": ("İnceleme bekliyor", "warning"),
    "NEEDS_DATA": ("Veri eksik", "warning"),
    "FAILED": ("Başarısız", "danger"),
    "NEVER_SYNCED": ("Çevrimiçi kontrol edilmedi", "neutral"),
    "NOT_AVAILABLE": ("Yayımlanmadı", "neutral"),
    "RUNNING": ("Çalışıyor", "accent"),
}

REVISION_HEADERS = ["Tespit", "Kaynak", "Yükümlülük", "Dönem", "Eski tarih", "Yeni tarih"]


def humanize(stamp: str | None) -> str:
    if not stamp:
        return "—"
    try:
        value = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return str(stamp)[:16]
    return value.astimezone().strftime("%d.%m.%Y %H:%M")


class OfficialPage(Page):
    """Where official dates come from, when they were last checked, what changed."""

    sync_requested = Signal()

    def __init__(self, official_service: OfficialUpdateService, parent: QWidget | None = None) -> None:
        super().__init__(
            "Resmî Güncellemeler",
            "GİB vergi takvimi ve SGK duyurularının kontrol durumu ile uygulanan tarih değişiklikleri.",
            parent,
            scrollable=True,
        )
        self.official_service = official_service
        self._build()

    def _build(self) -> None:
        self.sync_button = button("Şimdi Kontrol Et", "primary", "refresh")
        self.sync_button.clicked.connect(self.sync_requested.emit)
        self.header.add_action(self.sync_button)

        self.sources_card = Card("Kaynaklar")
        self.sources_body = QVBoxLayout()
        self.sources_body.setSpacing(tokens().space_sm)
        self.sources_card.add_layout(self.sources_body)
        self.add(self.sources_card)

        self.review_card = Card("İnceleme Bekleyen Duyurular")
        self.review_body = QVBoxLayout()
        self.review_body.setSpacing(tokens().space_sm)
        self.review_card.add_layout(self.review_body)
        self.add(self.review_card)

        history = Card("Uygulanan Tarih Değişiklikleri")
        history.setProperty("flush", True)
        self.stack = TableStack(
            REVISION_HEADERS,
            "Resmî tarih değişikliği yok",
            "GİB veya SGK bir vadeyi değiştirdiğinde değişiklik burada geçmişiyle listelenir ve "
            "ilgili şirketler için bildirim gönderilir.",
            None,
            "shield",
        )
        self.table = self.stack.table
        configure_columns(self.table, [136, 84, None, None, 104, 104])
        align_headers(self.table, center=(1, 4, 5))
        self.stack.setMinimumHeight(220)
        history.add(self.stack)
        self.add(history, 1)

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self._render_sources()
        self._render_reviews()
        self._render_revisions()

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear(item.layout())

    def status_tone(self) -> tuple[str, str]:
        """Overall tone for the sidebar footer."""
        try:
            rows = self.official_service.status_summary()
        except Exception:
            return "Resmî kaynak durumu okunamadı", "warning"
        if any(row["status"] == "FAILED" for row in rows):
            return "Son resmî kontrol başarısız", "danger"
        if any(row["status"] == "NEVER_SYNCED" for row in rows):
            return "Resmî kaynaklar henüz kontrol edilmedi", "neutral"
        pending = sum(row["pending_review"] for row in rows)
        if pending:
            return f"{pending} duyuru inceleme bekliyor", "warning"
        newest = max((row["last_success_at"] or "" for row in rows), default="")
        return f"Resmî kaynaklar güncel · {humanize(newest)}", "success"

    def _render_sources(self) -> None:
        self._clear(self.sources_body)
        try:
            rows = self.official_service.status_summary()
        except Exception as exc:
            self.sources_body.addWidget(label(f"Durum okunamadı: {exc}", "Muted", wrap=True))
            return

        from ui.widgets import separator

        for index, row in enumerate(rows):
            if index:
                self.sources_body.addWidget(separator())

            text, tone = STATUS_TONES.get(row["status"], (row["status"], "neutral"))
            block = QVBoxLayout()
            block.setSpacing(2)

            line = QHBoxLayout()
            line.setSpacing(tokens().space_sm)
            name = label(row["label"], "SectionTitle")
            name.setFixedWidth(190)
            line.addWidget(name)
            line.addWidget(Badge(text, tone))
            if row["pending_review"]:
                line.addWidget(Badge(f"{row['pending_review']} inceleme", "warning"))
            line.addStretch()
            line.addWidget(label(f"Son başarılı: {humanize(row['last_success_at'])}", "Muted"))
            block.addLayout(line)

            detail = row["detail"]
            if row["status"] == "FAILED" and row["last_error"]:
                # Never show a traceback; say what failed and when it last worked.
                detail = (
                    f"Son kontrol başarısız ({humanize(row['last_attempt_at'])}). "
                    f"Yerel takvim çalışmaya devam ediyor."
                )
            hint = label(detail, "Caption", wrap=True)
            hint.setContentsMargins(190 + tokens().space_sm, 0, 0, 0)
            block.addWidget(hint)

            holder = QWidget()
            holder.setLayout(block)
            self.sources_body.addWidget(holder)

    def _render_reviews(self) -> None:
        self._clear(self.review_body)
        try:
            reviews = self.official_service.list_pending_reviews(limit=20)
        except Exception:
            reviews = []
        self.review_card.setVisible(bool(reviews))
        for review in reviews:
            line = QHBoxLayout()
            line.setSpacing(tokens().space_sm)
            title = review["title"] or "(başlıksız duyuru)"
            line.addWidget(label(title, "Muted", wrap=True), 1)
            if review.get("old_due_date") and review.get("new_due_date"):
                line.addWidget(
                    Badge(f"{review['old_due_date']} → {review['new_due_date']}", "warning")
                )
            if review.get("scope_kind") == "REGIONAL":
                line.addWidget(Badge("Bölgesel", "info"))
            line.addWidget(label(review["published_at"] or "", "Caption"))
            holder = QWidget()
            holder.setLayout(line)
            self.review_body.addWidget(holder)
            if review.get("reason"):
                self.review_body.addWidget(label(review["reason"], "Caption", wrap=True))

    def _render_revisions(self) -> None:
        try:
            revisions = self.official_service.list_revisions(limit=200)
        except Exception as exc:
            QMessageBox.warning(self, "Geçmiş okunamadı", str(exc))
            revisions = []

        self.table.setRowCount(len(revisions))
        for row, revision in enumerate(revisions):
            detected = QTableWidgetItem(humanize(revision["detected_at"]))
            detected.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, detected)

            source = revision["source_kind"]
            self.table.setCellWidget(
                row,
                1,
                cell_widget(Badge("GİB" if source == "GIB" else source, "accent" if source == "GIB" else "info")),
            )

            item = QTableWidgetItem(revision["obligation_name"])
            item.setToolTip(f"{revision['title']}\n{revision['reason'] or ''}")
            self.table.setItem(row, 2, item)

            self.table.setItem(row, 3, QTableWidgetItem(revision["period_label"] or "—"))

            for index, key in ((4, "old_due_date"), (5, "new_due_date")):
                cell = QTableWidgetItem(_date_text(revision[key]))
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, index, cell)

        self.stack.show_rows(len(revisions))

    def set_busy(self, busy: bool) -> None:
        self.sync_button.setEnabled(not busy)
        self.sync_button.setText("Kontrol ediliyor…" if busy else "Şimdi Kontrol Et")


def _date_text(value: str | None) -> str:
    if not value:
        return "—"
    try:
        from datetime import date

        return short_date(date.fromisoformat(value))
    except ValueError:
        return value
