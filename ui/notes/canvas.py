"""The board surface the notes live on.

A `QGraphicsView` gives free positioning, stacking order, panning and zooming
for nothing; laying widgets out at absolute coordinates inside a scroll area
would have to re-implement all four.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFont,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QMenu

from services.note_service import GRID, snap
from ui.notes.note_item import NoteItem
from ui.theme import tokens

#: The furthest a note may be dragged. The scene itself is sized to the notes
#: plus one screen of room, so an almost empty board does not show scrollbars
#: for 3000px of blank paper it will never use.
BOARD_WIDTH = 3000.0
BOARD_HEIGHT = 2200.0
#: Slack kept beyond the last note, so there is always somewhere to drag to.
BOARD_SLACK = 400.0

MIN_ZOOM = 0.5
MAX_ZOOM = 2.0


class NoteCanvas(QGraphicsView):
    note_moved = Signal(int, float, float, float, float)
    note_edited = Signal(int, str, str)
    note_focused = Signal(int)
    note_deleted = Signal(int)
    raise_requested = Signal(int)
    lower_requested = Signal(int)
    colour_requested = Signal(int, str)
    create_requested = Signal(float, float)
    reminder_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("NoteCanvas")
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(QRectF(0, 0, BOARD_WIDTH, BOARD_HEIGHT))
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate
        )
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        # Anchor the board's top-left corner; the default centres the scene and
        # opens the view in the middle of an empty 3000x2200 board.
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.snap_enabled = True
        self._items: dict[int, NoteItem] = {}
        self._zoom = 1.0
        self._fit_scene()

    # ------------------------------------------------------------------ items
    def clear_notes(self) -> None:
        for item in list(self._items.values()):
            self._scene.removeItem(item)
        self._items.clear()

    def load(self, notes) -> None:
        self.clear_notes()
        for note in notes:
            self.add_note(note)
        self._fit_scene()
        self.show_origin()

    def _fit_scene(self) -> None:
        """Shrink the scene to the notes plus a screen of slack.

        The scene used to be a fixed 3000x2200 whatever it held, so an empty
        board still showed a long horizontal scrollbar.
        """
        viewport = self.viewport().size()
        used = self._scene.itemsBoundingRect() if self._items else QRectF()
        # Slack only past the last note; an empty board needs none. The two
        # pixels come off the viewport because the view keeps a 1px margin on
        # each side and would otherwise show a scrollbar for it.
        needed_w = used.right() + BOARD_SLACK if self._items else 0.0
        needed_h = used.bottom() + BOARD_SLACK if self._items else 0.0
        width = min(max(needed_w, viewport.width() - 2), BOARD_WIDTH)
        height = min(max(needed_h, viewport.height() - 2), BOARD_HEIGHT)
        self._scene.setSceneRect(QRectF(0, 0, width, height))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_scene()

    def show_origin(self) -> None:
        """Scroll to the top-left of the board.

        Deferred to the next event-loop turn: called straight from `load()` the
        scrollbars have no range yet, so setting them to their minimum does
        nothing and the view stays centred on empty board.
        """
        def scroll() -> None:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().minimum())
            self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())

        scroll()
        QTimer.singleShot(0, scroll)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.show_origin()

    def add_note(self, note) -> NoteItem:
        item = NoteItem(note)
        item.setZValue(note.z)
        item.geometry_changed.connect(self._on_geometry)
        item.content_changed.connect(self.note_edited)
        item.focus_gained.connect(self.note_focused)
        self._scene.addItem(item)
        self._items[note.id] = item
        self._fit_scene()
        self.viewport().update()
        return item

    def item(self, note_id: int) -> NoteItem | None:
        return self._items.get(note_id)

    def remove_note(self, note_id: int) -> None:
        item = self._items.pop(note_id, None)
        if item is not None:
            self._scene.removeItem(item)
            self._fit_scene()
            self.viewport().update()

    def apply_geometry(self, notes) -> None:
        """Push server-side geometry (an arrangement) back onto the items."""
        for note in notes:
            item = self._items.get(note.id)
            if item is None:
                continue
            item.setPos(note.x, note.y)
            item.set_size(note.width, note.height)

    def apply_order(self, notes) -> None:
        for note in notes:
            item = self._items.get(note.id)
            if item is not None:
                item.setZValue(note.z)

    # -------------------------------------------------------------- behaviour
    def _on_geometry(
        self, note_id: int, x: float, y: float, width: float, height: float
    ) -> None:
        item = self._items.get(note_id)
        if item is None:
            return
        x = max(0.0, min(snap(x, self.snap_enabled), BOARD_WIDTH - width))
        y = max(0.0, min(snap(y, self.snap_enabled), BOARD_HEIGHT - height))
        if (x, y) != (item.pos().x(), item.pos().y()):
            item.setPos(x, y)
        self._fit_scene()
        self.note_moved.emit(note_id, x, y, width, height)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        t = tokens()
        painter.fillRect(rect, QColor(t.surface_alt))
        if not self.snap_enabled:
            return
        # A faint dot grid: enough to read alignment, not enough to compete
        # with the notes themselves.
        dot = QColor(t.text_faint)
        dot.setAlpha(70)
        painter.setPen(QPen(dot, 2))
        step = GRID * 4
        left = int(rect.left() - rect.left() % step)
        top = int(rect.top() - rect.top() % step)
        points = [
            QPointF(x, y)
            for x in range(left, int(rect.right()), int(step))
            for y in range(top, int(rect.bottom()), int(step))
        ]
        if points:
            painter.drawPoints(points)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        """An empty board explains itself instead of showing a bare grid."""
        if self._items:
            return
        t = tokens()
        viewport = self.mapToScene(self.viewport().rect()).boundingRect()

        title = QFont()
        title.setPointSizeF(13.0)
        title.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title)
        painter.setPen(QColor(t.text_muted))
        painter.drawText(
            viewport.adjusted(0, -18, 0, -18),
            Qt.AlignmentFlag.AlignCenter,
            "Bu sayfada henüz not yok",
        )

        body = QFont()
        body.setPointSizeF(10.0)
        painter.setFont(body)
        painter.setPen(QColor(t.text_faint))
        painter.drawText(
            viewport.adjusted(0, 14, 0, 14),
            Qt.AlignmentFlag.AlignCenter,
            "Boş alana çift tıklayın veya “Yeni Not” düğmesini kullanın.",
        )

    # ---------------------------------------------------------------- printing
    def board_rect(self) -> QRectF:
        """The area the notes actually occupy, with a small margin."""
        if not self._items:
            return QRectF(0, 0, 0, 0)
        return self._scene.itemsBoundingRect().adjusted(-12, -12, 12, 12)

    def render_board(self, painter: QPainter, target: QRectF) -> None:
        """Paint the board into `target`, exactly as it is arranged on screen.

        The note text is drawn from each document rather than by rendering the
        embedded editors: `QGraphicsScene.render()` lays a proxy widget's text
        out for the target device and then clips it to a fraction of its
        height, which silently cut long notes out of the PDF. Drawing the
        document also means no caret and no scrollbars to hide.

        The light palette is forced for the duration: a dark-theme board on
        white paper is unreadable.
        """
        from ui.notes.note_item import HEADER, PAD
        from ui.theme import LIGHT, note_paper, palette_override

        source = self.board_rect()
        if source.isEmpty():
            return
        scale = target.width() / source.width() if source.width() else 1.0

        try:
            with palette_override(LIGHT):
                for item in self._items.values():
                    item.apply_colour(item.colour_key)
                    item.proxy.setVisible(False)
                self._scene.render(painter, target, source)

                for item in sorted(self._items.values(), key=lambda i: i.zValue()):
                    width, height = item.size()
                    body_w = max(width - 2 * PAD, 10.0)
                    body_h = max(height - HEADER - PAD, 10.0)
                    painter.save()
                    painter.translate(
                        target.x() + (item.pos().x() + PAD - source.x()) * scale,
                        target.y() + (item.pos().y() + HEADER - source.y()) * scale,
                    )
                    painter.scale(scale, scale)

                    # The document takes its default text colour from the paint
                    # context's palette, not from the painter's pen and not from
                    # the widget stylesheet, so the ink is set here. The clip
                    # cuts an overflowing note off on the page the same way it
                    # is cut off on screen.
                    context = QAbstractTextDocumentLayout.PaintContext()
                    context.palette.setColor(
                        QPalette.ColorRole.Text, QColor(note_paper(item.colour_key).ink)
                    )
                    context.clip = QRectF(0, 0, body_w, body_h)
                    painter.setClipRect(context.clip)
                    item.body.document().documentLayout().draw(painter, context)
                    painter.restore()
        finally:
            for item in self._items.values():
                item.proxy.setVisible(True)
                item.apply_colour(item.colour_key)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            target = max(MIN_ZOOM, min(self._zoom * factor, MAX_ZOOM))
            factor = target / self._zoom
            self._zoom = target
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def reset_zoom(self) -> None:
        if self._zoom != 1.0:
            self.scale(1.0 / self._zoom, 1.0 / self._zoom)
            self._zoom = 1.0

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.itemAt(event.pos()) is None:
            point = self.mapToScene(event.pos())
            self.create_requested.emit(snap(point.x(), self.snap_enabled),
                                       snap(point.y(), self.snap_enabled))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        item = self.itemAt(event.pos())
        note_item = self._owning_note(item)
        menu = QMenu(self)
        if note_item is None:
            point = self.mapToScene(event.pos())
            add = menu.addAction("Buraya not ekle")
            add.triggered.connect(
                lambda: self.create_requested.emit(
                    snap(point.x(), self.snap_enabled), snap(point.y(), self.snap_enabled)
                )
            )
        else:
            note_id = note_item.note_id
            menu.addAction("Bu nottan hatırlatma oluştur").triggered.connect(
                lambda: self.reminder_requested.emit(note_id)
            )
            menu.addSeparator()
            menu.addAction("Öne getir").triggered.connect(
                lambda: self.raise_requested.emit(note_id)
            )
            menu.addAction("Arkaya gönder").triggered.connect(
                lambda: self.lower_requested.emit(note_id)
            )
            menu.addSeparator()
            menu.addAction("Notu sil").triggered.connect(
                lambda: self.note_deleted.emit(note_id)
            )
        menu.exec(event.globalPos())

    def _owning_note(self, item) -> NoteItem | None:
        """Walk up from whatever was hit to the note that contains it."""
        while item is not None:
            if isinstance(item, NoteItem):
                return item
            item = item.parentItem()
        return None
