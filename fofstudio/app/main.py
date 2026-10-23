"""The window: the steps down the left, the activity bar along the top, one page at a time."""

from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, db, jobs, pipeline
from ..comfy import Comfy
from ..config import DEFAULTS, REPO, Paths, save_settings, settings, settings_path
from ..db import importer
from ..episode import Episode, list_episodes
from ..llm import Ollama
from .common import GOLD, GREEN, MUTED, RED, STYLE
from .pages.database import DatabasePage
from .pages.production import ProductionPage
from .pages.publish import PublishPage
from .pages.queue import QueuePage
from .pages.rendermode import RenderModePage
from .pages.research import ResearchPage
from .pages.script import ScriptPage
from .pages.settings import SettingsPage
from .pages.stories import StoriesPage
from .pages.storyboard import StoryboardPage
from .pages.video import VideoPage
from .widgets import ActivityBar, Toast

# (nav label, stage whose approval marks the step done)
STEPS = [("1  Database", None), ("2  Research", "research"), ("3  Stories", "stories"), ("4  Script", "script"),
         ("5  Storyboard", "storyboard"), ("6  Video", "video"), ("7  Production", "render"),
         ("8  Publish", "upload")]
GROUPS = {"research": ["research"], "stories": ["stories"], "script": ["script"], "storyboard": ["storyboard"],
          "video": ["video_plan", "video"],
          "render": ["narration", "captions", "music", "production", "preview", "render"],
          "upload": ["package", "upload"]}
TOOLS = ["Queue", "Render Mode", "Settings"]


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
        self.resize(1480, 920)
        icon = REPO / "brand" / "owlbert.ico"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.activity = ActivityBar()
        self.activity.job_finished.connect(self._job_finished)
        outer.addWidget(self.activity)
        body = QHBoxLayout()
        body.setSpacing(0)
        left = QWidget()
        left.setFixedWidth(220)
        left.setStyleSheet("background:#1b1e2a;")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 10, 0, 10)
        ep_label = QLabel("  Working on")
        ep_label.setObjectName("muted")
        ll.addWidget(ep_label)
        self.picker = QComboBox()
        self.picker.currentIndexChanged.connect(self._pick_episode)
        ll.addWidget(self.picker)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        for label, _ in STEPS:
            self.nav.addItem(label)
        sep = QListWidgetItem("")
        sep.setFlags(sep.flags() & ~sep.flags())
        self.nav.addItem(sep)
        for t in TOOLS:
            self.nav.addItem("     " + t)
        ll.addWidget(self.nav, 1)
        body.addWidget(left)
        self.stack = QStackedWidget()
        self.pages = [DatabasePage(self), ResearchPage(self), StoriesPage(self), ScriptPage(self),
                      StoryboardPage(self), VideoPage(self), ProductionPage(self), PublishPage(self)]
        self.tools = [QueuePage(), RenderModePage(), SettingsPage()]
        for p in self.pages:
            self.stack.addWidget(p)
        self.stack.addWidget(QWidget())  # the separator row
        for t in self.tools:
            self.stack.addWidget(t)
        self.pages_and_tools = self.pages + self.tools
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(18, 12, 18, 12)
        cl.addWidget(self.stack)
        body.addWidget(content, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)
        self.toast = Toast(central)

        self.nav.currentRowChanged.connect(self._go)
        self.pages[0].chosen.connect(self._chosen)
        for i, p in enumerate(self.pages[1:], 1):
            p.go_next.connect(lambda i=i: self.nav.setCurrentRow(min(i + 1, len(STEPS) - 1)))
        self.ep: Episode | None = None
        self._fill_picker()
        self.nav.setCurrentRow(0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(800)
        QTimer.singleShot(300, self._status)

    # ------------------------------------------------------------ episodes
    def _fill_picker(self, select: str | None = None) -> None:
        self.picker.blockSignals(True)
        self.picker.clear()
        self.picker.addItem("— choose on the Database page —", None)
        for p in list_episodes():
            self.picker.addItem(f"{p['project_id']}  {p['title'][:26]}", p["project_id"])
        if select:
            self.picker.setCurrentIndex(max(0, self.picker.findData(select)))
        elif self.picker.count() > 1:
            self.picker.setCurrentIndex(1)
        self.picker.blockSignals(False)
        self._pick_episode()

    def _pick_episode(self) -> None:
        pid = self.picker.currentData()
        self.ep = Episode.load(pid) if pid else None
        for p in self.pages:
            p.set_episode(self.ep)
        self._nav_marks()

    def _chosen(self, project_id: str, step: int = 1) -> None:
        """Open an episode. Research never starts by itself: you choose how deep first."""
        self._fill_picker(project_id)
        if step < 0:  # the first step that still needs you
            step = next((i for i, (_, stage) in enumerate(STEPS) if stage and self.ep
                         and self.ep.stage_status(stage)["status"] != "approved"), len(STEPS) - 1)
        self.nav.setCurrentRow(step)

    # ------------------------------------------------------------ navigation
    def _go(self, row: int) -> None:
        if row == len(STEPS):  # the separator
            return
        self.stack.setCurrentIndex(row)
        page = self.stack.currentWidget()
        try:
            if hasattr(page, "refresh"):
                page.refresh()
        except Exception as exc:  # noqa: BLE001 - show it, don't crash the window
            QMessageBox.warning(self, APP_NAME, f"{type(exc).__name__}: {exc}")

    def _nav_marks(self) -> None:
        for i, (label, stage) in enumerate(STEPS):
            item = self.nav.item(i)
            if not self.ep or not stage:
                item.setText(label)
                item.setForeground(QColor("#ffffff"))
                continue
            group = GROUPS[stage]
            states = [self.ep.stage_status(s)["status"] for s in group]
            done = self.ep.stage_status(stage)["status"] == "approved"
            if any(s in ("running", "queued") for s in states):
                mark, color = "  …", "#4aa3df"
            elif done:
                mark, color = "  ✔", GREEN
            elif any(s in ("failed", "interrupted") for s in states):
                mark, color = "  ✖", RED
            elif any(s == "awaiting_approval" for s in states):
                mark, color = "  ●", GOLD
            elif pipeline.missing_requirements(self.ep, group[0]):
                mark, color = "", MUTED
            else:
                mark, color = "", "#ffffff"
            item.setText(label + mark)
            item.setForeground(QColor(color))

    def _poll(self) -> None:
        try:
            self.activity.refresh()
            page = self.stack.currentWidget()
            if hasattr(page, "poll"):
                page.poll()
            elif page is self.tools[0]:
                page.refresh()
            self._nav_marks()
            # (the activity bar starts the worker when jobs are waiting)
        except Exception:  # noqa: BLE001 - a busy database is fine; try again next tick
            pass

    def _job_finished(self, job: dict) -> None:
        label = pipeline.stage(job["stage"]).label if job["stage"] in pipeline.BY_NAME else job["stage"]
        if job["status"] == "done":
            self.toast.show_message(f"✔ {label} finished for {job['project_id']}. Have a look.", "ok", 6)
            if job["stage"] == "render" and settings()["video"].get("open_folder_after_render", True):
                self._reveal_render(job["project_id"])
        elif job["status"] == "cancelled":
            self.toast.show_message(f"{label} was cancelled.", "warn", 5)
        else:
            self.toast.show_message(f"✖ {label} failed: {(job['error'] or '')[:160]}", "error", 10)
        QApplication.alert(self, 3000)  # flash the taskbar button
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def _reveal_render(self, project_id: str) -> None:
        """Open the folder with the finished video selected."""
        try:
            from ..util import read_json, reveal
            ep = Episode.load(project_id)
            info = read_json(ep.path("render", "timeline.json"))
            if info and not info.get("draft") and ep.abs(info["output"]).exists():
                reveal(ep.abs(info["output"]))
        except Exception as exc:  # noqa: BLE001 - opening a folder must never break the window
            self.toast.show_message(f"Couldn't open the folder: {exc}", "warn", 6)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt name
        """Close the ComfyUI we started, unless the queue still needs it."""
        from .. import services
        from ..config import settings
        busy = any(j["status"] in ("queued", "running") for j in jobs.jobs(50))
        if busy and jobs.worker_mode() == "inside the Studio":
            answer = QMessageBox.question(
                self, APP_NAME, "Jobs are running inside the Studio (the background worker wouldn't start), so "
                "closing now stops them. Close anyway?")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        if settings()["services"]["stop_comfyui_on_exit"] and not busy:
            services.stop_started_comfyui()
        super().closeEvent(event)

    def _status(self) -> None:
        ollama_ok, _ = Ollama().health()
        comfy_ok, comfy_msg = Comfy().health()
        bits = [f"Ollama: {'running' if ollama_ok else 'not running'}",
                comfy_msg if comfy_ok else "ComfyUI: not running"]
        self.statusBar().showMessage("   ·   ".join(bits) + f"   ·   data: {Paths().root}")


def main() -> None:
    # the playback engine must be chosen before Qt starts (Settings → Sound → Playback engine)
    try:
        backend = settings()["sound"]["media_backend"]
        if backend in ("ffmpeg", "windows"):
            os.environ["QT_MEDIA_BACKEND"] = backend
    except Exception:  # noqa: BLE001 - no settings yet on the very first run
        pass
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
    if "--no-services" not in sys.argv:
        from .startup import Startup
        Startup().exec()
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
