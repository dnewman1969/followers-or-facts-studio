"""Script: Owlbert's narration, scene by scene, written from the chosen story. Edit freely."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton)

from ... import pipeline
from ...stages import research as rs
from ...stages import script as script_stage
from ...util import read_json, write_text
from ..common import GOLD, tint
from ..widgets import StagePage, click_feedback


class ScriptPage(StagePage):
    TITLE = "Script"
    HELP = ("Step 4. Owlbert's narration, written scene by scene from the story you chose, in the video's style. Every "
            "scene lists the proof it relies on. Change any words you like, press Save, and the checks run again.")
    APPROVE_STAGE = "script"
    CLEAR_STAGE = "script"

    def __init__(self, window):
        super().__init__(window)
        row = QHBoxLayout()
        self.minutes = QDoubleSpinBox()
        self.minutes.setRange(1, 30)
        self.minutes.setValue(8)
        self.minutes.setSuffix(" minutes")
        self.minutes.setToolTip("How long the video should be. Changing it updates the length check straight away.")
        self.minutes.valueChanged.connect(self._minutes_changed)
        self.direction = QLineEdit()
        self.direction.setPlaceholderText("Optional notes for the writer, e.g. 'shorter opening, more on the money'")
        self.write_btn = QPushButton("Write the script")
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
        self.repair_btn = QPushButton("Remove made-up IDs")
        self.repair_btn.setObjectName("primary")
        self.repair_btn.setToolTip("Take out claim/source IDs the AI invented and use the ticked evidence instead")
        self.repair_btn.clicked.connect(self._repair)
        self.repair_btn.hide()
        want.addWidget(self.repair_btn)
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.body.addWidget(self.editor, 1)
        save_row = QHBoxLayout()
        self.save_btn = QPushButton("Save my changes")
        click_feedback(self.save_btn, self._save, "Saving...")
        save_row.addWidget(self.save_btn)
        save_row.addStretch(1)
        self.body.addLayout(save_row)

    def _minutes_changed(self, value: float) -> None:
        if self.ep:
            self.ep.set_creative(minutes=float(value))
            super().refresh()   # re-run the checks (the length check uses this)

    def set_episode(self, ep) -> None:
        if ep:
            self.minutes.blockSignals(True)
            self.minutes.setValue(float(ep.creative().get("minutes", 8)))
            self.minutes.blockSignals(False)
        super().set_episode(ep)

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

    def _repair(self) -> None:
        notes = script_stage.repair(self.ep)
        self.ep.record("script", "awaiting_approval", "made-up IDs removed")
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
        if self.ep and not self.minutes.hasFocus():
            self.minutes.blockSignals(True)
            self.minutes.setValue(float(self.ep.creative().get("minutes", 8)))
            self.minutes.blockSignals(False)
        busy = self.busy("script")
        ok_to_write = bool(self.ep) and self.stage_status("stories")["status"] == "approved"
        self.write_btn.setEnabled(ok_to_write and not busy)
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
        invented = any("may have invented" in self.checks.item(i).text() for i in range(self.checks.count()))
        self.repair_btn.setVisible(bool(self.ep) and invented and not busy)

    def watched(self) -> list[str]:
        return ["script", "stories"]
