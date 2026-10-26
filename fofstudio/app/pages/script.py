"""Script: Owlbert's narration, scene by scene, written from the chosen story. Edit freely."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton)

from ... import filmstyles, pipeline
from ...stages import lengthscan
from ...stages import research as rs
from ...stages import script as script_stage
from ...util import read_json, write_text
from ..common import GOLD, tint
from ..creative import CreativePanel
from ..widgets import StagePage, click_feedback


class ScriptPage(StagePage):
    TITLE = "Script"
    HELP = ("Step 4. Choose the kind of video (genre) and the director's style, press Scan to work out how long the "
            "story needs, set your length, then Produce script: Owlbert's narration scene by scene, with the music "
            "and his moves. Every scene lists its proof. Change any words you like, press Save, and the checks run again. "
            "The video style (the look of the pictures) and caricatures are chosen here too.")
    APPROVE_STAGE = "script"
    CLEAR_STAGE = "script"

    def __init__(self, window):
        super().__init__(window)
        self.creative = CreativePanel(show=("style", "caricatures"))
        self.body.addWidget(self.creative)
        film = QHBoxLayout()
        self.genre = QComboBox()
        self.genre.setMinimumWidth(260)
        self.genre.setToolTip("The kind of video: changes the tone, pacing, the look of the pictures and the music. "
                              "The facts never change.")
        self.director = QComboBox()
        self.director.setMinimumWidth(330)
        self.director.setToolTip("The director's way of shooting: framing, camera moves, how long shots hold, "
                                 "transitions, music and silence. Described to the AI by its traits only.")
        self.genre.currentIndexChanged.connect(self._film_changed)
        self.director.currentIndexChanged.connect(self._film_changed)
        self.scan_btn = QPushButton("Scan the story")
        self.scan_btn.setToolTip("The local AI reads the story and the ticked evidence and works out how long the "
                                 "video needs to be to tell it properly (no padding)")
        click_feedback(self.scan_btn, lambda: self.run_stage("scan", {}, "Scanning the story for its length"))
        film.addWidget(QLabel("<b>Genre</b>"))
        film.addWidget(self.genre)
        film.addWidget(QLabel("<b>Director</b>"))
        film.addWidget(self.director)
        film.addWidget(self.scan_btn)
        film.addStretch(1)
        self.body.addLayout(film)
        self.film_blurb = QLabel("")
        self.film_blurb.setWordWrap(True)
        self.film_blurb.setObjectName("muted")
        self.body.addWidget(self.film_blurb)
        self.scan_text = QLabel("")
        self.scan_text.setWordWrap(True)
        self.scan_text.setStyleSheet(f"background:{tint(GOLD, 0.10)}; border:1px solid {GOLD}; border-radius:6px; "
                                     "padding:8px;")
        self.body.addWidget(self.scan_text)
        self._loading_film = False
        row = QHBoxLayout()
        self.minutes = QDoubleSpinBox()
        self.minutes.setRange(0.5, 150)
        self.minutes.setValue(8)
        self.minutes.setSuffix(" minutes")
        self.minutes.setToolTip("How long the video should be. Changing it updates the length check straight away.")
        self.minutes.valueChanged.connect(self._minutes_changed)
        self.direction = QLineEdit()
        self.direction.setPlaceholderText("Optional notes for the writer, e.g. 'shorter opening, more on the money'")
        self.write_btn = QPushButton("Produce script")
        self.write_btn.setObjectName("primary")
        click_feedback(self.write_btn, self._write)
        self.longer_btn = QPushButton("Make it longer")
        self.longer_btn.setToolTip("Rewrite only the scenes that are shorter than their share of the length")
        click_feedback(self.longer_btn, lambda: self.run_stage("script", {"expand": True, "minutes": self.minutes.value()},
                                                               "Lengthening the short scenes"))
        row.addWidget(QLabel("Length"))
        row.addWidget(self.minutes)
        row.addWidget(self.direction, 1)
        row.addWidget(self.longer_btn)
        row.addWidget(self.write_btn)
        self.body.addLayout(row)
        # the script uses evidence you haven't ticked
        want = QHBoxLayout()
        self.want_text = QLabel("")
        self.want_text.setWordWrap(True)
        self.want_text.setStyleSheet(f"background:{tint(GOLD, 0.16)}; border:1px solid {GOLD}; border-radius:6px; "
                                     "padding:8px; font-size:11pt;")
        self.want_show = QPushButton("Show me on Research")
        self.want_show.setMinimumHeight(40)
        self.want_show.clicked.connect(self._show_on_research)
        self.want_tick = QPushButton("Tick what the script needs")
        self.want_tick.setObjectName("primary")
        self.want_tick.setMinimumHeight(40)
        self.want_tick.clicked.connect(self._tick_wanted)
        want.addWidget(self.want_text, 1)
        want.addWidget(self.want_show)
        want.addWidget(self.want_tick)
        self.body.addLayout(want)
        self.repair_btn = QPushButton("Fix made-up IDs and quotes")
        self.repair_btn.setObjectName("primary")
        self.repair_btn.setToolTip("Take out claim/source IDs the AI invented and use the ticked evidence instead. "
                                   "Words in quote marks that are a verified quote get it listed; quote marks "
                                   "around anything else come off (it becomes a paraphrase).")
        self.repair_btn.clicked.connect(self._repair)
        self.repair_btn.hide()
        want.addWidget(self.repair_btn)
        self.repeat_btn = QPushButton("Fix repeats")
        self.repeat_btn.setToolTip("Rewrite only the sentences that say again what an earlier scene already said, "
                                   "with new details from that scene's facts")
        click_feedback(self.repeat_btn, lambda: self.run_stage("script", {"derepeat": True}, "Fixing repeats"))
        self.repeat_btn.hide()
        want.addWidget(self.repeat_btn)
        self.lookup_btn = QPushButton("Look these up")
        click_feedback(self.lookup_btn, self._lookup)
        self.lookup_btn.hide()
        want.addWidget(self.lookup_btn)
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.body.addWidget(self.editor, 1)
        save_row = QHBoxLayout()
        self.save_btn = QPushButton("Save my changes")
        click_feedback(self.save_btn, self._save, "Saving...")
        save_row.addWidget(self.save_btn)
        save_row.addStretch(1)
        self.body.addLayout(save_row)

    def _fill_film(self) -> None:
        c = self.ep.creative()
        self._loading_film = True
        self.genre.clear()
        for g in filmstyles.allowed_genres(bool(c.get("careful"))):
            self.genre.addItem(g.name, g.key)
            self.genre.setItemData(self.genre.count() - 1, f"{g.definition}\nSuits: {g.suits}\nAvoid: {g.avoid}", 3)
        self.genre.setCurrentIndex(max(0, self.genre.findData(c.get("genre") or filmstyles.DEFAULT_GENRE)))
        self.director.clear()
        self.director.addItem("No particular director", "")
        for d in filmstyles.allowed_directors(bool(c.get("careful"))):
            self.director.addItem(d.label, d.key)
            self.director.setItemData(self.director.count() - 1, f"{d.prompt}\nGood for: {d.topics}", 3)
        self.director.setCurrentIndex(max(0, self.director.findData(c.get("director") or "")))
        self._loading_film = False
        self._film_blurb()

    def _film_changed(self) -> None:
        if self._loading_film or not self.ep:
            return
        self.ep.set_creative(genre=self.genre.currentData() or filmstyles.DEFAULT_GENRE,
                             director=self.director.currentData() or "")
        self._film_blurb()

    def _film_blurb(self) -> None:
        g, d = filmstyles.chosen(self.ep.creative())
        parts = []
        if g:
            parts.append(f"<b>{g.name}:</b> {g.definition}")
        if d:
            parts.append(f"<b>{d.label}:</b> shots hold about {d.shot_seconds[0]}-{d.shot_seconds[1]} s. Good for "
                         f"{d.topics}")
        if self.ep.creative().get("careful"):
            parts.append("Careful topic: only the sober genres and styles are offered.")
        self.film_blurb.setText("<br>".join(parts))

    def _minutes_changed(self, value: float) -> None:
        if self.ep:
            self.ep.set_creative(minutes=float(value))
            super().refresh()   # re-run the checks (the length check uses this)

    def new_episode(self) -> None:
        super().new_episode()
        self.direction.clear()
        self.editor.clear()
        self.editor.document().setModified(False)
        self.scan_text.clear()

    def set_episode(self, ep) -> None:
        if ep:
            self.minutes.blockSignals(True)
            self.minutes.setValue(float(ep.creative().get("minutes", 8)))
            self.minutes.blockSignals(False)
        self.creative.set_episode(ep)
        super().set_episode(ep)
        if ep:
            self._fill_film()

    def _write(self) -> None:
        opts = {"minutes": self.minutes.value()}
        if self.direction.text().strip():
            opts["direction"] = self.direction.text().strip()
        self.run_stage("script", opts, "Writing the script")

    def _wanted(self) -> dict[str, list[str]]:
        return script_stage.wanted_unticked(self.ep) if self.ep and not self.busy("script") else {}

    def _show_wanted(self) -> None:
        w = self._wanted()
        for widget in (self.want_text, self.want_show, self.want_tick):
            widget.setVisible(bool(w))
        if not w:
            return
        ev = {e["id"]: e for e in (read_json(self.ep.path("research.json")) or {}).get("evidence", [])}
        names = "; ".join(f"“{(ev[i].get('title') or i)[:60]}” ({', '.join(scenes)})" for i, scenes in w.items())
        self.want_text.setText(f"<b>The script wants {len(w)} piece(s) of evidence you haven't ticked:</b> {names}. "
                               "Tick them so the script can use them, or edit those scenes.")

    def _tick_wanted(self) -> None:
        w = self._wanted()
        if not w:
            return
        rs.set_include(self.ep, list(w), True)
        self.toast(f"Ticked {len(w)} piece(s) of evidence on the Research page.")
        self.refresh()

    def _lookup(self) -> None:
        qs = (read_json(self.ep.path("script-questions.json")) or {}).get("questions", [])
        self.run_stage("lookup", {"questions": qs}, f"Looking up {len(qs)} question(s)")

    def _repair(self) -> None:
        notes = script_stage.repair(self.ep)
        self.ep.record("script", "awaiting_approval", "made-up IDs and quotes fixed")
        self.editor.document().setModified(False)
        self.toast("Fixed: " + ("; ".join(notes[:4]) if notes else "nothing needed changing") + ". Read those scenes "
                   "and approve.")
        self.refresh()

    def _show_on_research(self) -> None:
        self.win.nav.setCurrentRow(1)
        self.win.pages[1].show_wanted()

    def _save(self) -> None:
        write_text(self.ep.path("script.md"), self.editor.toPlainText())
        if self.stage_status("script")["status"] in ("approved", "reset", "rejected", "failed", "not_started"):
            self.ep.record("script", "awaiting_approval", "edited by hand")
        pipeline.invalidate_after(self.ep, "script")
        self.toast("Script saved. Checks updated.")
        self.refresh()

    def refresh(self) -> None:
        super().refresh()
        if self.ep and not self.creative.isAncestorOf(self.focusWidget() or self):
            self.creative.set_episode(self.ep)
        if self.ep and not self.minutes.hasFocus():
            self.minutes.blockSignals(True)
            self.minutes.setValue(float(self.ep.creative().get("minutes", 8)))
            self.minutes.blockSignals(False)
        busy = self.busy("script") or self.busy("scan")
        ok_to_write = bool(self.ep) and self.stage_status("stories")["status"] == "approved"
        self.write_btn.setEnabled(ok_to_write and not busy)
        self.scan_btn.setEnabled(ok_to_write and not busy)
        scan = lengthscan.load(self.ep) if self.ep else {}
        self.scan_text.setVisible(bool(scan))
        if scan:
            self.scan_text.setText(lengthscan.summary_html(scan) + "<br>Set the length you want, then press "
                                   "<b>Produce script</b>.")
        self.longer_btn.setEnabled(ok_to_write and not busy and bool(self.ep) and self.ep.path("script.md").exists())
        if self.ep:
            from ... import styles
            self.help.setText(self.HELP + f"  Style: {styles.get(self.ep.creative()['style']).name} (change it on "
                              "the Stories page).")
        self.save_btn.setEnabled(bool(self.ep) and not busy)
        self.editor.setReadOnly(busy)
        if self.ep and not self.editor.document().isModified() or busy:
            path = self.ep.path("script.md") if self.ep else None
            text = path.read_text(encoding="utf-8") if path and path.exists() else ""
            if busy:
                text = "Writing... watch the progress line above."
            self.editor.setPlainText(text)
            self.editor.document().setModified(False)
        if self.ep and self.ep.path("script.md").exists():
            self.write_btn.setText("Write it again")
        self._show_wanted()
        invented = any(("may have invented" in t or "doesn't match any verified quote" in t) for t in
                       (self.checks.item(i).text() for i in range(self.checks.count())))
        self.repair_btn.setVisible(bool(self.ep) and invented and not busy)
        repeats = any("Fix repeats" in self.checks.item(i).text() for i in range(self.checks.count()))
        self.repeat_btn.setVisible(bool(self.ep) and repeats and not busy)
        qs = (read_json(self.ep.path("script-questions.json")) or {}).get("questions", []) if self.ep else []
        self.lookup_btn.setVisible(bool(qs) and not busy and not self.busy("lookup"))
        self.lookup_btn.setText(f"Look these up ({len(qs)})")
        self.lookup_btn.setToolTip("Questions the writer couldn't answer from the research. The agents search for "
                                   "documents; finds arrive on the Research page as NEW and unticked:\n- "
                                   + "\n- ".join(q["question"] for q in qs))

    def watched(self) -> list[str]:
        return ["script", "stories", "scan", "lookup"]
