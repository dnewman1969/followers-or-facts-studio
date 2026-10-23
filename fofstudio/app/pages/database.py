"""Database: pick what the video is about - a Story, a Conspiracy, a Person or an Organization -
read what it will cover, then press OK to send it to Research."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter,
                               QTextBrowser, QVBoxLayout, QWidget)

from ... import db, subjects
from ...episode import Episode, list_episodes
from ..common import GOLD, GREEN, MUTED, RED, color_item, error, fill, table
from ..widgets import Chip


class DatabasePage(QWidget):
    chosen = Signal(str)  # project_id of the new episode

    def __init__(self, window):
        super().__init__()
        self.win = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Database")
        title.setObjectName("h1")
        lay.addWidget(title)
        hint = QLabel("Step 1. Choose what the video is about. Click a row to see what it will cover, "
                      "then press OK to send it to Research.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        tabs = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.kind_buttons = {}
        for kind, name in subjects.KINDS.items():
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
        existing = [r["project_id"] for r in list_episodes()]
        n = 1
        while f"S01E{n:02d}" in existing:
            n += 1
        title = re.sub(r"\s*\(.*?\)", "", b["title"]).strip()
        self.ok.setEnabled(False)
        self.ok.setText("Creating episode...")
        try:
            ep = Episode.create(f"S01E{n:02d}", title, b["id"] if self.kind == "story" else None, b["claim_ids"])
            db.execute("UPDATE project SET subject_type=?, subject_id=? WHERE project_id=?",
                       (self.kind, b["id"], ep.project_id))
        except (ValueError, KeyError) as exc:
            error(self, str(exc))
            return
        finally:
            self.ok.setText("OK — research this  →")
            self.ok.setEnabled(True)
        self.chosen.emit(ep.project_id)
