"""Script: Owlbert's narration, scene by scene, written from the chosen story. Edit freely."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton)

from ... import pipeline
from ...util import write_text
from ..widgets import StagePage, click_feedback


class ScriptPage(StagePage):
    TITLE = "Script"
    HELP = ("Step 4. Owlbert's narration, written from the story you chose. Every scene lists the proof it "
            "relies on. Change any words you like, press Save, and the checks run again.")
    APPROVE_STAGE = "script"

    def __init__(self, window):
        super().__init__(window)
        row = QHBoxLayout()
        self.minutes = QDoubleSpinBox()
        self.minutes.setRange(2, 20)
        self.minutes.setValue(8)
        self.minutes.setSuffix(" minutes")
        self.direction = QLineEdit()
        self.direction.setPlaceholderText("Optional notes for the writer, e.g. 'shorter opening, more on the money'")
        self.write_btn = QPushButton("Write the script")
        self.write_btn.setObjectName("primary")
        click_feedback(self.write_btn, self._write)
        row.addWidget(QLabel("Length"))
        row.addWidget(self.minutes)
        row.addWidget(self.direction, 1)
        row.addWidget(self.write_btn)
        self.body.addLayout(row)
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.body.addWidget(self.editor, 1)
        save_row = QHBoxLayout()
        self.save_btn = QPushButton("Save my changes")
        click_feedback(self.save_btn, self._save, "Saving...")
        save_row.addWidget(self.save_btn)
        save_row.addStretch(1)
        self.body.addLayout(save_row)

    def _write(self) -> None:
        opts = {"minutes": self.minutes.value()}
        if self.direction.text().strip():
            opts["direction"] = self.direction.text().strip()
        self.run_stage("script", opts, "Writing the script")

    def _save(self) -> None:
        write_text(self.ep.path("script.md"), self.editor.toPlainText())
        if self.stage_status("script")["status"] in ("approved", "reset", "rejected", "failed", "not_started"):
            self.ep.record("script", "awaiting_approval", "edited by hand")
        pipeline.invalidate_after(self.ep, "script")
        self.toast("Script saved. Checks updated.")
        self.refresh()

    def refresh(self) -> None:
        super().refresh()
        busy = self.busy("script")
        ok_to_write = bool(self.ep) and self.stage_status("stories")["status"] == "approved"
        self.write_btn.setEnabled(ok_to_write and not busy)
        self.save_btn.setEnabled(bool(self.ep) and not busy)
        self.editor.setReadOnly(busy)
        if self.ep and not self.editor.document().isModified() or busy:
            path = self.ep.path("script.md") if self.ep else None
            text = path.read_text(encoding="utf-8") if path and path.exists() else ""
            if busy:
                text = "Writing... watch the bar at the top."
            self.editor.setPlainText(text)
            self.editor.document().setModified(False)
        if self.ep and self.ep.path("script.md").exists():
            self.write_btn.setText("Write it again")

    def watched(self) -> list[str]:
        return ["script", "stories"]
