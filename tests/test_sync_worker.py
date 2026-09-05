"""The background worker must actually call back on the Qt thread.

Regression: the runnable auto-deleted itself as soon as `run()` returned, and
its signal object went with it, so a queued callback could be dropped. The work
finished but the UI never refreshed and official date changes were never
announced.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QEventLoop, QTimer

from services.sync_worker import pending_jobs, run_in_background


def _pump(predicate, timeout_ms: int = 5000) -> bool:
    """Spin the Qt event loop until predicate holds or the timeout expires."""
    loop = QEventLoop()
    result = {"ok": False}

    def poll() -> None:
        if predicate():
            result["ok"] = True
            loop.quit()

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(10)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    return result["ok"] or predicate()


def test_finished_callback_runs_on_the_qt_thread(qt_app):
    """The work runs off the GUI thread; the callback must come back onto it.

    A callback delivered on the worker thread would let a handler touch widgets
    from the wrong thread, which is undefined behaviour in Qt.
    """
    gui_thread = threading.get_ident()
    received: list[dict] = []
    worker_thread: list[int] = []
    callback_thread: list[int] = []

    def work() -> dict:
        worker_thread.append(threading.get_ident())
        return {"value": 42}

    def done(payload: dict) -> None:
        callback_thread.append(threading.get_ident())
        received.append(payload)

    run_in_background(work, on_finished=done)

    assert _pump(lambda: bool(received)), "arka plan işi geri çağırmadı"
    assert received == [{"value": 42}]
    assert worker_thread[0] != gui_thread, "iş Qt thread'inde çalışmamalı"
    assert callback_thread[0] == gui_thread, (
        "on_finished Qt/GUI thread'inde çalışmalı; aksi hâlde widget'lara "
        "yanlış thread'den dokunulur"
    )
    assert _pump(lambda: pending_jobs() == 0)


def test_error_callback_runs_on_the_qt_thread(qt_app):
    gui_thread = threading.get_ident()
    errors: list[str] = []
    callback_thread: list[int] = []

    def work():
        raise OSError("network is unreachable")

    def failed(message: str) -> None:
        callback_thread.append(threading.get_ident())
        errors.append(message)

    run_in_background(work, on_finished=lambda _r: None, on_error=failed)

    assert _pump(lambda: bool(errors)), "hata geri bildirilmedi"
    assert "network is unreachable" in errors[0]
    assert callback_thread[0] == gui_thread, "on_error Qt/GUI thread'inde çalışmalı"
    assert _pump(lambda: pending_jobs() == 0)


def test_many_jobs_all_report_back_on_the_qt_thread(qt_app):
    gui_thread = threading.get_ident()
    done: list[dict] = []
    threads: set[int] = set()

    def work(index: int) -> dict:
        return {"index": index}

    def collect(payload: dict) -> None:
        threads.add(threading.get_ident())
        done.append(payload)

    for index in range(8):
        run_in_background(work, index, on_finished=collect)

    assert _pump(lambda: len(done) == 8), f"yalnızca {len(done)}/8 iş geri döndü"
    assert sorted(item["index"] for item in done) == list(range(8))
    assert threads == {gui_thread}, "her callback GUI thread'inde çalışmalı"
    assert _pump(lambda: pending_jobs() == 0)
