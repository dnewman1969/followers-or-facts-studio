"""Home: your episodes, what each one needs next, and whether the tools are running."""

from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                               QVBoxLayout, QWidget)

from ... import db, jobs, pipeline
from ...episode import Episode, list_episodes
from ..common import (GOLD, GREEN, MUTED, RED, STATUS_COLORS, STATUS_WORDS, button, color_item,
                      error, fill, label, row, table)


class NewEpisodeDialog(QDialog):
    def __init__(self, parent=None, arc_id: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("New episode")
        self.setMinimumWidth(560)
        form = QFormLayout(self)
        existing = [r["project_id"] for r in list_episodes()]
        n = 1
        while f"S01E{n:02d}" in existing:
            n += 1
        self.pid = QLineEdit(f"S01E{n:02d}")
        self.title = QLineEdit()
        self.arc = QComboBox()
        for r in db.rows("SELECT * FROM arc_strength ORDER BY sourced_claims DESC, claims DESC"):
            careful = "  [careful topic]" if r["careful"] else ""
            self.arc.addItem(f"{r['title']}  -  {r['sourced_claims']}/{r['claims']} claims "
                             f"sourced{careful}", r["arc_id"])
        if arc_id:
            self.arc.setCurrentIndex(max(0, self.arc.findData(arc_id)))
        self.arc.currentIndexChanged.connect(self._suggest_title)
        self._suggest_title()
        form.addRow("Episode ID", self.pid)
        form.addRow("Story arc", self.arc)
        form.addRow("Working title", self.title)
        form.addRow(label("Every claim in the arc is included. You can drop claims on the "
                          "Research tab of the episode before running Research.", "muted"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _suggest_title(self) -> None:
        text = self.arc.currentText().split("  -  ")[0]
        self.title.setText(re.sub(r"\s*\(.*?\)", "", text))


class HomePage(QWidget):
    open_episode = Signal(str)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(label("Episodes", "h1"))
        lay.addWidget(label("Every episode goes Research -> Script -> Storyboard -> Narration -> "
                            "Images -> Animation -> Captions -> Music -> Render -> Package -> "
                            "Upload, and stops for your OK after each step.", "muted"))
        self.health = label("", "muted")
        lay.addWidget(self.health)
        lay.addWidget(row(button("New episode", self.new_episode, "primary"),
                          button("Open selected", self._open)))
        self.table = table(["Episode", "Title", "Arc", "Next step", "Status", "YouTube"])
        self.table.cellDoubleClicked.connect(lambda r, c: self._open())
        lay.addWidget(self.table, 1)
        self._ids: list[str] = []

    def refresh(self) -> None:
        rows, colors = [], []
        self._ids = []
        for p in list_episodes():
            ep = Episode.load(p["project_id"])
            nxt = pipeline.next_stage(ep)
            over = {s["name"]: s for s in pipeline.overview(ep)}
            waiting = [s for s in over.values() if s["status"] in ("awaiting_approval", "running",
                                                                     "queued", "failed")]
            st = waiting[0]["status"] if waiting else ("approved" if not nxt else "not_started")
            label_next = pipeline.stage(nxt).label if nxt else "Published"
            if waiting:
                label_next = waiting[0]["label"]
            rows.append([p["project_id"], p["title"], p["arc_id"] or "", label_next,
                         STATUS_WORDS.get(st, st), p["youtube_id"] or ""])
            colors.append(STATUS_COLORS.get(st, MUTED))
            self._ids.append(p["project_id"])
        fill(self.table, rows)
        for r, c in enumerate(colors):
            color_item(self.table, r, 4, c)
        self.table.resizeColumnsToContents()
        worker = jobs.worker_running()
        ctl = jobs.control()
        bits = [f"Worker: {'running' if worker else 'idle'}"]
        if ctl["paused"]:
            bits.append(f"Queue PAUSED - {ctl['reason'] or ''}")
        self.health.setText("   ·   ".join(bits))

    def _open(self) -> None:
        r = self.table.currentRow()
        if 0 <= r < len(self._ids):
            self.open_episode.emit(self._ids[r])

    def new_episode(self, arc_id: str | None = None) -> None:
        dlg = NewEpisodeDialog(self, arc_id if isinstance(arc_id, str) else None)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            ep = Episode.create(dlg.pid.text().strip(), dlg.title.text().strip() or "Untitled",
                                dlg.arc.currentData())
        except (ValueError, KeyError) as exc:
            error(self, str(exc))
            return
        self.refresh()
        self.open_episode.emit(ep.project_id)
