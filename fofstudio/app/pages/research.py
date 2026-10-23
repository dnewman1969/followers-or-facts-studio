"""Research: the agents dig up the proof. Watch the progress line; then tick what goes in the write-up."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSplitter,
                               QTableWidgetItem, QTextBrowser)

from ... import db, jobs
from ...stages import research as rs
from ...util import read_json
from ..common import GOLD, GREEN, MUTED, RED, table
from ..widgets import StagePage, click_feedback

TYPE_COLORS = {"court": "#e67e22", "gov": "#4aa3df", "wire": GREEN, "journalism": GREEN, "academic": "#9b59b6",
               "museum": "#9b59b6", "archive_audio": "#9b59b6", "other": MUTED}


class ResearchPage(StagePage):
    TITLE = "Research"
    HELP = ("Step 2. The research agents read the sources already on file, search the web, court records and "
            "government archives for more proof, and keep only quotes that appear word for word in the saved "
            "page. Every link gets a permanent Wayback Machine copy. Untick anything you don't want in the "
            "YouTube write-up, then approve.")
    APPROVE_STAGE = "research"

    def __init__(self, window):
        super().__init__(window)
        row = QHBoxLayout()
        self.depth = QComboBox()
        self.depth.addItem("Quick (about 5-10 minutes)", "quick")
        self.depth.addItem("Normal (about 15-30 minutes)", "normal")
        self.depth.addItem("Deep (an hour or more)", "deep")
        self.depth.setCurrentIndex(1)
        self.start = QPushButton("Start research")
        self.start.setObjectName("primary")
        self.start.setMinimumHeight(38)
        click_feedback(self.start, lambda: self.run_stage("research", {"depth": self.depth.currentData()},
                                                          "Research agents"))
        self.subject = QLabel("")
        self.subject.setObjectName("h2")
        row.addWidget(self.subject, 1)
        row.addWidget(QLabel("How deep"))
        row.addWidget(self.depth)
        row.addWidget(self.start)
        self.body.addLayout(row)
        # a big progress line right on the page, as well as the bar at the top
        self.live = QLabel("")
        self.live.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setStyleSheet(f"QProgressBar {{ background:#22263a; border:none; border-radius:6px; height:18px; "
                               f"color:white; text-align:center; }} QProgressBar::chunk {{ background:{GOLD}; "
                               "border-radius:6px; }")
        self.body.addWidget(self.live)
        self.body.addWidget(self.bar)
        split = QSplitter(Qt.Vertical)
        self.table = table(["Use", "ID", "Type", "Found by", "Title / quote", "Link", "Wayback copy"])
        self.table.itemChanged.connect(self._toggled)
        self.table.itemSelectionChanged.connect(self._detail)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.detail.document().setDefaultStyleSheet(f"a {{ color: {GOLD}; }}")
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setSizes([420, 160])
        self.body.addWidget(split, 1)
        self._rows: list[dict] = []
        self._filling = False
        self._sig = None

    def refresh(self) -> None:
        super().refresh()
        if not self.ep:
            self.subject.setText("Choose a story on the Database page first.")
            self.start.setEnabled(False)
            return
        proj = db.one("SELECT subject_type FROM project WHERE project_id=?", (self.ep.project_id,)) or {}
        self.subject.setText(f"{self.ep.project_id}: {self.ep.title}  ·  {len(self.ep.claim_ids)} claims")
        busy = self.busy("research")
        self.start.setEnabled(not busy)
        self.start.setText("Research again" if self.ep.path("research.json").exists() else "Start research")
        self._progress(busy)
        packet = read_json(self.ep.path("research.json")) or {}
        sig = str(packet.get("built_at")) + str(len(packet.get("evidence", [])))
        if sig != self._sig:
            self._sig = sig
            self._fill(packet.get("evidence", []))

    def _progress(self, busy: bool) -> None:
        job = next((j for j in jobs.jobs(30) if j["project_id"] == self.ep.project_id and j["stage"] == "research"
                    and j["status"] in ("running", "queued")), None)
        self.bar.setVisible(busy)
        self.live.setVisible(busy)
        if job:
            self.live.setText(f"<b style='color:{GOLD}'>●</b> {html.escape(job['progress'] or 'Starting the research agents...')}")
            if job["progress_pct"] is None:
                self.bar.setRange(0, 0)
            else:
                self.bar.setRange(0, 100)
                self.bar.setValue(int(job["progress_pct"]))

    def _fill(self, evidence: list[dict]) -> None:
        self._filling = True
        self._rows = evidence
        self.detail.setHtml("<p style='color:#8a8fa3'>Click a row to see the quote and its links.</p>"
                            if evidence else "")
        self.table.setRowCount(len(evidence))
        for r, e in enumerate(evidence):
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            use.setCheckState(Qt.Checked if e.get("include") else Qt.Unchecked)
            self.table.setItem(r, 0, use)
            text = f"“{e['quote']}”" if e["kind"] == "quote" else (e.get("title") or "")
            vals = [e["id"], e.get("type") or "", "agent" if e.get("found_by") == "agent" else "database",
                    text[:160], e.get("url") or "", e.get("archive_url") or ""]
            for c, v in enumerate(vals, 1):
                item = QTableWidgetItem(v)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if c == 2:
                    from PySide6.QtGui import QColor
                    item.setForeground(QColor(TYPE_COLORS.get(v, MUTED)))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(4, 420)
        self.table.setColumnWidth(5, 220)
        self._filling = False

    def _toggled(self, item) -> None:
        if self._filling or item.column() != 0:
            return
        e = self._rows[item.row()]
        rs.set_include(self.ep, e["id"], item.checkState() == Qt.Checked)

    def _detail(self) -> None:
        r = self.table.currentRow()
        if not 0 <= r < len(self._rows):
            return
        e = self._rows[r]
        esc = html.escape
        parts = [f"<h3>{esc(e.get('title') or e['id'])}</h3>",
                 f"<p>{esc(e.get('publisher') or '')} {esc(str(e.get('date') or ''))} · <b>{esc(e.get('type') or '')}</b>"
                 f" · found by {'the research agent' if e.get('found_by') == 'agent' else 'the database'}"
                 f" · claim {esc(e['claim_id'])}</p>"]
        if e.get("quote"):
            parts.append(f"<blockquote>“{esc(e['quote'])}”</blockquote>")
        if e.get("supports"):
            parts.append(f"<p><i>Shows:</i> {esc(e['supports'])}</p>")
        if e.get("url"):
            parts.append(f"<p><a href='{esc(e['url'])}'>{esc(e['url'])}</a></p>")
        if e.get("archive_url"):
            parts.append(f"<p>Permanent copy: <a href='{esc(e['archive_url'])}'>{esc(e['archive_url'])}</a></p>")
        self.detail.setHtml("".join(parts))

    def poll(self) -> None:
        super().poll()
        if self.ep and self.busy("research"):
            self._progress(True)
