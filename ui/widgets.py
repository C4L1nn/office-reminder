"""Reusable building blocks shared by every screen.

Each one is a thin wrapper that sets an object name (or a dynamic property) the
stylesheet knows about, so pages describe structure and never colours.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.formatting import upper_tr
from ui import icons
from ui.theme import tokens


def restyle(widget: QWidget) -> None:
    """Re-evaluate the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


# --------------------------------------------------------------------------- text
def label(text: str = "", role: str = "", *, wrap: bool = False) -> QLabel:
    item = QLabel(text)
    if role:
        item.setObjectName(role)
    item.setWordWrap(wrap)
    return item


def separator(horizontal: bool = True) -> QFrame:
    """A hairline drawn by the stylesheet; QFrame's own line styles are avoided
    because they paint a second, lighter groove on top."""
    line = QFrame()
    line.setObjectName("Separator")
    line.setFrameShape(QFrame.Shape.NoFrame)
    if horizontal:
        line.setFixedHeight(1)
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    else:
        line.setFixedWidth(1)
        line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    return line


# --------------------------------------------------------------------------- buttons
def button(
    text: str,
    variant: str = "default",
    icon_name: str | None = None,
    *,
    tooltip: str = "",
) -> QPushButton:
    item = QPushButton(text)
    item.setProperty("variant", variant)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        colour = tokens().text_on_accent if variant == "primary" else tokens().text_muted
        item.setIcon(icons.icon(icon_name, color=colour))
        item.setIconSize(icons.ICON_SIZE)
    if tooltip:
        item.setToolTip(tooltip)
    return item


def icon_button(icon_name: str, tooltip: str, variant: str = "ghost") -> QPushButton:
    """A square icon-only button.

    `variant` picks the frame: "ghost" for actions floating over content,
    "subtle" for a toolbar, where an unframed glyph does not read as a button
    next to framed neighbours.
    """
    item = QPushButton()
    item.setProperty("variant", variant)
    item.setIcon(icons.icon(icon_name))
    item.setIconSize(icons.ICON_SIZE)
    item.setFixedSize(32, 32)
    item.setToolTip(tooltip)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    return item


# --------------------------------------------------------------------------- badges
class Badge(QLabel):
    """Small status pill. `tone` drives the colour via the stylesheet."""

    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        restyle(self)

    def update_badge(self, text: str, tone: str) -> None:
        self.setText(text)
        self.set_tone(tone)


def status_dot(tone: str) -> QLabel:
    colours = {
        "success": tokens().success,
        "warning": tokens().warning,
        "danger": tokens().danger,
        "neutral": tokens().text_faint,
    }
    dot = QLabel("●")
    dot.setObjectName("Dot")
    dot.setStyleSheet(f"color: {colours.get(tone, tokens().text_faint)};")
    return dot


# --------------------------------------------------------------------------- containers
class Card(QFrame):
    """A surface panel with optional title row."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        t = tokens()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(t.space, t.space_sm, t.space, t.space)
        self._layout.setSpacing(t.space_sm)
        self.header = QHBoxLayout()
        self.header.setSpacing(t.space_sm)
        self.title_label = label(title, "CardTitle")
        self.header.addWidget(self.title_label)
        self.header.addStretch()
        if title:
            self._layout.addLayout(self.header)
        else:
            self.title_label.hide()

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout: QLayout) -> None:
        self._layout.addLayout(layout)

    def add_header_widget(self, widget: QWidget) -> None:
        self.header.addWidget(widget)

    def tighten(self) -> None:
        """Row spacing for a card that holds a list rather than prose."""
        self._layout.setSpacing(tokens().space_xs)


def data_row(children: list[tuple[QWidget, int]]) -> QWidget:
    """One dense line inside a card: no default margins, fixed height.

    A plain QHBoxLayout adds 9px on every side, which turns a 30px line into
    a 48px one and undoes the density this pass is about.
    """
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(tokens().space_sm)
    for widget, stretch in children:
        layout.addWidget(widget, stretch)
    holder.setFixedHeight(tokens().row_height - 6)
    return holder


class StatCard(QFrame):
    """Dashboard KPI: label, big number, one line of context."""

    clicked = Signal()

    def __init__(
        self,
        caption: str,
        description: str,
        icon_name: str,
        tone: str = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        self._tone = tone
        t = tokens()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.space_lg, t.space, t.space_lg, t.space)
        outer.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(t.space_sm)
        self.caption = label(upper_tr(caption), "StatLabel")
        top.addWidget(self.caption)
        top.addStretch()
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon_name, 17, self._accent_colour()))
        top.addWidget(glyph)
        outer.addLayout(top)

        self.value = label("0", "StatValue")
        outer.addWidget(self.value)

        self.description = label(description, "StatCaption", wrap=True)
        outer.addWidget(self.description)

        self.setMinimumWidth(168)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _accent_colour(self) -> str:
        t = tokens()
        return {"danger": t.danger, "warning": t.warning, "accent": t.accent}.get(self._tone, t.text_faint)

    def set_value(self, value: int, *, alert: bool = False) -> None:
        self.value.setText(str(value))
        tone = self._tone if not alert else "danger"
        self.value.setProperty("tone", tone if tone in ("danger", "warning") else "")
        self.setProperty("tone", tone if alert else ("accent" if self._tone == "accent" else ""))
        restyle(self.value)
        restyle(self)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class EmptyState(QWidget):
    """Shown instead of a blank table so an empty screen still explains itself."""

    action_clicked = Signal()

    def __init__(
        self,
        title: str,
        body: str,
        icon_name: str = "list",
        action: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        t = tokens()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(t.space_xl, t.space_xl, t.space_xl, t.space_xl)
        layout.setSpacing(t.space_sm)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon_name, 30, tokens().text_faint))
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(glyph)

        self._heading = label(title, "SectionTitle")
        self._heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._heading)

        self._body = label(body, "Muted", wrap=True)
        self._body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # A centred layout hands a child its size hint, and a wrapping label's
        # hint collapses to about 175px — narrow enough to cut the sentence off.
        # The minimum pins a readable measure; the maximum stops a long line.
        self._body.setMinimumWidth(340)
        self._body.setMaximumWidth(420)
        layout.addWidget(self._body, alignment=Qt.AlignmentFlag.AlignCenter)

        if action:
            layout.addSpacing(t.space_sm)
            self.action = button(action, "primary", "plus")
            self.action.clicked.connect(self.action_clicked.emit)
            layout.addWidget(self.action, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_text(self, title: str, body: str) -> None:
        """Reword the empty state, e.g. when a filter is what emptied the list."""
        self._heading.setText(title)
        self._body.setText(body)


class TableStack(QWidget):
    """A table that swaps itself for an empty state when there are no rows."""

    def __init__(
        self,
        headers: list[str],
        empty_title: str,
        empty_body: str,
        empty_action: str | None = None,
        empty_icon: str = "list",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QStackedLayout

        self.table = build_table(headers)
        self.empty = EmptyState(empty_title, empty_body, empty_icon, empty_action)
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self.table)

        wrapper = QFrame()
        wrapper.setObjectName("Card")
        inner = QVBoxLayout(wrapper)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(self.empty)
        self._stack.addWidget(wrapper)

    def show_rows(self, count: int) -> None:
        self._stack.setCurrentIndex(0 if count else 1)


# --------------------------------------------------------------------------- metrics
class Metric(QFrame):
    """One number in the compact strip."""

    clicked = Signal()

    def __init__(self, caption: str, tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Metric")
        self._tone = tone
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.value = label("0", "MetricValue")
        self.caption = label(upper_tr(caption), "MetricLabel")
        layout.addWidget(self.value)
        layout.addWidget(self.caption)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_value(self, value: int, *, alert: bool = False) -> None:
        self.value.setText(str(value))
        tone = "danger" if alert else self._tone
        self.value.setProperty("tone", tone if tone != "neutral" else "")
        restyle(self.value)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class MetricStrip(QFrame):
    """Four counters on one line.

    Replaces four 91px cards that each carried a single number: the same
    information in roughly a third of the vertical space, which is what the
    list below actually needs.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MetricStrip")
        t = tokens()
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(t.space_sm, t.space_sm, t.space_sm, t.space_sm)
        self._layout.setSpacing(0)
        self._metrics: dict[str, Metric] = {}

    def add(self, key: str, caption: str, tone: str = "neutral") -> Metric:
        if self._metrics:
            divider = QFrame()
            divider.setObjectName("MetricDivider")
            divider.setFixedWidth(1)
            self._layout.addWidget(divider)
        metric = Metric(caption, tone)
        self._metrics[key] = metric
        self._layout.addWidget(metric, 1)
        return metric

    def add_trailing(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def __getitem__(self, key: str) -> Metric:
        return self._metrics[key]


# --------------------------------------------------------------------------- tables
class AccentRowDelegate(QStyledItemDelegate):
    """Row separators, and a colour bar down the left edge of flagged rows.

    An overdue item should be recognisable from the row itself, not only from a
    badge at the far right of the screen. The separator lives here rather than
    in the stylesheet so it can be inset from both ends: a rule running the
    full width of the table boxes a dense list in.
    """

    BAR_WIDTH = 3
    #: How far the separator stops short of each edge.
    INSET = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[int, str] = {}
        self._spanned: set[int] = set()
        self._hovered = -1

    def set_rows(self, rows: dict[int, str]) -> None:
        self._rows = rows

    def set_spanned_rows(self, rows: set[int]) -> None:
        """Rows that are one wide cell (a date heading) take no separator."""
        self._spanned = set(rows)

    def set_hovered_row(self, row: int) -> None:
        """Qt hovers one cell; a table of records should hover the whole row."""
        if row != self._hovered:
            self._hovered = row
            view = self.parent()
            if hasattr(view, "viewport"):
                view.viewport().update()

    def paint(self, painter: QPainter, option, index) -> None:
        if index.row() == self._hovered and index.row() not in self._spanned:
            painter.fillRect(option.rect, QColor(tokens().surface_hover))
        super().paint(painter, option, index)
        self._paint_separator(painter, option, index)
        if index.column() != 0:
            return
        tone = self._rows.get(index.row())
        if not tone:
            return
        t = tokens()
        colour = {"danger": t.danger, "warning": t.warning, "accent": t.accent}.get(tone)
        if colour is None:
            return
        painter.save()
        painter.fillRect(
            QRect(option.rect.left(), option.rect.top(), self.BAR_WIDTH, option.rect.height()),
            QColor(colour),
        )
        painter.restore()

    def _paint_separator(self, painter: QPainter, option, index) -> None:
        """A hairline under the row, stopping short of both ends."""
        if index.row() in self._spanned:
            return
        view = self.parent()
        columns = view.columnCount() if hasattr(view, "columnCount") else 0
        left = option.rect.left()
        right = option.rect.right()
        if index.column() == 0:
            left += self.INSET
        if columns and index.column() == columns - 1:
            right -= self.INSET

        painter.save()
        # `divider` is only a few values away from the card on the light theme
        # and disappeared entirely; the row rule needs `border` to register.
        painter.setPen(QPen(QColor(tokens().border), 1))
        painter.drawLine(left, option.rect.bottom(), right, option.rect.bottom())
        painter.restore()


def add_group_row(table: QTableWidget, text: str) -> int:
    """Insert a full-width separator row such as "BU HAFTA"."""
    row = table.rowCount()
    table.insertRow(row)
    table.setSpan(row, 0, 1, table.columnCount())
    holder = QLabel(upper_tr(text))
    holder.setObjectName("GroupRow")
    holder.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    table.setCellWidget(row, 0, holder)
    table.setRowHeight(row, tokens().group_height)
    item = QTableWidgetItem()
    item.setFlags(Qt.ItemFlag.NoItemFlags)
    table.setItem(row, 0, item)
    return row


class ElidedLabel(QLabel):
    """A label that ends in an ellipsis instead of being cut mid-word.

    Qt has no text-overflow, so a name too long for its column is simply
    chopped and looks like a rendering fault rather than a shortened name.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full = text
        self.setMinimumWidth(24)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        super().setText(text)
        self.update()

    def full_text(self) -> str:
        return self._full

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QPainter

        painter = QPainter(self)
        # Honour the stylesheet colour (DayChip, Muted, ...); without this the
        # text is always pure black, which vanishes on a dark surface.
        painter.setPen(self.palette().color(self.foregroundRole()))
        metrics = painter.fontMetrics()
        rect = self.contentsRect()
        elided = metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, int(self.alignment()), elided)
        painter.end()


class DistributionStrip(QWidget):
    """One slim bar per day for the next month: where the work piles up.

    Four totals say how much is coming; they do not say that eleven of it lands
    on the same Monday. The strip is drawn rather than charted because the app
    ships no plotting library and one row of bars needs none.
    """

    DAYS = 30
    BAR_GAP = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DistributionStrip")
        self.setFixedHeight(58)
        self.setMouseTracking(True)
        self._counts: list[tuple[object, int]] = []

    def set_counts(self, counts: list[tuple[object, int]]) -> None:
        """(date, how many fall due that day), oldest first."""
        self._counts = list(counts)[: self.DAYS]
        self.update()

    def _bar_width(self) -> float:
        if not self._counts:
            return 0.0
        return (self.width() - self.BAR_GAP * (len(self._counts) - 1)) / len(self._counts)

    def paintEvent(self, event) -> None:  # noqa: N802
        from datetime import date as _date

        from PySide6.QtGui import QPainter

        if not self._counts:
            return
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        today = _date.today()
        peak = max((count for _day, count in self._counts), default=0) or 1
        width = self._bar_width()
        # Room for the date labels under the bars.
        chart_height = self.height() - 14

        # A rule under the bars: without it the sparse days read as dashes
        # floating at random heights instead of a distribution.
        painter.setBrush(QColor(t.border))
        painter.drawRect(QRectF(0, chart_height - 1, self.width(), 1))

        for index, (day, count) in enumerate(self._counts):
            x = index * (width + self.BAR_GAP)
            if count:
                height = max(4.0, chart_height * (count / peak))
            else:
                height = 2.0
            if count == 0:
                colour = QColor(t.border_strong)
            elif day < today:
                colour = QColor(t.danger)
            elif day == today:
                colour = QColor(t.warning)
            else:
                colour = QColor(t.accent)
            painter.setBrush(colour)
            painter.drawRoundedRect(
                QRectF(x, chart_height - height, max(width, 1.0), height), 2, 2
            )

        painter.setPen(QColor(t.text_faint))
        font = painter.font()
        font.setPointSizeF(7.5)
        painter.setFont(font)
        first, last = self._counts[0][0], self._counts[-1][0]
        baseline = QRectF(0, chart_height + 1, self.width(), 13)
        painter.drawText(baseline, Qt.AlignmentFlag.AlignLeft, first.strftime("%d.%m"))
        painter.drawText(baseline, Qt.AlignmentFlag.AlignRight, last.strftime("%d.%m"))
        painter.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """The bar under the cursor names its own day and count."""
        width = self._bar_width()
        if not width:
            return
        index = int(event.position().x() // (width + self.BAR_GAP))
        if 0 <= index < len(self._counts):
            day, count = self._counts[index]
            self.setToolTip(f"{day.strftime('%d.%m.%Y')} · {count} kayıt")
        else:
            self.setToolTip("")


class StickyGroupHeader(QLabel):
    """Keeps the current date group pinned while the list scrolls.

    A long list scrolls its "BU AY" heading away within a few rows, and the
    reader loses track of which window the dates belong to. This pins a copy of
    the heading to the top of the viewport, and hides itself again as soon as
    the real heading is back on screen.
    """

    def __init__(self, table: QTableWidget) -> None:
        super().__init__(table.viewport())
        self.setObjectName("GroupRow")
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.table = table
        self._groups: dict[int, str] = {}
        self.hide()

        table.verticalScrollBar().valueChanged.connect(self.follow)
        table.viewport().installEventFilter(self)

    def set_groups(self, groups: dict[int, str]) -> None:
        """Row index -> heading text, for the rows that carry a heading."""
        self._groups = dict(groups)
        self.follow()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.table.viewport() and event.type() == event.Type.Resize:
            self.follow()
        return super().eventFilter(watched, event)

    def follow(self) -> None:
        if not self._groups:
            self.hide()
            return
        top = self.table.rowAt(0)
        if top < 0:
            self.hide()
            return
        # The heading that governs the first visible row.
        current = None
        for row in sorted(self._groups):
            if row <= top:
                current = row
            else:
                break
        if current is None or current == top:
            # The real heading is on screen; a second copy would be noise.
            self.hide()
            return
        self.setText(self._groups[current])
        self.setGeometry(0, 0, self.table.viewport().width(), tokens().group_height)
        self.raise_()
        self.show()


def build_table(headers: list[str]) -> QTableWidget:
    """A table configured for dense, readable, keyboard-friendly rows."""
    t = tokens()
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(t.row_height)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setMinimumSectionSize(64)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    return table


def stretch_column(table: QTableWidget, index: int) -> None:
    table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)


def set_column_widths(table: QTableWidget, widths: dict[int, int]) -> None:
    for index, width in widths.items():
        table.setColumnWidth(index, width)


def configure_columns(table: QTableWidget, spec: list[int | None]) -> None:
    """Size table columns so text columns keep room at the smallest window.

    Each entry is either a fixed pixel width or ``None`` for a flexible column.
    Flexible columns share the remaining width equally, which keeps a long
    obligation title readable instead of letting fixed columns squeeze it down
    to a few characters when the window is at its minimum size.
    """
    header = table.horizontalHeader()
    header.setMinimumSectionSize(72)
    for index, width in enumerate(spec):
        if width is None:
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
            table.setColumnWidth(index, width)
    header.setStretchLastSection(False)


def align_headers(table: QTableWidget, center: tuple[int, ...] = ()) -> None:
    """Match each header to its cells: centred over centred columns, left over text.

    Qt centres every header by default, which floats "Şirket" in the middle of
    a column whose values are left aligned.
    """
    for index in range(table.columnCount()):
        item = table.horizontalHeaderItem(index)
        if item is None:
            continue
        if index in center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )


def row_widget(*widgets: QWidget, spacing: int | None = None, margins: tuple = (0, 0, 0, 0)) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing if spacing is not None else tokens().space_sm)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch()
    return holder


def fixed_cell(widget: QWidget, width: int, align: Qt.AlignmentFlag | None = None) -> QWidget:
    """Put a hugging widget (a badge) into a fixed-width, aligned column."""
    holder = QWidget()
    holder.setFixedWidth(width)
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setAlignment(align or (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
    layout.addWidget(widget)
    return holder


def cell_widget(widget: QWidget, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter) -> QWidget:
    """Centre a badge (or any widget) inside a table cell."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(8, 0, 8, 0)
    layout.setAlignment(align)
    layout.addWidget(widget)
    return holder


def list_row(primary: str, secondary: str = "", trailing: str = "", muted: bool = False) -> QWidget:
    """A two-line entry for the master lists.

    A list showing only a name wastes most of its width; the second line is
    where the plate's make/model or the company's tax number belongs.
    """
    t = tokens()
    holder = QWidget()
    outer = QHBoxLayout(holder)
    outer.setContentsMargins(2, 4, 2, 4)
    outer.setSpacing(t.space_sm)

    column = QVBoxLayout()
    column.setSpacing(1)
    title = label(primary)
    if muted:
        title.setStyleSheet(f"color: {t.text_faint};")
    column.addWidget(title)
    if secondary:
        column.addWidget(label(secondary, "Caption"))
    outer.addLayout(column, 1)

    if trailing:
        outer.addWidget(label(trailing, "Caption"), 0, Qt.AlignmentFlag.AlignVCenter)

    holder.setFixedHeight(LIST_ROW_TWO_LINE if secondary else LIST_ROW_ONE_LINE)
    return holder


#: Explicit heights, because a list item's size hint is read before its widget
#: has been laid out.
LIST_ROW_ONE_LINE = 32
LIST_ROW_TWO_LINE = 46


def list_row_size(secondary: bool = True) -> QSize:
    return QSize(0, LIST_ROW_TWO_LINE if secondary else LIST_ROW_ONE_LINE)


def metric_row(pairs: list[tuple[str, str]], spacing: int | None = None) -> QWidget:
    """Caption-over-value pairs on one line, evenly spaced and left aligned."""
    t = tokens()
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing if spacing is not None else t.space_xl)
    for caption, value in pairs:
        column = QVBoxLayout()
        column.setSpacing(1)
        column.addWidget(label(caption, "FieldLabel"))
        column.addWidget(label(value, "SectionTitle"))
        cell = QWidget()
        cell.setLayout(column)
        layout.addWidget(cell)
    layout.addStretch()
    return holder


def style_calendar(calendar) -> None:
    """Make a QDateEdit's pop-up calendar match the rest of the app.

    Qt's default calendar shows an ISO week-number column nobody in the office
    uses, and it paints its day text from the palette rather than from the
    stylesheet, so on the dark theme the selection and the weekend columns come
    out almost unreadable. Both have to be set on the widget, not in QSS.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette, QTextCharFormat
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QCalendarWidget,
        QSpinBox,
        QToolButton,
    )

    if calendar is None:
        return
    t = tokens()

    calendar.setVerticalHeaderFormat(
        QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
    )
    calendar.setHorizontalHeaderFormat(
        QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
    )
    calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
    calendar.setGridVisible(False)

    weekday = QTextCharFormat()
    weekday.setForeground(QColor(t.text))
    weekend = QTextCharFormat()
    weekend.setForeground(QColor(t.warning))
    for day in (
        Qt.DayOfWeek.Monday,
        Qt.DayOfWeek.Tuesday,
        Qt.DayOfWeek.Wednesday,
        Qt.DayOfWeek.Thursday,
        Qt.DayOfWeek.Friday,
    ):
        calendar.setWeekdayTextFormat(day, weekday)
    for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
        calendar.setWeekdayTextFormat(day, weekend)

    header = QTextCharFormat()
    header.setForeground(QColor(t.text_faint))
    calendar.setHeaderTextFormat(header)

    # Qt draws the month arrows with its own built-in style icons, which ignore
    # the theme and look nothing like the rest of the app. Swap in our own SVG
    # chevrons, tinted like every other icon.
    from ui import icons

    for name, glyph in (
        ("qt_calendar_prevmonth", "chevron_left"),
        ("qt_calendar_nextmonth", "chevron_right"),
    ):
        nav = calendar.findChild(QToolButton, name)
        if nav is not None:
            nav.setIcon(icons.icon(glyph, 16, t.text))
            nav.setIconSize(QSize(16, 16))

    # The year editor takes its width from the styled size hint, which is far
    # wider than four digits need; left alone it opened as a long empty box and
    # pushed the next-month arrow to the edge. Size it to its actual content.
    year_edit = calendar.findChild(QSpinBox, "qt_calendar_yearedit")
    if year_edit is not None:
        digits = year_edit.fontMetrics().horizontalAdvance("0000")
        year_edit.setFixedWidth(digits + 40)  # digits, arrows and the border
        year_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)

    palette = calendar.palette()
    palette.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Base, QColor(t.surface))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(t.surface))
    palette.setColor(QPalette.ColorRole.Text, QColor(t.text))
    calendar.setPalette(palette)

    # The day grid is a private view that keeps its own palette, so the
    # selection colour has to be set on it too or the selected day stays a
    # barely visible dark square.
    view = calendar.findChild(QAbstractItemView)
    if view is not None:
        view.setPalette(palette)
        view.setAlternatingRowColors(False)
        # A widget-level sheet is the only one that reliably beats the generic
        # QTableView rule for this private view.
        view.setStyleSheet(
            "QAbstractItemView {"
            f" background: {t.surface};"
            f" alternate-background-color: {t.surface};"
            " border: none; border-radius: 0px; outline: none;"
            f" selection-background-color: {t.accent};"
            " selection-color: #ffffff;"
            "}"
            "QAbstractItemView::item {"
            f" border: none; padding: 0px; border-radius: {t.radius_sm}px;"
            "}"
            "QAbstractItemView::item:selected {"
            f" background: {t.accent}; color: #ffffff;"
            "}"
            "QAbstractItemView::item:hover:!selected {"
            f" background: {t.surface_hover};"
            "}"
        )


class _ListPlaceholder(QLabel):
    """A hint centred over an empty master list.

    Qt has no placeholder for QListWidget, and assigning `paintEvent` on the
    viewport from Python does not override the C++ virtual, so the hint is an
    overlay label that follows the viewport and hides as soon as a row exists.
    """

    def __init__(self, listing: QListWidget, text: str) -> None:
        super().__init__(text, listing.viewport())
        self.setObjectName("ListPlaceholder")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.listing = listing
        listing.viewport().installEventFilter(self)
        listing.model().rowsInserted.connect(self.follow)
        listing.model().rowsRemoved.connect(self.follow)
        listing.model().modelReset.connect(self.follow)
        self.follow()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.listing.viewport() and event.type() == event.Type.Resize:
            self.follow()
        return super().eventFilter(watched, event)

    def follow(self) -> None:
        rect = self.listing.viewport().rect().adjusted(16, 0, -16, 0)
        self.setGeometry(rect)
        self.setVisible(self.listing.count() == 0)


def set_list_placeholder(listing, text: str) -> QLabel | None:
    """Show `text` while `listing` is empty."""
    if not isinstance(listing, QListWidget):
        return None
    return _ListPlaceholder(listing, text)
