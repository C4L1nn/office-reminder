"""Design tokens and the single stylesheet built from them.

Colours, spacing and type sizes live here and nowhere else. Widgets set an
object name or a dynamic property and let the stylesheet resolve it, so a
palette change is one edit rather than a search across twenty files.

Two palettes share the same token names. Which one is used follows the
operating system's colour scheme, with dark as the default — the app runs all
day on office machines that are usually dark.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path

FONT_FAMILY = '"Segoe UI", "Segoe UI Variable", system-ui, sans-serif'
FONT_MONO = '"Cascadia Mono", Consolas, "Courier New", monospace'


@dataclass(frozen=True, slots=True)
class Tokens:
    name: str

    # Surfaces, ordered back to front. No pure black, no pure white: the
    # hierarchy is carried by small steps, not by maximum contrast.
    canvas: str
    rail: str
    surface: str
    surface_alt: str
    surface_hover: str
    surface_active: str
    overlay: str

    border: str
    border_strong: str
    divider: str

    text: str
    text_muted: str
    text_faint: str
    text_on_accent: str

    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    selected: str
    accent_border: str

    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    info: str
    info_soft: str

    shadow: str

    # Geometry
    radius_sm: int = 4
    radius: int = 7
    radius_lg: int = 11
    space_xs: int = 4
    space_sm: int = 8
    space: int = 12
    space_lg: int = 18
    space_xl: int = 26
    # A single-line row does not need 46px. 38 fits ~15 rows on a 720p window
    # instead of 8, which is what this screen is actually for.
    row_height: int = 38
    control_height: int = 30
    group_height: int = 26

    # Type scale (pt)
    text_display: float = 16.0
    text_title: float = 12.0
    text_body: float = 9.5
    text_small: float = 8.5
    text_caption: float = 8.0
    text_metric: float = 25.0


DARK = Tokens(
    name="dark",
    canvas="#15171c",
    rail="#111318",
    surface="#1c1f26",
    surface_alt="#21242c",
    surface_hover="#272b34",
    surface_active="#2e333e",
    overlay="#1a1d23",
    border="#2c313b",
    border_strong="#3a4150",
    divider="#242832",
    text="#e7eaf0",
    text_muted="#a2abba",
    text_faint="#8b93a2",
    text_on_accent="#ffffff",
    accent="#4a8cf0",
    accent_hover="#5c99f4",
    accent_pressed="#3b7ade",
    accent_soft="#1d2a41",
    selected="#26385a",
    accent_border="#31517f",
    success="#4bb387",
    success_soft="#16302a",
    warning="#d9a13c",
    warning_soft="#332a17",
    danger="#e2695a",
    danger_soft="#3a221f",
    info="#5aa9c7",
    info_soft="#172c34",
    shadow="rgba(0, 0, 0, 0.45)",
)

LIGHT = Tokens(
    name="light",
    canvas="#f4f5f7",
    rail="#eceef2",
    surface="#ffffff",
    surface_alt="#f7f8fa",
    surface_hover="#eef1f6",
    surface_active="#e4e9f2",
    overlay="#ffffff",
    border="#dfe3ea",
    border_strong="#c5ccd8",
    divider="#e9ecf1",
    text="#1c222c",
    text_muted="#5b6577",
    text_faint="#636b78",
    text_on_accent="#ffffff",
    accent="#2c69c4",
    accent_hover="#3d7bda",
    accent_pressed="#2660bb",
    accent_soft="#e8f0fd",
    selected="#d7e6fb",
    accent_border="#bcd3f5",
    success="#1b7954",
    success_soft="#e3f4ec",
    warning="#8e6216",
    warning_soft="#fbf1dd",
    danger="#ba4237",
    danger_soft="#fbe9e7",
    info="#27738e",
    info_soft="#e4f2f7",
    shadow="rgba(20, 26, 38, 0.12)",
)

_active: Tokens = DARK


def tokens() -> Tokens:
    """The palette currently in use."""
    return _active


def tokens_for(choice: str, app=None) -> Tokens:
    """Resolve a stored appearance choice to a palette.

    "system" follows Windows; anything else is the user's explicit override.
    """
    if choice == "light":
        return LIGHT
    if choice == "dark":
        return DARK
    return detect_tokens(app)


def detect_tokens(app=None) -> Tokens:
    """Follow the OS colour scheme, defaulting to dark."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        hints = (app or QGuiApplication.instance()).styleHints()
        if hints.colorScheme() == Qt.ColorScheme.Light:
            return LIGHT
    except (AttributeError, RuntimeError):
        # Older Qt or no application object yet: dark is the deliberate default.
        pass
    return DARK


@dataclass(frozen=True, slots=True)
class Paper:
    """One sticky-note colour: the paper, its edge, its header strip, its ink."""

    fill: str
    edge: str
    header: str
    ink: str


#: Sticky-note papers, per theme. Notes store a palette key ("yellow"), never a
#: hex value, so the same note is drawn with bright office-desk colours on the
#: light theme and with muted, low-glare ones on the dark theme.
NOTE_PAPERS: dict[str, dict[str, Paper]] = {
    "light": {
        "yellow": Paper("#fff3b0", "#f0dc85", "#ffe886", "#3a3320"),
        "amber": Paper("#ffdca8", "#f2c47e", "#ffcd85", "#3d2f18"),
        "mint": Paper("#c9f0d9", "#a3ddb9", "#aae8c4", "#1e3a2b"),
        "sky": Paper("#cfe3ff", "#a7c8f5", "#b3d5ff", "#1d2f47"),
        "rose": Paper("#ffd3dd", "#f2adbd", "#ffbccb", "#43222c"),
        "lilac": Paper("#e4d6fb", "#c8b3ef", "#d5c1f7", "#2f2445"),
        "slate": Paper("#e3e7ee", "#c4ccd8", "#d3dae4", "#252b35"),
    },
    "dark": {
        "yellow": Paper("#4a4327", "#665c33", "#5c5230", "#f2ecd6"),
        "amber": Paper("#4d3b23", "#6b5231", "#5e492c", "#f6e6d0"),
        "mint": Paper("#22443a", "#31604f", "#2a5347", "#d8f0e4"),
        "sky": Paper("#23374f", "#345272", "#2c4462", "#d8e6f7"),
        "rose": Paper("#4a2b35", "#6a3d4b", "#5b3541", "#f7dbe3"),
        "lilac": Paper("#372f4e", "#4f446e", "#443a60", "#e5dcf7"),
        "slate": Paper("#30343d", "#454b58", "#3b404a", "#e2e6ee"),
    },
}

#: The order the swatches appear in the toolbar.
PAPER_ORDER = ("yellow", "amber", "mint", "sky", "rose", "lilac", "slate")


@contextmanager
def palette_override(palette: Tokens):
    """Resolve colours against another palette for the duration of the block.

    Used when printing: a board drawn in the dark theme is a slab of ink on
    white paper, so the export renders it with the light palette and puts the
    active one back. Only the token lookup is swapped — the application
    stylesheet is left alone, so nothing repaints outside the block.
    """
    global _active
    previous = _active
    _active = palette
    try:
        yield palette
    finally:
        _active = previous


def note_paper(key: str) -> Paper:
    """Resolve a stored palette key against the active theme."""
    papers = NOTE_PAPERS.get(tokens().name, NOTE_PAPERS["light"])
    return papers.get(key, papers["yellow"])


def apply_theme(app, palette: Tokens | None = None) -> Tokens:
    """Install the palette and stylesheet on a QApplication."""
    global _active
    _active = palette or detect_tokens(app)
    app.setStyleSheet(build_stylesheet(_active))
    return _active


# Qt's stylesheet cannot take inline SVG, so the few glyphs the stylesheet needs
# (checkbox tick, radio dot, dropdown chevrons) are written to disk once per
# palette and referenced by path. Styling ::indicator without supplying an image
# is what leaves a checked box as a blank coloured square.
_INDICATOR_ASSETS = {
    "check": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
    '<path d="M3.4 8.4 6.4 11.4 12.6 4.9" fill="none" stroke="{on_accent}" '
    'stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "dot": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
    '<circle cx="8" cy="8" r="3.4" fill="{on_accent}"/></svg>',
    "chevron_down": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
    '<path d="M4 6.2 8 10.2 12 6.2" fill="none" stroke="{muted}" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "chevron_up": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
    '<path d="M4 9.8 8 5.8 12 9.8" fill="none" stroke="{muted}" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>',
}


def _asset_paths(t: Tokens) -> dict[str, str]:
    directory = Path(tempfile.gettempdir()) / "office_reminder_theme" / t.name
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for name, template in _INDICATOR_ASSETS.items():
        target = directory / f"{name}.svg"
        content = template.format(on_accent=t.text_on_accent, muted=t.text_muted)
        try:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                target.write_text(content, encoding="utf-8")
        except OSError:
            # Without the asset the control still works, just without its glyph.
            paths[f"asset_{name}"] = ""
            continue
        paths[f"asset_{name}"] = target.as_posix()
    return paths


def build_stylesheet(t: Tokens) -> str:
    values = {k: v for k, v in asdict(t).items()}
    values["font"] = FONT_FAMILY
    values["mono"] = FONT_MONO
    values.update(_asset_paths(t))
    return _QSS.format(**values)


# --------------------------------------------------------------------------- QSS
# Organised by component. Object names used here:
#   #Rail #RailBrand #RailItem #RailFooter
#   #PageHeader #PageTitle #PageSubtitle
#   #Card #CardTitle #StatCard #StatValue #StatLabel #StatCaption
#   #Badge (property tone: neutral|accent|success|warning|danger|info)
#   #EmptyTitle #EmptyBody
#   QPushButton property variant: primary|ghost|danger|subtle
_QSS = """
* {{
    font-family: {font};
    font-size: {text_body}pt;
    outline: none;
}}

QWidget {{
    color: {text};
    background: transparent;
}}

QMainWindow, QDialog, #Canvas {{
    background: {canvas};
}}

/* ------------------------------------------------------------------ sidebar */
#Rail {{
    background: {rail};
    border-right: 1px solid {border};
}}

#RailBrand {{
    color: {text};
    font-size: {text_title}pt;
    font-weight: 600;
    padding: 2px 0;
}}

#ListPlaceholder {{
    color: {text_faint};
    font-size: {text_body}pt;
    background: transparent;
}}

#RailSection {{
    color: {text_faint};
    font-size: {text_caption}pt;
    font-weight: 600;
    letter-spacing: 0.8px;
    padding: {space}px {space_sm}px {space_xs}px {space_sm}px;
}}

#RailItem {{
    background: transparent;
    border: none;
    /* Space reserved for the selected item's accent bar, so the label does
       not shift when the selection moves. */
    border-left: 3px solid transparent;
    border-radius: {radius}px;
    color: {text_muted};
    padding: 9px 10px;
    text-align: left;
    font-size: {text_body}pt;
}}
#RailItem:hover {{
    background: {surface_hover};
    color: {text};
}}
#RailItem:checked {{
    border-left: 3px solid {accent};
    background: {accent_soft};
    color: {text};
    font-weight: 600;
}}

#RailFooter {{
    color: {text_faint};
    font-size: {text_caption}pt;
}}

#RailDivider {{
    background: {divider};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* ------------------------------------------------------------------ header */
#PageHeader {{
    background: {canvas};
    border-bottom: 1px solid {divider};
}}
#PageTitle {{
    font-size: {text_display}pt;
    font-weight: 600;
    /* Large text needs tighter tracking to stop looking loose. */
    letter-spacing: -0.4px;
    color: {text};
}}
#PageSubtitle {{
    font-size: {text_small}pt;
    color: {text_muted};
}}
#SectionTitle {{
    font-size: {text_title}pt;
    font-weight: 600;
    color: {text};
}}
#FieldLabel {{
    color: {text_muted};
    font-size: {text_small}pt;
}}
#Caption {{
    color: {text_faint};
    font-size: {text_caption}pt;
}}
#Muted {{
    color: {text_muted};
    font-size: {text_small}pt;
}}
#Mono {{
    font-family: {mono};
    color: {text_muted};
    font-size: {text_small}pt;
}}

/* ------------------------------------------------------------------ cards */
/* Cards are separated from the page by tone, not by a drawn box: an outline
   around every panel made the screen read as a wireframe. The canvas is a
   step darker (or greyer) than the card, which is what does the work. */
#Card, #StatCard {{
    background: {surface};
    border: none;
    border-radius: {radius_lg}px;
}}
/* A card whose only child already draws its own frame (a table or an empty
   state) must not draw a second one around it. */
#Card[flush="true"] > QWidget > QFrame#Card,
#Card[flush="true"] QFrame#Card {{
    border: none;
    background: transparent;
}}
#StatCard[tone="danger"] {{
    border-color: {danger};
    background: {danger_soft};
}}

/* Compact metric strip: four numbers on one line instead of four tall cards. */
#MetricStrip {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {radius_lg}px;
}}
#Metric {{
    background: transparent;
    border: none;
    border-radius: {radius}px;
    padding: 6px 14px;
}}
#Metric:hover {{ background: {surface_hover}; }}
#MetricValue {{
    font-size: 19pt;
    font-weight: 600;
    color: {text};
}}
#MetricValue[tone="danger"]  {{ color: {danger}; }}
#MetricValue[tone="warning"] {{ color: {warning}; }}
#MetricValue[tone="accent"]  {{ color: {accent}; }}
#MetricLabel {{
    color: {text_muted};
    font-size: {text_caption}pt;
    font-weight: 600;
    letter-spacing: 0.7px;
}}
#MetricDivider {{ background: {divider}; max-width: 1px; min-width: 1px; }}
#StatCard[tone="accent"] {{
    border-color: {accent_border};
}}
#StatValue {{
    font-size: {text_metric}pt;
    font-weight: 600;
    color: {text};
}}
#StatValue[tone="danger"] {{ color: {danger}; }}
#StatValue[tone="warning"] {{ color: {warning}; }}
#StatLabel {{
    color: {text_muted};
    font-size: {text_caption}pt;
    font-weight: 600;
    letter-spacing: 0.7px;
}}
#StatCaption {{
    color: {text_faint};
    font-size: {text_caption}pt;
}}
/* A card title labels a section; it should not compete with the content
   inside it, so it is a step smaller and quieter than the page title.
   Not uppercased: Qt has no text-transform, and doing it in CSS would get
   Turkish wrong anyway ("İ"). */
#CardTitle {{
    font-size: {text_small}pt;
    font-weight: 700;
    letter-spacing: 0.3px;
    color: {text_muted};
}}

/* ------------------------------------------------------------------ badges */
/* The update strip sits above the page, not over it: an accent left edge and
   a tinted ground mark it as the shell speaking rather than the page. */
#UpdateBanner {{
    background: {surface_alt};
    border: none;
    border-left: 3px solid {accent};
    border-bottom: 1px solid {border};
}}
#UpdateBanner QProgressBar {{
    border: 1px solid {border};
    border-radius: {radius_sm}px;
    background: {surface};
    height: 16px;
    font-size: {text_caption}pt;
    color: {text_muted};
}}
#UpdateBanner QProgressBar::chunk {{
    background: {accent};
    border-radius: {radius_sm}px;
}}

/* Filled rather than outlined: a row of bordered pills fights the text it is
   meant to annotate. The tint carries the meaning, the border added noise. */
#Badge {{
    border-radius: {radius_sm}px;
    padding: 3px 8px;
    font-size: {text_caption}pt;
    font-weight: 600;
    background: {surface_alt};
    color: {text_muted};
    border: none;
}}
#Badge[tone="accent"]  {{ background: {accent_soft};  color: {accent};  }}
#Badge[tone="success"] {{ background: {success_soft}; color: {success}; }}
#Badge[tone="warning"] {{ background: {warning_soft}; color: {warning}; }}
#Badge[tone="danger"]  {{ background: {danger_soft};  color: {danger};  }}
#Badge[tone="info"]    {{ background: {info_soft};    color: {info};    border-color: {info}; }}

#Dot {{ font-size: {text_body}pt; }}

/* ------------------------------------------------------------------ buttons */
QPushButton {{
    background: {surface_alt};
    border: 1px solid {border_strong};
    border-radius: {radius}px;
    color: {text};
    padding: 4px 13px;
    min-height: {control_height}px;
    max-height: {control_height}px;
}}
QPushButton:hover  {{ background: {surface_hover}; }}
QPushButton:pressed {{ background: {surface_active}; }}
QPushButton:disabled {{ color: {text_faint}; background: {surface}; border-color: {border}; }}

QPushButton[variant="primary"] {{
    background: {accent};
    border: 1px solid {accent};
    color: {text_on_accent};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover   {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {accent_pressed}; }}
QPushButton[variant="primary"]:disabled {{ background: {surface_alt}; border-color: {border}; color: {text_faint}; }}

QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {text_muted};
}}
QPushButton[variant="ghost"]:hover {{ background: {surface_hover}; color: {text}; }}

QPushButton[variant="subtle"] {{
    background: transparent;
    border: 1px solid {border};
    color: {text_muted};
}}
QPushButton[variant="subtle"]:hover {{ background: {surface_hover}; color: {text}; }}
/* Checkable toolbar buttons (bold, italic, grid snap) must show their state. */
QPushButton[variant="subtle"]:checked {{
    background: {accent_soft};
    border-color: {accent};
    color: {text};
}}

QPushButton[variant="danger"] {{
    background: transparent;
    border: 1px solid {danger};
    color: {danger};
}}
QPushButton[variant="danger"]:hover {{ background: {danger_soft}; }}

QPushButton:focus {{ border: 1px solid {accent}; }}

/* ------------------------------------------------------------------ inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDateEdit, QTimeEdit, QComboBox {{
    background: {surface};
    border: 1px solid {border_strong};
    border-radius: {radius}px;
    color: {text};
    padding: 3px 9px;
    min-height: {control_height}px;
    max-height: {control_height}px;
    selection-background-color: {accent};
    selection-color: {text_on_accent};
}}
QLineEdit:hover, QSpinBox:hover, QDateEdit:hover, QTimeEdit:hover, QComboBox:hover {{
    border-color: {accent_border};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QComboBox:focus {{
    border-color: {accent};
}}
QLineEdit:disabled, QSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled, QComboBox:disabled {{
    color: {text_faint};
    background: {surface_alt};
}}
QLineEdit[state="invalid"], QComboBox[state="invalid"], QDateEdit[state="invalid"] {{
    border-color: {danger};
}}
QTextEdit, QPlainTextEdit {{ padding: 7px 9px; max-height: none; }}

QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({asset_chevron_down}); width: 14px; height: 14px; }}

/* A QDateEdit with a calendar popup draws a drop-down, not spin buttons. */
QDateEdit::drop-down {{ border: none; width: 24px; }}
QDateEdit::drop-down:!editable {{ border: none; }}
QDateEdit[calendarPopup="true"]::down-arrow {{
    image: url({asset_chevron_down}); width: 14px; height: 14px;
}}
QComboBox QAbstractItemView {{
    background: {overlay};
    border: 1px solid {border_strong};
    border-radius: {radius}px;
    color: {text};
    padding: 4px;
    selection-background-color: {accent_soft};
    selection-color: {text};
    outline: none;
}}

QSpinBox::up-button, QSpinBox::down-button,
QDateEdit::up-button, QDateEdit::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{
    background: transparent;
    border: none;
    width: 18px;
}}
QSpinBox::up-arrow, QDateEdit::up-arrow, QTimeEdit::up-arrow {{
    image: url({asset_chevron_up}); width: 11px; height: 11px;
}}
QSpinBox::down-arrow, QDateEdit::down-arrow, QTimeEdit::down-arrow {{
    image: url({asset_chevron_down}); width: 11px; height: 11px;
}}

QCheckBox, QRadioButton {{ color: {text}; spacing: 8px; padding: 3px 0; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {border_strong};
    background: {surface};
}}
QCheckBox::indicator {{ border-radius: {radius_sm}px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: url({asset_check});
}}
QRadioButton::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: url({asset_dot});
}}
QCheckBox::indicator:disabled {{ background: {surface_alt}; border-color: {border}; }}

/* ------------------------------------------------------------------ tables */
QTableView, QTableWidget {{
    background: {surface};
    alternate-background-color: {surface_alt};
    /* The table already sits inside a card; a second frame doubles the box. */
    border: none;
    border-radius: {radius_lg}px;
    gridline-color: transparent;
    color: {text};
    selection-background-color: {accent_soft};
    selection-color: {text};
}}
/* No border-bottom here: a full-bleed rule from edge to edge makes a dense
   table look boxed in. The separator is drawn by AccentRowDelegate, inset
   from both ends. */
QTableView::item, QTableWidget::item {{
    border: none;
    padding: 0px 10px;
}}
/* Date-range separator inside a list ("BU HAFTA", "EKİM 2026"). */
#GroupRow {{
    background: {surface_alt};
    color: {text_faint};
    font-size: {text_caption}pt;
    font-weight: 700;
    letter-spacing: 1.1px;
    padding-left: 12px;
}}
QTableView::item:selected, QTableWidget::item:selected {{
    background: {selected};
    color: {text};
}}
/* Row hover is painted by AccentRowDelegate: a per-cell rule highlighted
   one lone cell under the cursor, which read as a rendering fault. */

QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {surface_alt};
    color: {text_muted};
    border: none;
    border-bottom: 1px solid {border};
    padding: 7px 10px;
    font-size: {text_caption}pt;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QHeaderView::section:first {{ border-top-left-radius: {radius_lg}px; }}
QHeaderView::section:last {{ border-top-right-radius: {radius_lg}px; }}
QTableCornerButton::section {{ background: {surface_alt}; border: none; }}

/* ------------------------------------------------------------- calendar page */
#DayHeading {{
    color: {text_faint};
    font-size: {text_caption}pt;
    font-weight: 600;
    letter-spacing: 0.6px;
    padding: 2px 0;
}}
#DayHeading[weekend="true"] {{ color: {warning}; }}

#DayCell {{
    background: {surface};
    border: 1px solid {divider};
    border-radius: {radius}px;
}}
#DayCell[outside="true"] {{ background: {surface_alt}; border-color: {surface_alt}; }}
#DayCell[weekend="true"] {{ background: {surface_alt}; }}
#DayCell[holiday="true"] {{ border-color: {warning}; }}
/* The load lives in the count badge, not in a background tint: the tint was
   invisible on the light theme. */
#DayCell[today="true"] {{ border-color: {accent}; }}
#DayCell[selected="true"] {{ background: {selected}; border: 2px solid {accent}; }}
#DayCell:hover {{ border-color: {border_strong}; }}

#DayNumber {{
    color: {text};
    font-size: {text_body}pt;
    font-weight: 600;
}}
#DayNumber[outside="true"] {{ color: {text_faint}; }}
/* Today is a filled pill so it stays recognisable when another day is
   selected; selection is the border, today is the badge. */
#DayNumber[today="true"] {{
    background: {accent};
    color: {text_on_accent};
    border-radius: {radius_sm}px;
    padding: 0px 5px;
}}

#DayCount {{
    color: {text_faint};
    font-size: {text_caption}pt;
    font-weight: 600;
    padding: 0px 4px;
}}
#DayCount[busy="true"] {{
    background: {warning_soft};
    color: {warning};
    border-radius: {radius_sm}px;
}}

#DayChip {{
    background: {surface_alt};
    border-left: 3px solid {text_faint};
    border-radius: 2px;
    color: {text_muted};
    font-size: {text_caption}pt;
    padding: 1px 4px;
}}
#DayChip[official="true"] {{ border-left-color: {accent}; }}
#DayHoliday {{
    color: {warning};
    font-size: {text_caption}pt;
    font-weight: 600;
}}
/* ---------------------------------------------------------------- notes */
#NoteCanvas {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: {radius_lg}px;
}}
/* Board tabs sit above the canvas and read as paper tabs, not as buttons. */
#BoardTabs::tab {{
    background: {surface_alt};
    color: {text_muted};
    border: 1px solid {border};
    border-bottom: none;
    border-top-left-radius: {radius_sm}px;
    border-top-right-radius: {radius_sm}px;
    padding: 5px 14px;
    margin-right: 2px;
    font-size: {text_body}pt;
}}
#BoardTabs::tab:selected {{
    background: {surface};
    color: {text};
    border-color: {accent};
}}
#BoardTabs::tab:hover:!selected {{ color: {text}; }}

/* ------------------------------------------------------------- calendar */
/* The date popup is a QCalendarWidget whose day grid is an internal
   QTableView. Without its own rules it inherits the table styling above and
   Qt then paints a check indicator in place of every day number, which is
   why the popup came out as a grid of empty squares. */
QCalendarWidget QWidget {{
    background: {surface};
    color: {text};
}}
QCalendarWidget QAbstractItemView {{
    background: {surface};
    alternate-background-color: {surface};
    border: none;
    border-radius: 0px;
    outline: none;
    color: {text};
    font-size: {text_body}pt;
    selection-background-color: {accent};
    selection-color: #ffffff;
}}
QCalendarWidget QAbstractItemView:disabled {{ color: {text_faint}; }}
QCalendarWidget QAbstractItemView::item {{
    border: none;
    padding: 0px;
    border-radius: {radius_sm}px;
}}
QCalendarWidget QAbstractItemView::item:selected {{
    background: {accent};
    color: #ffffff;
}}
QCalendarWidget QAbstractItemView::item:hover:!selected {{
    background: {surface_hover};
}}
/* Kill the inherited checkbox indicator; a day cell has no check state. */
QCalendarWidget QAbstractItemView::indicator {{
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
    image: none;
}}
QCalendarWidget QTableView {{
    background: {surface};
    border: none;
    border-radius: 0px;
    gridline-color: transparent;
}}
QCalendarWidget QHeaderView::section {{
    background: {surface};
    color: {text_faint};
    border: none;
    padding: 4px 0px;
    font-size: {text_caption}pt;
    font-weight: 600;
}}

/* Navigation bar: month/year buttons and the two arrows. */
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background: {surface_alt};
    border-bottom: 1px solid {border};
    min-height: 34px;
}}
QCalendarWidget QToolButton {{
    background: transparent;
    border: none;
    border-radius: {radius_sm}px;
    color: {text};
    font-size: {text_body}pt;
    font-weight: 600;
    padding: 3px 10px;
    margin: 3px 2px;
}}
QCalendarWidget QToolButton:hover {{ background: {surface_hover}; }}
QCalendarWidget QToolButton:pressed {{ background: {accent_soft}; }}
QCalendarWidget QToolButton::menu-indicator {{ image: none; width: 0px; }}
QCalendarWidget QToolButton#qt_calendar_prevmonth,
QCalendarWidget QToolButton#qt_calendar_nextmonth {{
    qproperty-iconSize: 16px 16px;
    padding: 3px 6px;
}}
/* The year editor that appears when the year button is clicked. Its width is
   pinned in style_calendar(); a min-width here inflated the size hint to 156px
   and left a long gap between the year and its arrows. */
QCalendarWidget QSpinBox {{
    background: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius_sm}px;
    padding: 1px 2px;
}}
/* The editor inside the spin box inherits the global QLineEdit padding, which
   ate 18px of a 34px field and clipped the last digit of the year. */
QCalendarWidget QSpinBox QLineEdit {{
    padding: 0px;
    border: none;
    background: transparent;
}}
/* The month drop-down list. */
QCalendarWidget QMenu {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {radius_sm}px;
    color: {text};
    padding: 4px;
}}
QCalendarWidget QMenu::item {{ padding: 5px 18px; border-radius: {radius_sm}px; }}
QCalendarWidget QMenu::item:selected {{ background: {accent_soft}; color: {text}; }}

/* ------------------------------------------------------------------ lists */
QListWidget, QTreeWidget {{
    background: {surface};
    border: none;
    border-radius: {radius_lg}px;
    padding: 5px;
    color: {text};
}}
/* No vertical padding: these lists are drawn with row widgets whose size hint
   is the row height, so any padding here pushed the widget below its own
   highlight. The row widget carries its own inner spacing instead. The 3px
   left inset is reserved for the selected row's accent bar, so the text does
   not shift when a row is picked. */
QListWidget::item {{
    border-radius: {radius}px;
    padding: 0px 0px 0px 3px;
    margin: 1px 2px;
}}
QListWidget::item:hover {{ background: {surface_hover}; }}
/* The left bar is the same selection language the tables use, and it survives
   the row's own widget being painted on top of the item background. */
QListWidget::item:selected {{
    background: {selected};
    color: {text};
    border-left: 3px solid {accent};
    padding-left: 0px;
}}
QListWidget::item:selected:hover {{ background: {selected}; }}

/* ------------------------------------------------------------------ scrollbars */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 11px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {border_strong}; border-radius: 5px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {text_faint}; }}
QScrollBar:horizontal {{
    background: transparent; height: 11px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {border_strong}; border-radius: 5px; min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: {text_faint}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ------------------------------------------------------------------ menus */
QMenu {{
    background: {overlay};
    border: 1px solid {border_strong};
    border-radius: {radius}px;
    padding: 5px;
    color: {text};
}}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: {radius_sm}px; }}
QMenu::item:selected {{ background: {accent_soft}; }}
QMenu::item:disabled {{ color: {text_faint}; }}
QMenu::separator {{ height: 1px; background: {divider}; margin: 5px 8px; }}

QToolTip {{
    background: {overlay};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: {radius_sm}px;
    padding: 5px 8px;
}}

/* ------------------------------------------------------------------ misc */
QSplitter::handle {{ background: {divider}; }}
QSplitter::handle:horizontal {{ width: 1px; }}

QProgressBar {{
    background: {surface_alt};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}

QGroupBox {{
    border: 1px solid {border};
    border-radius: {radius_lg}px;
    margin-top: 16px;
    padding: {space}px;
    background: {surface};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    color: {text_muted};
    font-weight: 600;
}}

#Separator {{ background: {divider}; max-height: 1px; min-height: 1px; }}

/* A checkbox row must not stretch to 1100px; long forms get a text measure. */
#Measure {{ background: transparent; }}
#SubtleHint {{ color: {text_muted}; font-size: {text_small}pt; }}
#DialogFooter {{ background: {surface_alt}; border-top: 1px solid {border}; }}

QMessageBox {{ background: {surface}; }}
QMessageBox QLabel {{ color: {text}; }}
"""
