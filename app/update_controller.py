"""Güncelleme akışını arayüzle buluşturan ince katman.

`update_flow` Qt bilmez, `UpdateBanner` da servisleri bilmez; ikisini bu sınıf
konuşturur. Ağa çıkan her adım `sync_worker` üzerinden arka planda koşar, yani
kullanıcı denetim sürerken de çalışmaya devam eder.

Sıra hep aynı ve hep kullanıcının onayıyla ilerler: denetle -> şeridi göster ->
"Güncelle" -> indir -> hazırla -> sınat -> yedekle -> kur ve çık.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from app import update_flow
from app.update_flow import UpdateBlocked
from app.version import APP_VERSION
from services.settings_service import UPDATE_AUTO_CHECK, UPDATE_SKIPPED_VERSION
from services.sync_worker import run_in_background
from services.update_service import Release, UpdateService
from services.update_swap import clear_result, read_result

logger = logging.getLogger("office_reminder.update.controller")

#: Açılıştan ne kadar sonra bakılacağı. Senkron ve bildirim denetiminden
#: sonraya bırakıldı: ilk saniyeler kullanıcının verisine ait.
FIRST_CHECK_DELAY_MS = 30_000
#: Günde bir. Sürümler günlerce arayla çıkıyor; daha sık bakmanın karşılığı yok.
CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000


class UpdateController(QObject):
    """Denetimi, indirmeyi ve kurulumu yürütür; çıkışı uygulamaya bırakır."""

    #: Kurulum başlatıldı, uygulama kapanmalı.
    quit_requested = Signal()

    def __init__(self, settings_service, banner, window, backup_factory=None) -> None:
        super().__init__()
        self.settings = settings_service
        self.banner = banner
        self.window = window
        # Fabrika, hazır nesne değil: yedekleme ayarları arada değişmiş
        # olabilir ve yedek kurulumdan hemen önce alınmalı.
        self.backup_factory = backup_factory
        self.service = UpdateService(APP_VERSION)
        self._release: Release | None = None
        self._busy = False

        banner.install_requested.connect(self.install)
        banner.notes_requested.connect(self._show_notes)
        banner.dismissed.connect(self._skip_this_version)

    # ------------------------------------------------------------------ açılış
    def start(self) -> None:
        """Önceki güncellemenin izlerini topla, sonra denetimi zamanla."""
        self._report_previous_result()
        try:
            update_flow.cleanup()
        except Exception:
            logger.debug("Güncelleme artıkları temizlenemedi", exc_info=True)

        if not update_flow.is_frozen():
            # Kaynaktan çalışırken güncelleme diye bir şey yok.
            return
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self.check)
        self.timer.start()
        QTimer.singleShot(FIRST_CHECK_DELAY_MS, self.check)

    def _report_previous_result(self) -> None:
        """Başarısız bir güncelleme sessiz kalmamalı.

        Kurulum uygulama kapalıyken çalışıyor; geriye bıraktığı not olmasa
        kullanıcı eski sürümün neden geri geldiğini hiç öğrenemezdi.
        """
        try:
            from services.update_service import update_dir

            root = update_dir()
            result = read_result(root)
            if not result:
                return
            clear_result(root)
        except Exception:
            logger.debug("Önceki güncelleme sonucu okunamadı", exc_info=True)
            return

        status = result.get("status")
        version = result.get("version") or "?"
        if status == "installed":
            self._notify("Güncelleme tamamlandı", f"Sürüm {version} kuruldu.")
        elif status in ("failed", "rolled_back", "aborted"):
            message = result.get("message") or "Güncelleme uygulanamadı."
            self._notify(
                "Güncelleme yapılamadı",
                f"{message}\nÖnceki sürüm çalışmaya devam ediyor.",
                tone="warning",
            )

    def _notify(self, title: str, body: str, tone: str = "success") -> None:
        try:
            self.window.toasts.show_toast(title, body.replace("\n", " · "), tone)
        except Exception:
            logger.info("%s: %s", title, body)

    # ----------------------------------------------------------------- denetim
    def check(self, manual: bool = False) -> None:
        """Manifeste bak. Elle çağrıldığında ayar ve 'sonra' kaydı geçersiz."""
        if self._busy:
            return
        if not manual and not self._auto_check_enabled():
            return
        if not update_flow.is_frozen():
            if manual:
                self._warn("Kaynaktan çalışırken güncelleme denetlenmez.")
            return

        def done(payload: dict) -> None:
            release = payload.get("result")
            if release is None:
                if manual:
                    self._notify("Güncelleme yok", f"En son sürümü kullanıyorsunuz ({APP_VERSION}).")
                return
            if not manual and self._skipped(release.version_text):
                return
            self._offer(release, manual=manual)

        def failed(message: str) -> None:
            logger.info("Güncelleme denetimi başarısız: %s", message)
            if manual:
                self._warn(f"Güncelleme denetlenemedi:\n{message}")

        run_in_background(self.service.check, on_finished=done, on_error=failed)

    def _offer(self, release: Release, manual: bool) -> None:
        if not self.service.supported(release):
            self._warn(
                f"Sürüm {release.version_text} bu yapının üzerine kurulamıyor. "
                "Yeni sürümü elle indirmeniz gerekiyor."
            )
            return
        self._release = release
        package = self.service.choose(release)
        self.banner.announce(
            release.version_text, package.size / 1048576, bool(release.notes)
        )

    # --------------------------------------------------------------- kurulum
    def install(self) -> None:
        if self._release is None or self._busy:
            return
        release = self._release
        package = self.service.choose(release)

        try:
            update_flow.check_installable()
        except UpdateBlocked as exc:
            self.banner.failed("Güncelleme kurulamıyor")
            self._warn(str(exc))
            return

        self._busy = True
        self.banner.downloading(0, package.size)

        def progress(received: int, total: int) -> None:
            # Arka plan iş parçacığından geliyor; şeridi doğrudan çizemeyiz.
            QTimer.singleShot(0, lambda: self.banner.downloading(received, total))

        def work():
            prepared = update_flow.prepare(
                self.service, release, package, progress=progress
            )
            return prepared

        def done(payload: dict) -> None:
            prepared = payload.get("result")
            self._busy = False
            if prepared is None:
                self.banner.failed("Güncelleme hazırlanamadı")
                return
            self.banner.working("Güncelleme kuruluyor, uygulama yeniden başlayacak…")
            self._backup_before_install()
            try:
                update_flow.launch_installer(prepared)
            except Exception as exc:
                logger.error("Kurulum başlatılamadı", exc_info=True)
                self.banner.failed(f"Kurulum başlatılamadı: {exc}")
                return
            # Kurulum bizim kapanmamızı bekliyor; dosya kilitleri bırakılmalı.
            QTimer.singleShot(400, self.quit_requested.emit)

        def failed(message: str) -> None:
            self._busy = False
            logger.warning("Güncelleme başarısız: %s", message)
            self.banner.failed("Güncelleme yapılamadı")
            self._warn(message)

        run_in_background(work, on_finished=done, on_error=failed)

    def _backup_before_install(self) -> None:
        """Kurulumdan önceki son güvenli an.

        Yeni sürüm migration taşıyor olabilir ve migration'lar tek yönlü;
        vazgeçilmesi gereken bir durumda geri dönüş yolu `.old` klasörü değil,
        bu yedektir.
        """
        if self.backup_factory is None:
            return
        try:
            path = self.backup_factory().create_backup(force=True)
            logger.info("Güncelleme öncesi yedek: %s", path)
        except Exception:
            logger.warning("Güncelleme öncesi yedek alınamadı", exc_info=True)

    # ------------------------------------------------------------------ yardım
    def _auto_check_enabled(self) -> bool:
        try:
            return self.settings.get_bool(UPDATE_AUTO_CHECK)
        except Exception:
            return True

    def _skipped(self, version: str) -> bool:
        try:
            return (self.settings.get(UPDATE_SKIPPED_VERSION) or "") == version
        except Exception:
            return False

    def _skip_this_version(self) -> None:
        """"Sonra": bu sürüm için bir daha rahatsız etme, sonrakinde çık."""
        if self._release is None:
            return
        try:
            self.settings.set(UPDATE_SKIPPED_VERSION, self._release.version_text)
        except Exception:
            logger.debug("Atlanan sürüm yazılamadı", exc_info=True)

    def _show_notes(self) -> None:
        if self._release is None:
            return
        released = f"\n\nYayın tarihi: {self._release.released}" if self._release.released else ""
        QMessageBox.information(
            self.window,
            f"Sürüm {self._release.version_text}",
            f"{self._release.notes}{released}",
        )

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self.window, "Güncelleme", message)


__all__ = ["CHECK_INTERVAL_MS", "FIRST_CHECK_DELAY_MS", "UpdateController"]
