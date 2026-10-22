"""The window: sidebar on the left, one page at a time on the right."""

from __future__ import annotations

import sys
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QListWidget, QMainWindow, QMessageBox,
                               QStackedWidget, QWidget)

from .. import APP_NAME, __version__, db, jobs
from ..config import DEFAULTS, REPO, Paths, save_settings, settings_path
from ..db import importer
from ..llm import Ollama
from ..comfy import Comfy
from .common import STYLE
from .pages.episode import EpisodePage
from .pages.home import HomePage
from .pages.queue import QueuePage
from .pages.rendermode import RenderModePage
from .pages.research import ResearchPage
from .pages.settings import SettingsPage


def first_run() -> None:
    Paths().ensure()
    if not settings_path().exists():
        save_settings(DEFAULTS)
    db.init()
    if db.is_empty():
        importer.import_research()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1360, 860)
        icon = REPO / "brand" / "owlbert-profile.png"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(190)
        self.stack = QStackedWidget()
        self.home = HomePage()
        self.research = ResearchPage()
        self.episode = EpisodePage()
        self.queue = QueuePage()
        self.rendermode = RenderModePage()
        self.settings = SettingsPage()
        for name, page in (("Home", self.home), ("Research", self.research), ("Episode", self.episode),
                           ("Queue", self.queue), ("Render Mode", self.rendermode),
                           ("Settings", self.settings)):
            self.nav.addItem(name)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self._go)
        lay.addWidget(self.nav)
        content = QWidget()
        cl = QHBoxLayout(content)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.addWidget(self.stack)
        lay.addWidget(content, 1)
        self.setCentralWidget(central)

        self.home.open_episode.connect(self._open_episode)
        self.research.make_episode.connect(self._new_from_arc)
        self.nav.setCurrentRow(0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(2500)
        QTimer.singleShot(200, self._status)

    def _go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception as exc:  # noqa: BLE001 - show, don't crash the window
                QMessageBox.warning(self, APP_NAME, f"{type(exc).__name__}: {exc}")

    def _open_episode(self, project_id: str) -> None:
        self.nav.setCurrentRow(2)
        self.episode.open(project_id)

    def _new_from_arc(self, arc_id: str) -> None:
        self.nav.setCurrentRow(0)
        self.home.new_episode(arc_id)

    def _poll(self) -> None:
        page = self.stack.currentWidget()
        try:
            if page is self.episode:
                self.episode.poll()
            elif page in (self.queue, self.home):
                page.refresh()
        except Exception:  # noqa: BLE001 - a busy database is fine; try next tick
            pass
        if any(j["status"] == "queued" for j in jobs.jobs(20)) and not jobs.worker_running() \
                and not jobs.control()["paused"]:
            jobs.start_worker()

    def _status(self) -> None:
        ollama_ok, _ = Ollama().health()
        comfy_ok, comfy_msg = Comfy().health()
        bits = [f"Ollama: {'running' if ollama_ok else 'not running'}",
                comfy_msg if comfy_ok else "ComfyUI: not running"]
        self.statusBar().showMessage("   ·   ".join(bits) + f"   ·   data: {Paths().root}")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)

    def excepthook(kind, value, tb):
        text = "".join(traceback.format_exception(kind, value, tb))
        try:
            (Paths().logs / "app-errors.log").open("a", encoding="utf-8").write(text + "\n")
        except OSError:
            pass
        QMessageBox.critical(None, APP_NAME, f"{kind.__name__}: {value}")
    sys.excepthook = excepthook

    try:
        first_run()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, APP_NAME, f"Couldn't set up the data folder {Paths().root}:\n{exc}\n\n"
                             "Check config/data-dir.txt or run setup.ps1.")
        return
    jobs.recover_stale()
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
