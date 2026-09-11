"""Yeni sürümü haber veren ince şerit.

Kesintiye uğratmadan haber vermek şart: kullanıcı ayın 26'sında beyanname
hazırlarken ekranın ortasına çıkan bir kutu, güncellemeden çok işi böler. Şerit
pencerenin üstünde durur, "Sonra" denince kapanır ve o sürüm için bir daha
çıkmaz — bir sonraki sürümde yeniden görünür.

İndirme sırasında aynı şerit ilerlemeyi gösterir; ayrı bir pencere açmıyoruz,
çünkü kullanıcı bu sırada çalışmaya devam edebilmeli.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QProgressBar, QWidget

from ui.theme import tokens
from ui.widgets import button, icon_button, label


class UpdateBanner(QFrame):
    """Tek satır: ne var, ne yapılabilir."""

    install_requested = Signal()
    notes_requested = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UpdateBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        t = tokens()

        row = QHBoxLayout(self)
        row.setContentsMargins(t.space, t.space_sm, t.space_sm, t.space_sm)
        row.setSpacing(t.space_sm)

        self._text = label("", "SectionTitle")
        row.addWidget(self._text, 1)

        self._progress = QProgressBar()
        self._progress.setFixedWidth(180)
        self._progress.setTextVisible(True)
        self._progress.hide()
        row.addWidget(self._progress)

        self._notes_button = button("Notlar", "subtle")
        self._notes_button.clicked.connect(self.notes_requested.emit)
        row.addWidget(self._notes_button)

        self._install_button = button("Güncelle", "primary", "download")
        self._install_button.clicked.connect(self.install_requested.emit)
        row.addWidget(self._install_button)

        self._close_button = icon_button("close", "Sonra")
        self._close_button.clicked.connect(self._dismiss)
        row.addWidget(self._close_button)

        self.hide()

    # ----------------------------------------------------------------- durumlar
    def announce(self, version: str, size_mb: float, has_notes: bool) -> None:
        """Yeni sürüm var: ne olduğu ve ne kadar ineceği."""
        self._text.setText(
            f"Yeni sürüm hazır: {version} · {size_mb:.0f} MB indirilecek"
        )
        self._progress.hide()
        self._notes_button.setVisible(has_notes)
        self._install_button.setEnabled(True)
        self._install_button.show()
        self._close_button.show()
        self.show()

    def downloading(self, received: int, total: int) -> None:
        """İndirme sürüyor. Şerit kapatılamaz; iş yarıda bırakılmamalı."""
        self._text.setText("Güncelleme indiriliyor…")
        self._notes_button.hide()
        self._install_button.setEnabled(False)
        self._close_button.hide()
        self._progress.setRange(0, max(total, 1))
        self._progress.setValue(min(received, total))
        self._progress.show()
        self.show()

    def working(self, message: str) -> None:
        """İndirme bitti, sıra hazırlık ve sınamada — süresi belirsiz."""
        self._text.setText(message)
        self._notes_button.hide()
        self._install_button.setEnabled(False)
        self._close_button.hide()
        self._progress.setRange(0, 0)
        self._progress.show()
        self.show()

    def failed(self, message: str) -> None:
        """Başarısızlık sessiz kalmamalı; şerit hatayı taşır."""
        self._text.setText(message)
        self._progress.hide()
        self._notes_button.hide()
        self._install_button.hide()
        self._close_button.show()
        self.show()

    def _dismiss(self) -> None:
        self.hide()
        self.dismissed.emit()


__all__ = ["UpdateBanner"]
