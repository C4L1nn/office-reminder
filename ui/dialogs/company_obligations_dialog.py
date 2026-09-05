from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QWidget,
)

from services.company_service import KDV_VARIANTS, SGK_WAGE_PERIODS, CompanyService
from ui.dialogs.base import FormDialog
from ui.theme import tokens
from ui.widgets import Badge, label

CATEGORY_TITLES = {
    "TAX": "Vergi",
    "SGK": "SGK",
    "E_LEDGER": "e-Defter / e-Belge",
    "SYSTEM": "Bildirimler",
}
CATEGORY_ORDER = ("TAX", "SGK", "E_LEDGER", "SYSTEM")

KDV_OPTIONS = (
    ("KDV_STANDARD_MONTHLY", "Aylık beyan", "Standart KDV, her ay beyan edilir (yılda 12)."),
    ("KDV_STANDARD_QUARTERLY", "3 aylık beyan", "Üçer aylık dönemlerde beyan (yılda 4)."),
    ("KDV_TEVKIFAT", "Tevkifat", "Sorumlu sıfatıyla 2 No.lu KDV beyannamesi."),
)

WAGE_OPTIONS = (
    ("MONTHLY_1_END", "Ayın 1'i – ay sonu (yaygın)"),
    ("MONTHLY_15_14", "Ayın 15'i – takip eden ayın 14'ü"),
)

# Obligations that need more than a yes/no answer before their official dates
# can be projected onto the company.
PROFILE_DRIVEN = {"GIB_KDV", "SGK_4A_PREMIUM"}


class CompanyObligationsDialog(FormDialog):
    """Pick the obligations a company is subject to, and qualify them.

    The dialog only collects the answer. Writing it — the obligation set and the
    profile together — is a single service transaction performed by the caller,
    so a first-time selection can never lose its profile.
    """

    def __init__(
        self,
        company_service: CompanyService,
        company_id: int,
        company_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(f"Yükümlülük Profili — {company_name}", "Profili Kaydet", parent, width=680)
        self.company_service = company_service
        self.company_id = company_id
        self._checks: dict[int, QCheckBox] = {}
        self._codes: dict[int, str] = {}
        self._rows: dict[int, QWidget] = {}
        self._section_rows: list[tuple[object, list[QWidget]]] = []
        self._kdv_checks: dict[str, QCheckBox] = {}
        self.resize(700, 740)
        self._build()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        profile = self.company_service.get_obligation_profile(self.company_id)
        grouped = self.company_service.grouped_obligation_types()

        intro = self.add_section(
            "Tabi Olunan Yükümlülükler",
            "İşaretlenen yükümlülüklerin resmî tarihleri bu şirket için otomatik takip edilir. "
            "İşaretlenmeyenler hiçbir ekranda görünmez.",
        )
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Yükümlülük ara (örn: KDV, damga, e-defter)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        intro.add_full(self.filter_edit)

        self.summary = Badge("", "accent")
        summary_row = QWidget()
        summary_layout = QHBoxLayout(summary_row)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(self.summary)
        summary_layout.addStretch()
        intro.add_full(summary_row)

        for category in sorted(
            grouped, key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99
        ):
            types = grouped[category]
            section = self.add_section(f"{CATEGORY_TITLES.get(category, category)} ({len(types)})")
            section_rows: list[QWidget] = []
            for obligation in types:
                check = QCheckBox(obligation.name)
                check.setChecked(obligation.id in profile.obligation_type_ids)
                check.setToolTip(
                    f"{obligation.description or ''}\n\nKod: {obligation.code}\n"
                    f"Kaynak: {obligation.source_kind}"
                )
                check.toggled.connect(self._sync)
                self._checks[obligation.id] = check
                self._codes[obligation.id] = obligation.code

                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(tokens().space_sm)
                row_layout.addWidget(check)
                if obligation.code in PROFILE_DRIVEN:
                    row_layout.addWidget(Badge("Ek seçim gerekir", "warning"))
                row_layout.addStretch()
                section.add_full(row)
                # Search matches the visible name and the internal code, so both
                # "Katma Değer" and "GIB_KDV" find the same row.
                row.setProperty("search", f"{obligation.name} {obligation.code}".casefold())
                self._rows[obligation.id] = row
                section_rows.append(row)
            self._section_rows.append((section, section_rows))

        # --- KDV detail ---
        self.kdv_section = self.add_section(
            "KDV Profili",
            "Şirketin hangi KDV beyan türlerine tabi olduğunu seçin. Seçilmeyen türlerin resmî "
            "tarihleri gösterilmez.",
        )
        for code, title, description in KDV_OPTIONS:
            check = QCheckBox(title)
            check.setChecked(code in profile.kdv_variants)
            check.toggled.connect(self._sync)
            self._kdv_checks[code] = check
            self.kdv_section.add_full(check)
            hint = label(description, "Caption", wrap=True)
            hint.setContentsMargins(24, 0, 0, 0)
            self.kdv_section.add_full(hint)

        # --- SGK detail ---
        self.sgk_section = self.add_section(
            "SGK 4/a Ücret Dönemi",
            "Vade, seçilen ücret dönemine göre hesaplanır. Yanlış seçim yanlış ödeme tarihi üretir.",
        )
        self.wage_combo = QComboBox()
        for code, title in WAGE_OPTIONS:
            self.wage_combo.addItem(title, code)
        if profile.sgk_wage_period:
            index = self.wage_combo.findData(profile.sgk_wage_period)
            if index >= 0:
                self.wage_combo.setCurrentIndex(index)
        self.sgk_section.add_row("Ücret dönemi", self.wage_combo, required=True)


        self.finish_body()
        self._sync()

    # ------------------------------------------------------------------ state
    def _apply_filter(self, text: str) -> None:
        """Narrow a 40-item list; already-selected rows always stay visible."""
        needle = text.strip().casefold()
        for obligation_id, row in self._rows.items():
            haystack = row.property("search") or ""
            row.setVisible(not needle or needle in haystack or self._checks[obligation_id].isChecked())
        for section, rows in self._section_rows:
            section.setVisible(any(row.isVisible() for row in rows))

    def _checked_codes(self) -> set[str]:
        return {self._codes[oid] for oid, check in self._checks.items() if check.isChecked()}

    def _sync(self) -> None:
        codes = self._checked_codes()
        self.kdv_section.setVisible("GIB_KDV" in codes)
        self.sgk_section.setVisible("SGK_4A_PREMIUM" in codes)
        self.summary.setText(f"{len(codes)} yükümlülük seçili")

    # ------------------------------------------------------------------ validate / read
    def validate(self) -> bool:
        codes = self._checked_codes()
        if "GIB_KDV" in codes and not any(c.isChecked() for c in self._kdv_checks.values()):
            first = self._kdv_checks["KDV_STANDARD_MONTHLY"]
            self.mark_invalid(
                first,
                "KDV seçildi: en az bir KDV beyan türü işaretleyin, aksi hâlde KDV tarihleri gösterilmez.",
            )
            return False
        return True

    def get_selection(self) -> dict:
        codes = self._checked_codes()
        variants = [code for code, check in self._kdv_checks.items() if check.isChecked()]
        return {
            "obligation_type_ids": [oid for oid, check in self._checks.items() if check.isChecked()],
            "kdv_variants": [v for v in variants if v in KDV_VARIANTS] if "GIB_KDV" in codes else [],
            "sgk_wage_period": (
                self.wage_combo.currentData()
                if "SGK_4A_PREMIUM" in codes and self.wage_combo.currentData() in SGK_WAGE_PERIODS
                else None
            ),
        }

    # Backwards-compatible accessor used by older callers/tests.
    def get_selected_ids(self) -> list[int]:
        return self.get_selection()["obligation_type_ids"]
