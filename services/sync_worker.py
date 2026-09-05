"""Run slow, network-bound work off the Qt thread.

Two guarantees matter to callers:

* the callable runs on a pool thread, never on the GUI thread;
* ``on_finished`` / ``on_error`` run **on the GUI thread**, so a handler may
  touch widgets safely. This is enforced by giving the signal object the
  application's thread affinity and connecting with an explicit queued
  connection, rather than relying on where ``run_in_background`` happened to be
  called from.

Live runnables are kept in a module-level registry: ``QRunnable`` deletes
itself once ``run()`` returns, and without a strong reference its signal object
can be collected before the queued callback is delivered — the work would
complete but the UI would never hear about it.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, Qt, QThreadPool, Signal, Slot

logger = logging.getLogger("office_reminder.worker")

# Strong references to in-flight jobs, cleared when each one reports back.
_live: set["SyncRunnable"] = set()


class SyncWorkerSignals(QObject):
    finished = Signal(dict)
    error = Signal(str)
    progress = Signal(str)


class SyncRunnable(QRunnable):
    def __init__(self, func, *args, **kwargs) -> None:
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signals = SyncWorkerSignals()
        # Callbacks must arrive on the GUI thread; queued delivery targets the
        # receiver's thread, so pin the receiver to the application's thread.
        application = QCoreApplication.instance()
        if application is not None:
            self.signals.moveToThread(application.thread())
        # Deletion is managed by the registry below, not by the thread pool.
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        try:
            result = self.func(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            logger.warning("Background job failed: %s", exc, exc_info=True)
            self.signals.error.emit(str(exc))
            return
        self.signals.finished.emit(result if isinstance(result, dict) else {"result": result})


def run_in_background(func, *args, on_finished=None, on_error=None, **kwargs) -> SyncRunnable:
    """Queue `func` on the global thread pool; callbacks run on the Qt thread."""
    runnable = SyncRunnable(func, *args, **kwargs)
    _live.add(runnable)

    def release(_payload=None) -> None:
        _live.discard(runnable)

    queued = Qt.ConnectionType.QueuedConnection
    if on_finished:
        runnable.signals.finished.connect(on_finished, queued)
    if on_error:
        runnable.signals.error.connect(on_error, queued)
    runnable.signals.finished.connect(release, queued)
    runnable.signals.error.connect(release, queued)

    QThreadPool.globalInstance().start(runnable)
    return runnable


def pending_jobs() -> int:
    """How many jobs are still in flight (used by tests and shutdown)."""
    return len(_live)
