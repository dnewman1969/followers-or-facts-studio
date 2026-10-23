"""Widgets that make it obvious what's happening: the activity bar, toasts, status chips,
buttons that react, and the base class every pipeline page uses."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from PySide6.QtCore import QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

from .. import jobs, pipeline
from ..util import StageError
from .common import GOLD, GREEN, MUTED, PANEL, RED, STATUS_COLORS, STATUS_WORDS, error, tint

CHECK_COLORS = {"block": RED, "warn": GOLD, "ok": GREEN}
CHECK_ICONS = {"block": "✖", "warn": "!", "ok": "✔"}


def _ago(iso: str | None) -> str:
    if not iso:
        return ""
    secs = int((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds())
    return f"{secs // 60}:{secs % 60:02d}"


class Chip(QLabel):
    """A coloured status pill: Not started / Running / Needs your OK / Approved..."""

    def set_status(self, status: str, text: str | None = None) -> None:
        color = STATUS_COLORS.get(status, MUTED)
        self.setText(text or STATUS_WORDS.get(status, status))
        self.setStyleSheet(f"background:{tint(color, 0.13)}; color:{color}; border:1px solid {color}; "
                           "border-radius:10px; padding:2px 10px; font-weight:600;")


class Toast(QLabel):
    """A message that slides in at the bottom right for a few seconds."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setMaximumWidth(420)
        self.hide()
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade)

    def show_message(self, text: str, kind: str = "ok", seconds: float = 4.0) -> None:
        color = {"ok": GREEN, "warn": GOLD, "error": RED, "info": "#4aa3df"}.get(kind, GREEN)
        self.setText(text)
        self.setStyleSheet(f"background:{PANEL}; color:white; border-left:5px solid {color}; "
                           "border-radius:6px; padding:12px 16px; font-size:11pt;")
        self.adjustSize()
        p = self.parentWidget()
        self.move(p.width() - self.width() - 24, p.height() - self.height() - 40)
        self.raise_()
        self.show()
        self._anim.stop()
        self._fx.setOpacity(1.0)
        self._timer.start(int(seconds * 1000))

    def _fade(self) -> None:
        self._anim.setDuration(600)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.hide)
        self._anim.start()


class ActivityBar(QFrame):
    """Always visible at the top: what the computer is doing right now, how far along, and Cancel."""

    job_finished = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setObjectName("activity")
        self.setStyleSheet(f"QFrame#activity {{ background:{PANEL}; border-bottom:1px solid #2c3046; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        self.dot = QLabel("●")
        self.text = QLabel("Ready")
        self.text.setStyleSheet("font-size:11pt;")
        self.bar = QProgressBar()
        self.bar.setFixedWidth(260)
        self.bar.setTextVisible(True)
        self.bar.setStyleSheet(f"QProgressBar {{ background:#22263a; border:none; border-radius:6px; "
                               f"height:14px; color:white; text-align:center; }} "
                               f"QProgressBar::chunk {{ background:{GOLD}; border-radius:6px; }}")
        self.elapsed = QLabel("")
        self.elapsed.setStyleSheet(f"color:{MUTED};")
        self.cancel = QPushButton("Cancel")
        self.cancel.setObjectName("danger")
        self.cancel.clicked.connect(self._cancel)
        self.resume = QPushButton("Resume the queue")
        self.resume.setObjectName("primary")
        self.resume.clicked.connect(self._resume)
        self.resume.hide()
        self.queue_text = QLabel("")
        self.queue_text.setStyleSheet(f"color:{MUTED};")
        lay.addWidget(self.dot)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.queue_text)
        lay.addWidget(self.bar)
        lay.addWidget(self.elapsed)
        lay.addWidget(self.cancel)
        lay.addWidget(self.resume)
        self._running: dict[str, Any] | None = None
        self._seen_done: set[int] = set()
        self._pulse = 0
        self.refresh()

    def refresh(self) -> None:
        rows = jobs.jobs(60)
        running = next((j for j in rows if j["status"] == "running"), None)
        queued = [j for j in rows if j["status"] == "queued"]
        ctl = jobs.control()
        # tell the window about jobs that finished since last time
        if self._running and (not running or running["job_id"] != self._running["job_id"]):
            done = next((j for j in rows if j["job_id"] == self._running["job_id"]), None)
            if done and done["job_id"] not in self._seen_done:
                self._seen_done.add(done["job_id"])
                self.job_finished.emit(done)
        self._running = running
        if running:
            self.resume.setVisible(False)
            self._pulse = (self._pulse + 1) % 2
            self.dot.setStyleSheet(f"color:{'#4aa3df' if self._pulse else '#2a6f9e'}; font-size:14pt;")
            label = pipeline.stage(running["stage"]).label if running["stage"] in pipeline.BY_NAME else running["stage"]
            self.text.setText(f"<b>Working: {running['project_id']} · {label}</b> — "
                              f"{running['progress'] or 'starting...'}")
            if running["progress_pct"] is None:
                self.bar.setRange(0, 0)  # moving "busy" bar when the percent isn't known
            else:
                self.bar.setRange(0, 100)
                self.bar.setValue(int(running["progress_pct"]))
                self.bar.setFormat("%p%")
            self.bar.show()
            self.elapsed.setText(_ago(running["started_at"]))
            self.cancel.show()
            self.cancel.setEnabled(not running["cancel_requested"])
            self.cancel.setText("Cancelling..." if running["cancel_requested"] else "Cancel")
        else:
            self.bar.hide()
            self.cancel.hide()
            self.elapsed.setText("")
            self.resume.setVisible(bool(ctl["paused"]))
            problem = jobs.worker_problem() if queued else ""
            if ctl["paused"]:
                self.dot.setStyleSheet(f"color:{RED}; font-size:14pt;")
                self.text.setText(f"<b>Queue paused</b> — {ctl['reason'] or ''}"
                                  + (f" {len(queued)} job(s) waiting." if queued else ""))
            elif queued and problem:
                self.dot.setStyleSheet(f"color:{RED}; font-size:14pt;")
                self.text.setText("<b>The background worker didn't start</b>, so jobs will run inside the Studio. "
                                  f"Its last message: {problem.splitlines()[-1][:160]}")
                jobs.start_worker()
            elif queued and not jobs.worker_running():
                self.dot.setStyleSheet(f"color:{GOLD}; font-size:14pt;")
                self.text.setText("Starting the worker...")
                jobs.start_worker()
            else:
                self.dot.setStyleSheet(f"color:{GREEN}; font-size:14pt;")
                self.text.setText("Ready — nothing running")
        self.queue_text.setText(f"{len(queued)} waiting" if queued else "")

    def _resume(self) -> None:
        jobs.set_paused(False)
        jobs.start_worker(force=True)
        self.refresh()

    def _cancel(self) -> None:
        if self._running:
            jobs.cancel(self._running["job_id"])
            self.cancel.setText("Cancelling...")
            self.cancel.setEnabled(False)


def click_feedback(button: QPushButton, action: Callable[[], Any], busy_text: str = "Starting...") -> None:
    """Make a button show it was pressed: it greys out and says what it's doing for a moment."""
    def go() -> None:
        old = button.text()
        button.setEnabled(False)
        button.setText(busy_text)
        QApplication.processEvents()
        try:
            action()
        except StageError as exc:
            error(button.window(), str(exc))
        finally:
            QTimer.singleShot(900, lambda: (button.setText(old), button.setEnabled(True)))
    button.clicked.connect(go)


class ChecksList(QListWidget):
    def set_checks(self, checks: list) -> None:
        self.clear()
        for c in checks:
            item = QListWidgetItem(f"{CHECK_ICONS[c.level]}  {c.message}")
            item.setForeground(QColor(CHECK_COLORS[c.level]))
            self.addItem(item)
        self.setVisible(bool(checks))
        self.setFixedHeight(min(150, 26 * max(1, len(checks)) + 8))


class PageProgress(QFrame):
    """A big progress line on the page itself while one of its jobs runs: what it's doing right now,
    a bar, and how long it's been going."""

    def __init__(self):
        super().__init__()
        self.setObjectName("pageprogress")
        self.setStyleSheet(f"QFrame#pageprogress {{ background:#1d2133; border:1px solid {tint(GOLD, 0.45)}; "
                           "border-radius:6px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        top = QHBoxLayout()
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.text.setStyleSheet("font-size:11pt;")
        self.elapsed = QLabel("")
        self.elapsed.setStyleSheet(f"color:{MUTED}; font-size:11pt;")
        top.addWidget(self.text, 1)
        top.addWidget(self.elapsed)
        lay.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setStyleSheet(f"QProgressBar {{ background:#22263a; border:none; border-radius:6px; height:16px; "
                               f"color:white; text-align:center; }} QProgressBar::chunk {{ background:{GOLD}; "
                               "border-radius:6px; }")
        lay.addWidget(self.bar)
        self.hide()

    def show_job(self, job: dict[str, Any] | None) -> None:
        if not job:
            self.hide()
            return
        label = pipeline.stage(job["stage"]).label if job["stage"] in pipeline.BY_NAME else job["stage"]
        if job["status"] == "queued":
            self.text.setText(f"<b style='color:{GOLD}'>●</b> <b>{label}</b>: waiting for the job ahead of it to finish...")
            self.bar.setRange(0, 0)
            self.elapsed.setText("")
        else:
            self.text.setText(f"<b style='color:{GOLD}'>●</b> <b>{label}</b>: "
                              f"{job['progress'] or 'starting the local AI (loading the model can take a minute)...'}")
            if job["progress_pct"] is None:
                self.bar.setRange(0, 0)
            else:
                self.bar.setRange(0, 100)
                self.bar.setValue(int(job["progress_pct"]))
            self.elapsed.setText(_ago(job["started_at"]))
        self.show()


class StagePage(QWidget):
    """Base for the pipeline pages. Subclasses set STAGES (stage names the page runs),
    build their own content, and call self.run_stage / self.approve."""

    TITLE = ""
    HELP = ""
    APPROVE_STAGE = ""      # the stage the big "Approve and continue" button approves
    SHOW_PROGRESS = True    # the progress line on the page (Research has its own)
    CLEAR_STAGE = ""        # the step the "Clear..." button starts over from
    go_next = Signal()

    def __init__(self, window):
        super().__init__()
        self.win = window
        self.ep = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.title = QLabel(self.TITLE)
        self.title.setObjectName("h1")
        self.chip = Chip()
        head.addWidget(self.title)
        head.addWidget(self.chip)
        head.addStretch(1)
        self.clear_btn = QPushButton("Clear and start over...")
        self.clear_btn.setObjectName("danger")
        self.clear_btn.setToolTip("Delete this step's work and everything made after it, so you can do it again")
        self.clear_btn.clicked.connect(self._clear_clicked)
        self.clear_btn.setVisible(bool(self.CLEAR_STAGE))
        head.addWidget(self.clear_btn)
        self.approve_btn = QPushButton("Approve and continue  →")
        self.approve_btn.setObjectName("primary")
        self.approve_btn.clicked.connect(self._approve_clicked)
        head.addWidget(self.approve_btn)
        outer.addLayout(head)
        self.help = QLabel(self.HELP)
        self.help.setObjectName("muted")
        self.help.setWordWrap(True)
        outer.addWidget(self.help)
        self.checks = ChecksList()
        self.checks.setVisible(False)
        outer.addWidget(self.checks)
        self.page_progress = PageProgress()
        outer.addWidget(self.page_progress)
        self.body = QVBoxLayout()
        outer.addLayout(self.body, 1)
        self._last_status: dict[str, str] = {}

    # ---- helpers for subclasses
    def toast(self, text: str, kind: str = "ok") -> None:
        self.win.toast.show_message(text, kind)

    def run_stage(self, stage: str, options: dict[str, Any] | None = None, label: str = "") -> None:
        if not self.ep:
            raise StageError("Pick a story on the Database page first.")
        jobs.enqueue(self.ep.project_id, stage, options or {})
        ctl = jobs.control()
        if ctl["paused"]:   # you pressed a Run button: that's your OK to carry on after an earlier failure
            jobs.set_paused(False)
        jobs.start_worker(force=True)
        self.toast(f"Started: {label or pipeline.stage(stage).label}. Watch the bar at the top."
                   + (" (The queue had been paused; it's running again.)" if ctl["paused"] else ""), "info")
        self.win.activity.refresh()
        self.refresh()
        self._show_progress()

    def stage_status(self, stage: str) -> dict[str, Any]:
        return self.ep.stage_status(stage) if self.ep else {"status": "not_started"}

    def busy(self, stage: str) -> bool:
        return self.stage_status(stage)["status"] in ("queued", "running")

    def _clear_clicked(self) -> None:
        if not self.ep or not self.CLEAR_STAGE:
            return
        from PySide6.QtWidgets import QMessageBox
        names = [pipeline.stage(n).label for n in pipeline.clear_plan(self.CLEAR_STAGE) if not pipeline.stage(n).hidden]
        answer = QMessageBox.question(
            self, "Clear and start over",
            f"Clear {names[0]} for {self.ep.project_id} and start it again?\n\n"
            f"This deletes the work from these steps: {', '.join(names)}.\n\n"
            "Your research, ticked evidence, video style and everything before this step are kept. "
            "Anything already uploaded to YouTube stays there.")
        if answer != QMessageBox.Yes:
            return
        try:
            cleared = pipeline.clear(self.ep, self.CLEAR_STAGE)
        except StageError as exc:
            error(self, str(exc))
            return
        self.toast(f"Cleared: {', '.join(cleared)}. Start this step again when you're ready.")
        self.win.activity.refresh()
        for page in getattr(self.win, "pages", []):
            if hasattr(page, "_sig"):
                page._sig = None   # pages that cache what they showed redraw from scratch
        self.refresh()
        if hasattr(self.win, "_nav_marks"):
            self.win._nav_marks()

    def _approve_clicked(self) -> None:
        if not self.ep or not self.APPROVE_STAGE:
            return
        try:
            pipeline.approve(self.ep, self.APPROVE_STAGE)
        except StageError as exc:
            error(self, str(exc))
            self.refresh()
            return
        self.toast(f"{pipeline.stage(self.APPROVE_STAGE).label} approved.")
        self.go_next.emit()

    # ---- called by the window
    def set_episode(self, ep) -> None:
        self.ep = ep
        self.refresh()

    def refresh(self) -> None:
        if not self.ep or not self.APPROVE_STAGE:
            self.chip.set_status("not_started", "Pick a story first" if not self.ep else "")
            self.approve_btn.setEnabled(False)
            return
        st = self.stage_status(self.APPROVE_STAGE)
        self.chip.set_status(st["status"])
        if self.CLEAR_STAGE:
            self.clear_btn.setEnabled(not any(self.busy(n) for n in pipeline.clear_plan(self.CLEAR_STAGE)))
        missing = pipeline.missing_requirements(self.ep, self.APPROVE_STAGE)
        if missing:
            self.chip.set_status("not_started", "Waiting for " + ", ".join(pipeline.stage(m).label for m in missing))
        self.approve_btn.setEnabled(st["status"] in ("awaiting_approval", "rejected", "reset")
                                    and not missing)
        self.approve_btn.setText("Approved ✔" if st["status"] == "approved" else "Approve and continue  →")
        if st["status"] in ("not_started", "queued", "running") or missing:
            self.checks.set_checks([])
        else:
            self.checks.set_checks(pipeline.checks(self.ep, self.APPROVE_STAGE))

    def _show_progress(self) -> None:
        job = None
        if self.ep and self.SHOW_PROGRESS:
            mine = set(self.watched()) | {self.APPROVE_STAGE}
            job = next((j for j in jobs.jobs(30) if j["project_id"] == self.ep.project_id and j["stage"] in mine
                        and j["status"] in ("running", "queued")), None)
        self.page_progress.show_job(job)

    def poll(self) -> None:
        """Every second or so: refresh when any of this page's stages changed status."""
        self._show_progress()
        if not self.ep:
            return
        now = {s: self.ep.stage_status(s)["status"] for s in self.watched()}
        if now != self._last_status:
            self._last_status = now
            self.refresh()

    def watched(self) -> list[str]:
        return [self.APPROVE_STAGE] if self.APPROVE_STAGE else []
