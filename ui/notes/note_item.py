"""One sticky note on the canvas.

The note is a `QGraphicsObject` that paints the paper itself and hosts a real
`QTextEdit` for the body, so rich text editing, selection and the clipboard
behave the way they do everywhere else in the app rather than being
re-implemented on top of a graphics item.

Geometry is reported through signals rather than written straight to the
database: the page batches those writes so that dragging a note does not
produce a hundred UPDATE statements.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QTextDocument,
    QTextImageFormat,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsObject,
    QGraphicsProxyWidget,
    QGraphicsSceneMouseEvent,
    QTextEdit,
)

import logging

from database.repositories.notes import MIN_HEIGHT, MIN_WIDTH
from services.note_images import SCHEME, NoteImageStore
from ui.theme import note_paper, tokens

logger = logging.getLogger(__name__)

#: Height of the drag strip along the top of a note.
HEADER = 26.0
#: Side of the square hit area for the resize grip in the bottom-right corner.
GRIP = 16.0
#: Padding between the paper edge and the text body.
PAD = 8.0


class NoteDocument(QTextDocument):
    """A document that knows how to fetch a note's pictures.

    The stored HTML refers to images as `note-image:name.png`, so Qt cannot
    resolve them on its own; this turns that private scheme into a file in the
    runtime folder when the document asks for it.
    """

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store

    def loadResource(self, resource_type: int, url: QUrl):  # noqa: N802
        if url.scheme() == SCHEME:
            name = url.path() or url.toString()[len(SCHEME) + 1 :]
            try:
                path = self.store.path_for(name)
            except ValueError:
                logger.warning("Geçersiz not görseli: %s", name)
                return QImage()
            image = QImage(str(path))
            if image.isNull():
                # The file was deleted from the runtime folder; show nothing
                # rather than Qt's broken-image box.
                logger.info("Not görseli bulunamadı: %s", name)
            return image
        return super().loadResource(resource_type, url)


class NoteBody(QTextEdit):
    """The editable paper surface.

    Wheel events are passed up so that scrolling over a note pans and zooms the
    canvas instead of silently scrolling inside a note the user is not editing.
    """

    def __init__(self, store=None) -> None:
        super().__init__()
        self.store = store or NoteImageStore()
        self.setDocument(NoteDocument(self.store, self))
        self.setFrameShape(QTextEdit.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAcceptRichText(True)
        self.setTabChangesFocus(True)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

    # ------------------------------------------------------------------ paste
    def insertFromMimeData(self, source) -> None:  # noqa: N802
        """A screenshot on the clipboard becomes a picture on the note."""
        if source.hasImage():
            image = QImage(source.imageData())
            if not image.isNull() and self._insert_image(image):
                return
        # A picture dragged in from Explorer is the same gesture as pasting one.
        dropped = self._dropped_images(source)
        if dropped:
            for path in dropped:
                image = QImage(str(path))
                if not image.isNull():
                    self._insert_image(image)
            return
        super().insertFromMimeData(source)

    # ------------------------------------------------------------------- drop
    def canInsertFromMimeData(self, source) -> bool:  # noqa: N802
        if source.hasImage():
            return True
        if source.hasUrls() and self._dropped_images(source):
            return True
        return QTextEdit.canInsertFromMimeData(self, source)

    @staticmethod
    def _dropped_images(source) -> list:
        """Image files among dropped URLs; anything else is left to Qt."""
        from pathlib import Path as _Path

        suffixes = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
        found = []
        for url in source.urls():
            if not url.isLocalFile():
                continue
            path = _Path(url.toLocalFile())
            if path.suffix.lower() in suffixes and path.is_file():
                found.append(path)
        return found

    def _insert_image(self, image: QImage) -> bool:
        try:
            name = self.store.save(image)
        except Exception as exc:
            logger.warning("Görsel yapıştırılamadı: %s", exc, exc_info=True)
            return False

        # Fit the picture to the note rather than letting a 1600px screenshot
        # decide how wide the note's text should be.
        available = max(self.viewport().width() - 8, 40)
        width = min(image.width(), available)

        fmt = QTextImageFormat()
        fmt.setName(f"{SCHEME}:{name}")
        fmt.setWidth(width)
        fmt.setHeight(image.height() * width / image.width())
        self.textCursor().insertImage(fmt)
        return True


class NoteItem(QGraphicsObject):
    """A movable, resizable sticky note."""

    geometry_changed = Signal(int, float, float, float, float)
    content_changed = Signal(int, str, str)
    focus_gained = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, note) -> None:
        super().__init__()
        self.note_id = note.id
        self.colour_key = note.colour
        self._width = float(note.width)
        self._height = float(note.height)
        self._resizing = False
        self._press_origin = QPointF()
        self._press_size = (0.0, 0.0)

        self.setPos(float(note.x), float(note.y))
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)

        self.body = NoteBody()
        if note.content_html:
            self.body.setHtml(note.content_html)
        self.proxy = QGraphicsProxyWidget(self)
        self.proxy.setWidget(self.body)
        self.body.textChanged.connect(self._on_text_changed)
        self.body.installEventFilter(self)

        self.apply_colour(note.colour)
        self._layout_body()

    # ------------------------------------------------------------------ shape
    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt naming
        # The extra margin leaves room for the drop shadow so it is not clipped.
        return QRectF(-2, -2, self._width + 4, self._height + 6)

    def size(self) -> tuple[float, float]:
        return self._width, self._height

    #: Qt's "no maximum" sentinel; the proxy caches the widget's size hints and
    #: will not grow past a stale one unless the constraints are cleared first.
    UNBOUNDED = 16777215

    def _layout_body(self) -> None:
        width = max(self._width - 2 * PAD, 10.0)
        height = max(self._height - HEADER - PAD, 10.0)
        # Order matters: clearing the editor's own size constraints invalidates
        # the proxy's cached hint, and only then does setGeometry actually
        # resize both. Sizing either one alone left the note's text clipped to
        # the editor's initial 53px hint.
        self.body.setMinimumSize(0, 0)
        self.body.setMaximumSize(self.UNBOUNDED, self.UNBOUNDED)
        self.proxy.setGeometry(QRectF(PAD, HEADER, width, height))

    def _grip_rect(self) -> QRectF:
        return QRectF(self._width - GRIP, self._height - GRIP, GRIP, GRIP)

    def _header_rect(self) -> QRectF:
        return QRectF(0, 0, self._width, HEADER)

    # ----------------------------------------------------------------- colour
    def apply_colour(self, key: str) -> None:
        self.colour_key = key
        paper = note_paper(key)
        self.body.setStyleSheet(
            "QTextEdit {"
            " background: transparent;"
            f" color: {paper.ink};"
            " border: none;"
            " selection-background-color: rgba(0,0,0,60);"
            "}"
        )
        self.update()

    # ---------------------------------------------------------------- painting
    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        paper = note_paper(self.colour_key)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        radius = 6.0
        body_path = QPainterPath()
        body_path.addRoundedRect(QRectF(0, 0, self._width, self._height), radius, radius)
        painter.fillPath(body_path, QBrush(QColor(paper.fill)))

        # Header strip: the drag handle, and the only part of the paper that is
        # a different tone, so it reads as "grab here". Clipped to the paper so
        # its top corners follow the same radius.
        painter.save()
        painter.setClipPath(body_path)
        painter.fillRect(self._header_rect(), QBrush(QColor(paper.header)))
        painter.setPen(QPen(QColor(paper.edge), 1))
        painter.drawLine(
            QPointF(0, HEADER), QPointF(self._width, HEADER)
        )
        painter.restore()

        pen = QPen(QColor(tokens().accent if self.isSelected() else paper.edge))
        pen.setWidthF(2.0 if self.isSelected() else 1.0)
        painter.setPen(pen)
        painter.drawPath(body_path)

        # Grip: three short diagonals, the conventional resize affordance.
        grip = self._grip_rect()
        painter.setPen(QPen(QColor(paper.edge), 1.5))
        for step in (3, 7, 11):
            painter.drawLine(
                QPointF(grip.right() - step, grip.bottom() - 2),
                QPointF(grip.right() - 2, grip.bottom() - step),
            )

    # -------------------------------------------------------------- interaction
    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        self.focus_gained.emit(self.note_id)
        if self._grip_rect().contains(event.pos()):
            self._resizing = True
            self._press_origin = event.scenePos()
            self._press_size = (self._width, self._height)
            event.accept()
            return
        if not self._header_rect().contains(event.pos()):
            # Clicks on the paper belong to the text editor, not to dragging.
            super().mousePressEvent(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if self._resizing:
            delta = event.scenePos() - self._press_origin
            self.prepareGeometryChange()
            self._width = max(self._press_size[0] + delta.x(), MIN_WIDTH)
            self._height = max(self._press_size[1] + delta.y(), MIN_HEIGHT)
            self._layout_body()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        was_resizing = self._resizing
        self._resizing = False
        super().mouseReleaseEvent(event)
        if was_resizing or self.flags() & QGraphicsObject.GraphicsItemFlag.ItemIsMovable:
            self.emit_geometry()

    def hoverMoveEvent(self, event) -> None:  # noqa: N802
        if self._grip_rect().contains(event.pos()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif self._header_rect().contains(event.pos()):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.body and event.type() == event.Type.FocusIn:
            self.focus_gained.emit(self.note_id)
        return super().eventFilter(watched, event)

    # -------------------------------------------------------------- reporting
    def snap_to(self, x: float, y: float) -> None:
        self.setPos(x, y)

    def emit_geometry(self) -> None:
        self.geometry_changed.emit(
            self.note_id, self.pos().x(), self.pos().y(), self._width, self._height
        )

    def set_size(self, width: float, height: float) -> None:
        self.prepareGeometryChange()
        self._width = max(float(width), MIN_WIDTH)
        self._height = max(float(height), MIN_HEIGHT)
        self._layout_body()
        self.update()

    def _on_text_changed(self) -> None:
        self.content_changed.emit(
            self.note_id, self.body.toHtml(), self.body.toPlainText()
        )

    def default_font(self) -> QFont:
        return self.body.font()
