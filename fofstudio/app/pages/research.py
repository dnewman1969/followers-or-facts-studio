"""Research: choose how deep, press Start, watch the progress line. Then read the write-up of
each piece of evidence, tick the ones this video will use (nothing starts ticked), search the
list, and send the agents to dig deeper on anything you ticked."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QProgressBar, QSizePolicy,
                               QPushButton, QSplitter, QTableWidgetItem, QTextBrowser)

from ... import jobs, pipeline
from ...stages import research as rs
from ...stages import script as script_stage
from ...util import read_json
from ..common import GOLD, GREEN, MUTED, table, tint
from ..widgets import StagePage, click_feedback

TYPE_COLORS = {"court": "#e67e22", "gov": "#4aa3df", "wire": GREEN, "journalism": GREEN, "academic": "#9b59b6",
               "museum": "#9b59b6", "archive_audio": "#9b59b6", "other": MUTED}
TYPE_NAMES = {"court": "Court", "gov": "Government", "wire": "News wire", "journalism": "News", "academic": "Study",
              "museum": "Museum", "archive_audio": "Recording", "other": "Other web page", "kf_index": "Index"}
DEPTHS = [("Only the sources already on file (a few minutes)", "files"),
          ("Quick search (about 5-10 minutes)", "quick"),
          ("Normal search (about 15-30 minutes)", "normal"),
          ("Deep search (an hour or more)", "deep")]
HIGHLIGHT = QColor(212, 160, 23, 90)
SHOW = [("Show everything", "all"), ("Only what the script wants", "wanted"), ("Only ticked", "ticked"), ("Only new finds", "new"),
        ("Only quotes", "quote"), ("Only court and government", "official")]


class ResearchPage(StagePage):
    TITLE = "Research"
    HELP = ("Step 2. Choose how much time the research agents get, then press Start research. They read the "
            "sources on file, search the web, court records and government archives, keep only quotes found word "
            "for word, and save a permanent Wayback Machine copy of every link. Everything they find is saved in "
            "the database. Nothing is ticked to begin with: tick what this video will use.")
    APPROVE_STAGE = "research"
    SHOW_PROGRESS = False  # this page has its own progress line

    def __init__(self, window):
        super().__init__(window)
        self.subject = QLabel("")
        self.subject.setObjectName("h2")
        self.body.addWidget(self.subject)

        row = QHBoxLayout()
        row.addWidget(QLabel("Research time:"))
        self.depth = QComboBox()
        for label, key in DEPTHS:
            self.depth.addItem(label, key)
        self.depth.setCurrentIndex(2)
        self.depth.setMinimumWidth(330)
        row.addWidget(self.depth)
        self.start = QPushButton("Start research")
        self.start.setObjectName("primary")
        self.start.setMinimumHeight(40)
        click_feedback(self.start, self._start)
        row.addWidget(self.start)
        self.deeper = QPushButton("Dig deeper on ticked...")
        self.deeper.setMinimumHeight(40)
        self.deeper.setToolTip("Send the agents after more documents about the evidence you ticked.")
        self.deeper.clicked.connect(self._dig_deeper)
        row.addWidget(self.deeper)
        self.dive = QPushButton("Deep dive on weak claims")
        self.dive.setMinimumHeight(40)
        self.dive.setToolTip("For each ticked claim that doesn't hold up yet (no primary record, and fewer than two "
                             "independent sources with verified quotes): plan who/what/when/where questions and "
                             "search primary records first. Finds arrive NEW and unticked. Claims that still don't "
                             "hold up stay out of the script.")
        click_feedback(self.dive, lambda: self.run_stage("deepdive", {}, "Deep dive on the weak claims"))
        row.addWidget(self.dive)
        row.addStretch(1)
        self.body.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        self.hold = QLabel("")
        self.hold.setWordWrap(True)
        self.hold.setStyleSheet(f"background:{tint(GOLD, 0.12)}; border:1px solid {GOLD}; border-radius:6px; "
                                "padding:6px;")
        self.hold.hide()
        self.body.addWidget(self.hold)
        self.tick_dive = QPushButton("")
        self.tick_dive.setObjectName("primary")
        self.tick_dive.setToolTip("Tick everything the deep dive found (each quote was checked word for word against "
                                  "the saved page). Read them first if you like; untick any that are wrong.")
        self.tick_dive.clicked.connect(self._tick_dive)
        self.tick_dive.hide()
        self.body.addWidget(self.tick_dive)
        # the script uses evidence that isn't ticked: say so, and offer to tick it
        want = QHBoxLayout()
        self.want_text = QLabel("")
        self.want_text.setWordWrap(True)
        self.want_text.setStyleSheet(f"background:{tint(GOLD, 0.16)}; border:1px solid {GOLD}; border-radius:6px; "
                                     "padding:8px; font-size:11pt;")
        self.want_btn = QPushButton("Tick them for me")
        self.want_btn.setObjectName("primary")
        self.want_btn.setMinimumHeight(40)
        self.want_btn.clicked.connect(self._tick_wanted)
        want.addWidget(self.want_text, 1)
        want.addWidget(self.want_btn)
        self.body.addLayout(want)
        self._wanted: dict[str, list[str]] = {}

        # a big progress line right on the page, as well as the bar at the top
        self.live = QLabel("")
        self.live.setWordWrap(True)
        self.live.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.bar = QProgressBar()
        self.bar.setStyleSheet(f"QProgressBar {{ background:#22263a; border:none; border-radius:6px; height:18px; "
                               f"color:white; text-align:center; }} QProgressBar::chunk {{ background:{GOLD}; "
                               "border-radius:6px; }")
        self.body.addWidget(self.live)
        self.body.addWidget(self.bar)
        # the phases of the research, and a scrolling list of every step so far
        self.phases = QLabel("")
        self.phases.setWordWrap(True)
        self.body.addWidget(self.phases)
        self.steps = QListWidget()
        self.steps.setMaximumHeight(150)
        self.steps.setStyleSheet("QListWidget { background:#141722; border-radius:6px; font-size:10pt; }")
        self.body.addWidget(self.steps)
        self._steps_seen = 0

        filt = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a word to show only the evidence that mentions it...")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(34)
        self.search.textChanged.connect(self._apply_filter)
        filt.addWidget(self.search, 1)
        self.show_what = QComboBox()
        for label, key in SHOW:
            self.show_what.addItem(label, key)
        self.show_what.currentIndexChanged.connect(self._apply_filter)
        filt.addWidget(self.show_what)
        self.tick_all = QPushButton("Tick all shown")
        self.tick_all.clicked.connect(lambda: self._tick_shown(True))
        self.untick_all = QPushButton("Untick all shown")
        self.untick_all.clicked.connect(lambda: self._tick_shown(False))
        filt.addWidget(self.tick_all)
        filt.addWidget(self.untick_all)
        self.count = QLabel("")
        self.count.setMinimumWidth(170)
        filt.addWidget(self.count)
        self.body.addLayout(filt)

        split = QSplitter(Qt.Vertical)
        self.table = table(["Use", "", "Type", "Title", "What it shows", "Claim", "Found by"])
        self.table.itemChanged.connect(self._toggled)
        self.table.itemSelectionChanged.connect(self._detail)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.detail.document().setDefaultStyleSheet(f"a {{ color: {GOLD}; }} h3 {{ color: {GOLD}; }}")
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setSizes([400, 220])
        self.body.addWidget(split, 1)
        self._evidence: list[dict] = []
        self._shown: list[int] = []      # table row -> index in self._evidence
        self._filling = False
        self._sig = None

    # ------------------------------------------------------------ loading
    def new_episode(self) -> None:
        super().new_episode()
        self.search.clear()

    def refresh(self) -> None:
        if not self.ep:
            super().refresh()
            self.subject.setText("Choose a story on the Database page first.")
            for b in (self.start, self.deeper, self.dive):
                b.setEnabled(False)
            self.hold.hide()
            self._fill([])
            return
        busy = self.busy("research")
        st = self.stage_status("research")["status"]
        self._show_hold()
        if not busy and st != "approved":
            # list what's on file straight away (no internet), keeping your ticks
            rs.prepare(self.ep)
            if st == "not_started":
                self.ep.record("research", "awaiting_approval", "evidence on file listed")
        super().refresh()
        packet = read_json(self.ep.path("research.json")) or {}
        self.subject.setText(f"{self.ep.project_id}: {self.ep.title}  ·  {len(self.ep.claim_ids)} claims")
        self.start.setEnabled(not busy)
        self.start.setText("Research again" if packet.get("researched_at") else "Start research")
        if busy:
            self.status.setText("")
        elif not packet.get("researched_at"):
            self.status.setText(f"<span style='color:{GOLD}'><b>Choose how much research time, then press Start "
                                f"research.</b></span> The {len(packet.get('evidence', []))} pieces of evidence "
                                "already on file are listed below; you can tick from them now.")
        else:
            runs = packet.get("runs") or []
            last = runs[-1] if runs else {}
            self.status.setText(f"<span style='color:{GREEN}'>Researched.</span> The last run found "
                                f"{last.get('new_evidence', 0)} new pieces of evidence (marked NEW). It's all saved "
                                "in the database for any video on this subject.")
        self._progress(busy)
        wanted = script_stage.wanted_unticked(self.ep)
        sig = (packet.get("built_at"), len(packet.get("evidence", [])), tuple(sorted(wanted)))
        self._wanted = wanted
        self._show_wanted()
        if sig != self._sig:
            self._sig = sig
            self._fill(packet.get("evidence", []))
        self._update_count()

    def _show_wanted(self) -> None:
        w = self._wanted
        self.want_text.setVisible(bool(w))
        self.want_btn.setVisible(bool(w))
        if w:
            scenes = sorted({s for v in w.values() for s in v})
            self.want_text.setText(f"<b>The script uses {len(w)} piece(s) of evidence that aren't ticked</b> "
                                   f"(in {', '.join(scenes)}). They're highlighted in gold below. Tick them so the "
                                   "script can use them, or take them out of the script.")

    PHASES = [("Sources on file", ("Reading sources on file",)), ("Quotes", ("Finding quotes",)),
              ("Web, courts and news", ("Planning searches", "Searching", "Reading ")),
              ("Summaries", ("Writing a summary",)), ("Permanent copies", ("Wayback",)), ("Done", ("Done:",))]

    def _steps(self, busy: bool) -> None:
        """The scrolling list of research steps, and which phase it's in."""
        f = self.ep.path("logs", "research-steps.log")
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines() if f.exists() else []
        self.steps.setVisible(bool(lines))
        self.phases.setVisible(bool(lines))
        if len(lines) < self._steps_seen:      # a new run started
            self.steps.clear()
            self._steps_seen = 0
        for ln in lines[self._steps_seen:]:
            t, pct, text = (ln.split("\t", 2) + ["", ""])[:3]
            self.steps.addItem(f"{t}   {(pct + '%') if pct else '':>5}   {text}")
        if len(lines) > self._steps_seen:
            self.steps.scrollToBottom()
        self._steps_seen = len(lines)
        reached = -1
        for ln in lines:
            text = ln.split("\t", 2)[-1]
            for k, (_, keys) in enumerate(self.PHASES):
                if any(text.startswith(x) or x in text for x in keys):
                    reached = max(reached, k)
        parts = []
        for k, (name, _) in enumerate(self.PHASES):
            if k < reached or (k == reached and name == "Done"):
                parts.append(f"<span style='color:{GREEN}'>✔ {name}</span>")
            elif k == reached:
                parts.append(f"<b style='color:{GOLD}'>● {name}</b>" if busy else f"<span style='color:{GREEN}'>✔ {name}</span>")
            else:
                parts.append(f"<span style='color:{MUTED}'>○ {name}</span>")
        self.phases.setText(" &nbsp;→&nbsp; ".join(parts))

    def _progress(self, busy: bool) -> None:
        job = next((j for j in jobs.jobs(30) if j["project_id"] == self.ep.project_id and j["stage"] == "research"
                    and j["status"] in ("running", "queued")), None)
        self._steps(busy)
        self.bar.setVisible(busy)
        self.live.setVisible(busy)
        if job:
            self.live.setText(f"<b style='color:{GOLD}'>●</b> {html.escape(job['progress'] or 'Starting the research agents...')}")
            if job["progress_pct"] is None:
                self.bar.setRange(0, 0)
            else:
                self.bar.setRange(0, 100)
                self.bar.setValue(int(job["progress_pct"]))

    # ------------------------------------------------------------ the list
    def _fill(self, evidence: list[dict]) -> None:
        # new finds first, then quotes, then links; keep the order stable within each
        self._evidence = sorted(evidence, key=lambda e: (e["id"] not in self._wanted, not e.get("new"),
                                                         e["kind"] != "quote"))
        self._apply_filter()

    def _matches(self, e: dict) -> bool:
        show = self.show_what.currentData()
        if show == "wanted" and e["id"] not in self._wanted:
            return False
        if show == "ticked" and not e.get("include"):
            return False
        if show == "new" and not e.get("new"):
            return False
        if show == "quote" and e["kind"] != "quote":
            return False
        if show == "official" and e.get("type") not in ("court", "gov"):
            return False
        words = self.search.text().lower().split()
        if words:
            hay = " ".join(str(e.get(k) or "") for k in ("id", "title", "publisher", "date", "quote", "summary",
                                                           "supports", "claim", "claim_id", "url", "type")).lower()
            return all(w in hay for w in words)
        return True

    def _apply_filter(self) -> None:
        self._filling = True
        self._shown = [i for i, e in enumerate(self._evidence) if self._matches(e)]
        self.table.setRowCount(len(self._shown))
        for r, i in enumerate(self._shown):
            e = self._evidence[i]
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            use.setCheckState(Qt.Checked if e.get("include") else Qt.Unchecked)
            self.table.setItem(r, 0, use)
            title = (f"“{e['quote']}”" if e["kind"] == "quote" else "") or (e.get("title") or e["id"])
            shows = e.get("summary") or e.get("supports") or ""
            wanted = e["id"] in self._wanted and not e.get("include")
            vals = ["SCRIPT" if wanted else "NEW" if e.get("new") else "", TYPE_NAMES.get(e.get("type") or "", e.get("type") or ""),
                    title[:140], shows[:180], e.get("claim") or e["claim_id"],
                    "agent" if e.get("found_by") == "agent" else "database"]
            for c, v in enumerate(vals, 1):
                item = QTableWidgetItem(v)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setToolTip(v if c in (3, 4, 5) else "")
                if c == 1:
                    item.setForeground(QColor(GOLD))
                if c == 2:
                    item.setForeground(QColor(TYPE_COLORS.get(e.get("type") or "", MUTED)))
                if wanted:
                    item.setBackground(HIGHLIGHT)
                    item.setToolTip(f"The script uses this in {', '.join(self._wanted[e['id']])}. Tick it.")
                self.table.setItem(r, c, item)
            if wanted:
                use.setBackground(HIGHLIGHT)
        self.table.setColumnWidth(0, 44)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 380)
        self.table.setColumnWidth(4, 420)
        self.table.setColumnWidth(5, 220)
        self._filling = False
        if not self._shown:
            self.detail.setHtml(f"<p style='color:{MUTED}'>" + ("Nothing matches. Clear the search box or choose "
                                                                 "Show everything." if self._evidence else
                                                                 "No evidence yet. Press Start research.") + "</p>")
        else:
            self.detail.setHtml(f"<p style='color:{MUTED}'>Click a row to read what it is, what it shows, and its "
                                "links.</p>")
        self._update_count()

    def _show_hold(self) -> None:
        """Ticked claims that don't hold up (yet): they stay out of the script until a deep dive proves them."""
        from ...stages.script import left_out
        from ...util import read_json
        weak = left_out(self.ep) if self.ep.path("research.json").exists() else []
        dive = ((read_json(self.ep.path("claim-check.json"), {}) or {}).get("deep_dive") or {}).get("claims") or []
        busy = self.busy("deepdive") or self.busy("research") or self.busy("lookup")
        self.dive.setEnabled(bool(weak) and not busy)
        self.dive.setText(f"Deep dive on weak claims ({len(weak)})" if weak else "Deep dive on weak claims")
        evidence = {e["id"]: e for e in (read_json(self.ep.path("research.json"), {}) or {}).get("evidence", [])}
        untick = [i for d in dive for i in d.get("found") or [] if i in evidence and not evidence[i].get("include")]
        self._dive_ids = untick
        self.tick_dive.setVisible(bool(untick) and not busy)
        self.tick_dive.setText(f"Tick the {len(untick)} deep-dive find(s)")
        if not weak:
            self.hold.hide()
            return
        lines = [f"<b>{len(weak)} ticked claim(s) don't hold up yet, so they stay out of the script</b> (a claim needs "
                 "a primary record, or two independent sources with verified quotes):"]
        last = {d["claim_id"]: d for d in dive}
        for w in weak[:6]:
            note = f" Deep dive: {last[w['claim_id']]['result']}." if w["claim_id"] in last else ""
            lines.append(f"• {w['claim_id']} {w['title'][:70]}: {w['why']}.{note}")
        self.hold.setText("<br>".join(lines))
        self.hold.show()

    def _tick_dive(self) -> None:
        ids = list(getattr(self, "_dive_ids", []) or [])
        if ids:
            self._save_ticks(ids, True)
            self.toast(f"Ticked {len(ids)} deep-dive find(s). Claims they prove now hold up; write the script again.")
            self.refresh()

    def _update_count(self) -> None:
        ticked = sum(1 for e in self._evidence if e.get("include"))
        shown = len(self._shown)
        self.count.setText(f"<b>{ticked}</b> ticked · {shown} of {len(self._evidence)} shown")
        self.deeper.setEnabled(bool(self.ep) and ticked > 0 and not self.busy("research"))
        self.deeper.setText(f"Dig deeper on ticked ({ticked})..." if ticked else "Dig deeper on ticked...")

    def _save_ticks(self, ids: list[str], on: bool) -> None:
        rs.set_include(self.ep, ids, on)
        for e in self._evidence:
            if e["id"] in ids:
                e["include"] = on
        self._update_count()
        if self.stage_status("research")["status"] != "not_started":
            self.checks.set_checks(pipeline.checks(self.ep, "research"))

    def _tick_wanted(self) -> None:
        ids = list(self._wanted)
        self._save_ticks(ids, True)
        self._wanted = {}
        self._show_wanted()
        self._apply_filter()
        self.toast(f"Ticked {len(ids)} piece(s) of evidence the script uses. Go back to Script and approve.")

    def _toggled(self, item) -> None:
        if self._filling or item.column() != 0:
            return
        e = self._evidence[self._shown[item.row()]]
        self._save_ticks([e["id"]], item.checkState() == Qt.Checked)
        if e["id"] in self._wanted and item.checkState() == Qt.Checked:
            self._wanted = script_stage.wanted_unticked(self.ep)
            self._show_wanted()
            self._apply_filter()
        elif self.show_what.currentData() == "ticked":
            self._apply_filter()

    def _tick_shown(self, on: bool) -> None:
        if not self.ep or not self._shown:
            return
        self._save_ticks([self._evidence[i]["id"] for i in self._shown], on)
        self._apply_filter()
        self.toast(f"{'Ticked' if on else 'Unticked'} {len(self._shown)} pieces of evidence.")

    def show_wanted(self) -> None:
        """Called from the Script page: show only what the script wants."""
        self.show_what.setCurrentIndex(self.show_what.findData("wanted"))

    def _detail(self) -> None:
        r = self.table.currentRow()
        if not 0 <= r < len(self._shown):
            return
        e = self._evidence[self._shown[r]]
        esc = html.escape
        kind = TYPE_NAMES.get(e.get("type") or "", e.get("type") or "")
        parts = [f"<h3>{esc(e.get('title') or e['id'])}</h3>",
                 f"<p>{esc(e.get('publisher') or '')} {esc(str(e.get('date') or ''))} · <b>{esc(kind)}</b>"
                 + (f" · reliability {esc(e['reliability'])}" if e.get("reliability") else "")
                 + f" · found by {'the research agent' if e.get('found_by') == 'agent' else 'the database'}"
                 f" · {esc(e['id'])}</p>",
                 f"<p><b>Claim:</b> {esc(e.get('claim') or e['claim_id'])}</p>"]
        if e["id"] in self._wanted and not e.get("include"):
            parts.insert(1, f"<p style='color:{GOLD}'><b>The script uses this in "
                            f"{esc(', '.join(self._wanted[e['id']]))}. Tick it so it can.</b></p>")
        if e.get("summary"):
            parts.append(f"<p><b>What it is and what it shows:</b> {esc(e['summary'])}</p>")
        else:
            parts.append(f"<p style='color:{MUTED}'>No write-up yet. Start research (even 'Only the sources already "
                         "on file') to have the AI read it and write one.</p>")
        if e.get("quote"):
            parts.append(f"<p><b>Word-for-word quote:</b></p><blockquote>“{esc(e['quote'])}”</blockquote>")
        if e.get("supports") and e.get("supports") != e.get("summary"):
            parts.append(f"<p><i>Why it matters:</i> {esc(e['supports'])}</p>")
        if e.get("url"):
            parts.append(f"<p>Link: <a href='{esc(e['url'])}'>{esc(e['url'])}</a></p>")
        if e.get("archive_url"):
            parts.append(f"<p>Permanent copy: <a href='{esc(e['archive_url'])}'>{esc(e['archive_url'])}</a></p>")
        self.detail.setHtml("".join(parts))

    # ------------------------------------------------------------ actions
    def _start(self) -> None:
        depth = self.depth.currentData()
        label = "Reading the sources on file" if depth == "files" else "Research agents"
        self.run_stage("research", {"depth": depth}, label)

    def _dig_deeper(self) -> None:
        ids = [e["id"] for e in self._evidence if e.get("include")]
        if not ids:
            return
        notes, ok = QInputDialog.getMultiLineText(
            self, "Dig deeper",
            f"The agents will look for more documents about the {len(ids)} piece(s) of evidence you ticked,\n"
            f"using the research time chosen ({self.depth.currentText()}).\n\n"
            "Anything particular to look for? (optional)")
        if not ok:
            return
        depth = self.depth.currentData()
        self.run_stage("research", {"depth": "quick" if depth == "files" else depth, "focus": ids,
                                    "notes": notes.strip()}, f"Digging deeper on {len(ids)} piece(s) of evidence")

    def poll(self) -> None:
        super().poll()
        if self.ep and self.busy("research"):
            self._progress(True)

    def watched(self) -> list[str]:
        return ["research", "lookup", "deepdive"]
