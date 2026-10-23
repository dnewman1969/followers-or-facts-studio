"""Queue: what the background worker is doing, what's waiting, and the worker's log."""

from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from ... import jobs
from ...config import Paths
from ..common import MUTED, RED, STATUS_COLORS, button, color_item, fill, info, label, row, table


class QueuePage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(label("Job queue", "h1"))
        lay.addWidget(label("One job runs at a time so the 12 GB graphics card only ever holds one "
                            "model. The queue keeps running if you close this window. A failed job "
                            "pauses the queue until you've looked at it.", "muted"))
        self.state = label("")
        lay.addWidget(self.state)
        self.pause_btn = button("Pause", self._toggle)
        lay.addWidget(row(self.pause_btn, button("Start worker", lambda: (jobs.start_worker(force=True), self.refresh())),
                          button("Run jobs inside the Studio", lambda: (jobs.start_thread_worker(), self.refresh())),
                          button("Test the worker", self._selftest),
                          button("Cancel selected", self._cancel), button("Move up", lambda: self._move(-1)),
                          button("Move down", lambda: self._move(1))))
        self.table = table(["Job", "Episode", "Stage", "Status", "Progress / error", "Queued", "Finished"])
        lay.addWidget(self.table, 2)
        lay.addWidget(label("Worker log", "h2"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
        self._ids: list[int] = []

    def refresh(self) -> None:
        rows = jobs.jobs()
        self._ids = [j["job_id"] for j in rows]
        fill(self.table, [[j["job_id"], j["project_id"], j["stage"], j["status"],
                           (j["error"] or j["progress"] or "")[:200], (j["created_at"] or "")[:19],
                           (j["finished_at"] or "")[:19]] for j in rows])
        for r, j in enumerate(rows):
            color_item(self.table, r, 3, STATUS_COLORS.get(j["status"], MUTED))
        self.table.resizeColumnsToContents()
        ctl = jobs.control()
        worker = jobs.worker_running()
        self.pause_btn.setText("Resume" if ctl["paused"] else "Pause")
        text = (f"Worker: running {jobs.worker_mode()} (pid {worker})" if worker else "Worker: not running")
        problem = jobs.worker_problem()
        if problem:
            text += f"<br><span style='color:{RED}'>The background worker stopped on start-up:</span><pre>{problem}</pre>"
        if ctl["paused"]:
            text += f"   ·   PAUSED: {ctl['reason'] or 'by you'}"
        self.state.setText(text)
        log = Paths().logs / "worker.log"
        console = Paths().logs / "worker-console.log"
        if log.exists() or console.exists():
            lines = []
            for f in (console, log):
                if f.exists():
                    lines += f.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]
            text = "\n".join(lines)
            if text != self.log.toPlainText():
                self.log.setPlainText(text)
                self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _selftest(self) -> None:
        """Queue a tiny job; it should say 'done' within a few seconds."""
        from ...episode import list_episodes
        from ...util import StageError
        eps = list_episodes()
        if not eps:
            info(self, "Make an episode on the Database page first; the test job needs one to belong to.")
            return
        try:
            jobs.enqueue(eps[0]["project_id"], "selftest")
        except StageError as exc:
            info(self, str(exc))
            return
        if jobs.control()["paused"]:
            jobs.set_paused(False)
        jobs.start_worker(force=True)
        self.refresh()
        info(self, "A tiny test job is queued. In a few seconds it should show 'done' in the list. If it stays "
                   "'queued', the message above the list says why (and jobs will then run inside the Studio).")

    def _toggle(self) -> None:
        paused = jobs.control()["paused"]
        jobs.set_paused(not paused, None if paused else "Paused by you")
        if paused:
            jobs.start_worker()
        self.refresh()

    def _selected(self) -> int | None:
        r = self.table.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def _cancel(self) -> None:
        if (j := self._selected()) is not None:
            jobs.cancel(j)
            self.refresh()

    def _move(self, d: int) -> None:
        if (j := self._selected()) is not None:
            jobs.move(j, d)
            self.refresh()
