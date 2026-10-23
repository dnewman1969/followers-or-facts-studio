"""Database: pick what the video is about - a Story, a Conspiracy, a Person or an Organization -
read what it will cover, then press OK to send it to Research. The Researched tab lists everything
already researched, the videos made from it, and starts another video from the same research."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter,
                               QTextBrowser, QVBoxLayout, QWidget)

from ... import db, researched, subjects
from ...episode import Episode, next_id
from ..common import GOLD, GREEN, MUTED, RED, color_item, error, fill, table
from ..widgets import Chip


TAB_NAMES = {**subjects.KINDS, "researched": "Researched ★"}
# which step to open for each button on the Researched tab
OPEN_RESEARCH, OPEN_STORIES = 1, 2


class DatabasePage(QWidget):
    chosen = Signal(str, int)  # project_id, which step to open

    def __init__(self, window):
        super().__init__()
        self.win = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Database")
        title.setObjectName("h1")
        lay.addWidget(title)
        hint = QLabel("Step 1. Choose what the video is about. Click a row to see what it will cover, "
                      "then press OK to send it to Research. Researched ★ keeps everything you've researched: "
                      "open a video, or make another one from the same research.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        tabs = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.kind_buttons = {}
        for kind, name in TAB_NAMES.items():
            b = QPushButton(name)
            b.setCheckable(True)
            b.setObjectName("tab")
            b.setMinimumHeight(38)
            self.group.addButton(b)
            self.kind_buttons[kind] = b
            b.clicked.connect(lambda _=False, k=kind: self.set_kind(k))
            tabs.addWidget(b)
        tabs.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search...")
        self.search.setMinimumWidth(280)
        self.search.textChanged.connect(self.refresh)
        tabs.addWidget(self.search)
        lay.addLayout(tabs)

        split = QSplitter(Qt.Horizontal)
        self.table = table(["Name", "Claims", "With proof", "Careful"])
        self.table.itemSelectionChanged.connect(self._show)
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.breakdown = QTextBrowser()
        self.breakdown.setOpenExternalLinks(True)
        self.breakdown.document().setDefaultStyleSheet(f"a {{ color: {GOLD}; }} h3 {{ color: {GOLD}; }}")
        rl.addWidget(self.breakdown, 1)
        row = QHBoxLayout()
        self.ready = Chip()
        row.addWidget(self.ready)
        row.addStretch(1)
        self.ok = QPushButton("OK — research this  →")
        self.ok.setObjectName("primary")
        self.ok.setMinimumHeight(44)
        self.ok.clicked.connect(self._ok)
        self.ok.setEnabled(False)
        row.addWidget(self.ok)
        rl.addLayout(row)
        # the Researched tab's buttons
        self.res_box = QWidget()
        rb = QVBoxLayout(self.res_box)
        rb.setContentsMargins(0, 0, 0, 0)
        pick = QHBoxLayout()
        pick.addWidget(QLabel("Video:"))
        self.video_pick = QComboBox()
        self.video_pick.currentIndexChanged.connect(self._res_buttons)
        pick.addWidget(self.video_pick, 1)
        self.open_btn = QPushButton("Open this video  →")
        self.open_btn.setObjectName("primary")
        self.open_btn.setMinimumHeight(40)
        self.open_btn.clicked.connect(self._open_video)
        pick.addWidget(self.open_btn)
        rb.addLayout(pick)
        again = QHBoxLayout()
        self.new_ev_btn = QPushButton("New video: pick different evidence")
        self.new_ev_btn.setToolTip("Same research, nothing ticked. Tick other evidence (and dig deeper on it) "
                                   "for a new video on the same subject.")
        self.new_ev_btn.clicked.connect(lambda: self._new_from("evidence"))
        self.new_story_btn = QPushButton("New video: use another of its stories")
        self.new_story_btn.setToolTip("Same ticked evidence and the same three stories. Pick a story you "
                                      "haven't made yet.")
        self.new_story_btn.clicked.connect(lambda: self._new_from("story"))
        for b in (self.new_ev_btn, self.new_story_btn):
            b.setMinimumHeight(38)
            again.addWidget(b)
        rb.addLayout(again)
        rl.addWidget(self.res_box)
        self.res_box.setVisible(False)
        self._ok_row = [self.ready, self.ok]
        split.addWidget(right)
        split.setSizes([520, 760])
        lay.addWidget(split, 1)
        self.kind = "story"
        self._rows: list[dict] = []
        self._current = None
        self.kind_buttons["story"].setChecked(True)

    def set_episode(self, ep) -> None:  # the Database page doesn't depend on the episode
        pass

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.kind_buttons[kind].setChecked(True)
        self.refresh()

    def refresh(self) -> None:
        researched_tab = self.kind == "researched"
        self.res_box.setVisible(researched_tab)
        for w in self._ok_row:
            w.setVisible(not researched_tab)
        if researched_tab:
            self._rows = researched.listing(self.search.text())
            self.table.setHorizontalHeaderLabels(["Name", "Type", "Videos", "Evidence"])
            fill(self.table, [[r["title"], researched.KIND_NAMES.get(r["kind"], r["kind"]), r["videos"], r["evidence"]]
                              for r in self._rows])
            for col, width in enumerate((300, 90, 60)):
                self.table.setColumnWidth(col, width)
            self.video_pick.clear()
            self._res_buttons()
            self.breakdown.setHtml(f"<p style='color:{MUTED}'>Click a row to see the videos made from it.</p>"
                                   if self._rows else
                                   f"<p style='color:{MUTED}'>Nothing researched yet. Pick a story on the Stories "
                                   "tab and press OK. Research you do is kept here.</p>")
            return
        self.table.setHorizontalHeaderLabels(["Name", "Claims", "With proof", "Careful"])
        self._rows = subjects.listing(self.kind, self.search.text())
        fill(self.table, [[r["title"], r["claims"], r["sourced"], "yes" if r.get("careful") else ""]
                          for r in self._rows])
        for i, r in enumerate(self._rows):
            color_item(self.table, i, 2, GREEN if r["claims"] and r["sourced"] == r["claims"]
                       else GOLD if r["sourced"] else RED)
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(2)
        self.table.setColumnWidth(0, 340)
        if not self._rows:
            self.breakdown.setHtml(f"<p style='color:{MUTED}'>Nothing matches.</p>")

    def _show(self) -> None:
        r = self.table.currentRow()
        if not 0 <= r < len(self._rows):
            return
        row = self._rows[r]
        if self.kind == "researched":
            self.breakdown.setHtml(researched.detail_html(row["kind"], row["id"]))
            self.video_pick.blockSignals(True)
            self.video_pick.clear()
            for v in researched.videos_for(row["kind"], row["id"]):
                label = f"{v['project_id']}  {v['title'][:40]}  ({v['where']})"
                self.video_pick.addItem(label, v)
            self.video_pick.setCurrentIndex(self.video_pick.count() - 1)
            self.video_pick.blockSignals(False)
            self._res_buttons()
            return
        self._current = subjects.breakdown(self.kind, row["id"])
        self.breakdown.setHtml(subjects.breakdown_html(self._current))
        b = self._current
        if not b["claims"]:
            self.ready.set_status("failed", "No claims to research")
        elif b["unsourced"]:
            self.ready.set_status("awaiting_approval", f"{b['ready']} of {len(b['claims'])} claims have proof")
        else:
            self.ready.set_status("approved", "Every claim has proof on file")
        self.ok.setEnabled(bool(b["claims"]))

    def _ok(self) -> None:
        b = self._current
        if not b:
            return
        title = re.sub(r"\s*\(.*?\)", "", b["title"]).strip()
        self.ok.setEnabled(False)
        self.ok.setText("Creating episode...")
        try:
            ep = Episode.create(next_id(), title, b["id"] if self.kind == "story" else None, b["claim_ids"])
            db.execute("UPDATE project SET subject_type=?, subject_id=? WHERE project_id=?",
                       (self.kind, b["id"], ep.project_id))
        except (ValueError, KeyError) as exc:
            error(self, str(exc))
            return
        finally:
            self.ok.setText("OK — research this  →")
            self.ok.setEnabled(True)
        self.chosen.emit(ep.project_id, OPEN_RESEARCH)

    # ------------------------------------------------------------ Researched tab
    def _res_buttons(self) -> None:
        v = self.video_pick.currentData()
        self.open_btn.setEnabled(bool(v))
        self.new_ev_btn.setEnabled(bool(v and v["has_research"]))
        can_story = bool(v and v["stories"])
        self.new_story_btn.setEnabled(can_story)
        self.new_story_btn.setToolTip("Same ticked evidence and the same three stories. Pick a story you haven't "
                                      "made yet." if can_story else "This video has no stories written yet.")

    def _open_video(self) -> None:
        v = self.video_pick.currentData()
        if v:
            self.chosen.emit(v["project_id"], -1)

    def _new_from(self, mode: str) -> None:
        v = self.video_pick.currentData()
        if not v:
            return
        button = self.new_ev_btn if mode == "evidence" else self.new_story_btn
        button.setEnabled(False)
        try:
            ep = researched.new_video_from(v["project_id"], mode)
        except (ValueError, KeyError) as exc:
            error(self, str(exc))
            return
        finally:
            button.setEnabled(True)
        self.win.toast.show_message(f"{ep.project_id} started from {v['project_id']}'s research.")
        self.chosen.emit(ep.project_id, OPEN_RESEARCH if mode == "evidence" else OPEN_STORIES)
