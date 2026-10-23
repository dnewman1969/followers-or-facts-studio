"""Publish: the YouTube write-up (title, description with every proof link, thumbnail), then upload private."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from ... import pipeline
from ...config import settings
from ...util import read_json, write_json, write_text
from ..common import GOLD, GREEN, MUTED
from ..widgets import StagePage, click_feedback


class PublishPage(StagePage):
    TITLE = "Publish"
    HELP = ("Step 8. The write-up for YouTube: title, a description with every proof link and its permanent "
            "Wayback copy, chapters, the Knowledge Fight credit and a thumbnail with Owlbert. Edit anything, "
            "approve it, then Upload. Videos go up as PRIVATE; you make them public in YouTube Studio.")
    APPROVE_STAGE = "package"

    def __init__(self, window):
        super().__init__(window)
        row = QHBoxLayout()
        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Video title (up to 100 characters)")
        self.thumb_words = QLineEdit()
        self.thumb_words.setPlaceholderText("Up to 4 big words for the thumbnail")
        self.verdict = QComboBox()
        self.verdict.addItems(["FALSE", "MISLEADING", "UNPROVEN", "TRUE", ""])
        form.addRow("Title", self.title_edit)
        form.addRow("Thumbnail words", self.thumb_words)
        form.addRow("Verdict stamp", self.verdict)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(form)
        btns = QHBoxLayout()
        self.make_btn = QPushButton("Write it up")
        self.make_btn.setObjectName("primary")
        click_feedback(self.make_btn, self._make)
        self.save_btn = QPushButton("Save my edits")
        click_feedback(self.save_btn, self._save, "Saving...")
        btns.addWidget(self.make_btn)
        btns.addWidget(self.save_btn)
        btns.addStretch(1)
        ll.addLayout(btns)
        self.desc = QPlainTextEdit()
        ll.addWidget(QLabel("Description"))
        ll.addWidget(self.desc, 1)
        row.addWidget(left, 3)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Thumbnail"))
        self.thumb = QLabel()
        self.thumb.setFixedSize(480, 270)
        self.thumb.setStyleSheet("background:#0d0f15; border-radius:6px;")
        self.thumb.setAlignment(Qt.AlignCenter)
        rl.addWidget(self.thumb)
        self.upload_btn = QPushButton("Upload to YouTube (private)")
        self.upload_btn.setObjectName("primary")
        self.upload_btn.setMinimumHeight(44)
        click_feedback(self.upload_btn, self._upload)
        rl.addWidget(self.upload_btn)
        self.uploaded = QLabel("")
        self.uploaded.setOpenExternalLinks(True)
        self.uploaded.setWordWrap(True)
        rl.addWidget(self.uploaded)
        rl.addStretch(1)
        row.addWidget(right, 2)
        self.body.addLayout(row, 1)
        self._sig = None

    def _make(self) -> None:
        opts = {"verdict": self.verdict.currentText()}
        if self.title_edit.text().strip():
            opts["title"] = self.title_edit.text().strip()
        if self.thumb_words.text().strip():
            opts["thumbnail_text"] = self.thumb_words.text().strip()
        self.run_stage("package", opts, "Writing the YouTube write-up")

    def _save(self) -> None:
        meta = read_json(self.ep.path("publish", "metadata.json"))
        if not meta:
            return
        meta["title"] = self.title_edit.text().strip()[:100] or meta["title"]
        meta["description"] = self.desc.toPlainText().strip()[:5000]
        write_json(self.ep.path("publish", "metadata.json"), meta)
        write_text(self.ep.path("publish", "description.txt"), meta["description"])
        if self.stage_status("package")["status"] == "approved":
            self.ep.record("package", "awaiting_approval", "edited by hand")
        self.toast(f"Saved. Description is {len(meta['description'])} of 5,000 characters.")
        self.refresh()

    def _upload(self) -> None:
        if self.stage_status("package")["status"] != "approved":
            pipeline.approve(self.ep, "package")
        meta = read_json(self.ep.path("publish", "metadata.json")) or {}
        privacy = settings()["youtube"]["privacy"]
        if QMessageBox.question(self, "Upload to YouTube",
                                f"Upload \"{meta.get('title')}\" to your channel as {privacy.upper()}?") \
                != QMessageBox.Yes:
            return
        self.run_stage("upload", {}, "Uploading to YouTube")

    def refresh(self) -> None:
        super().refresh()
        if not self.ep:
            return
        busy = self.busy("package") or self.busy("upload")
        rendered = self.stage_status("render")["status"] == "approved"
        self.make_btn.setEnabled(rendered and not busy)
        meta = read_json(self.ep.path("publish", "metadata.json"))
        self.save_btn.setEnabled(bool(meta) and not busy)
        self.upload_btn.setEnabled(bool(meta) and not busy and
                                   self.stage_status("package")["status"] in ("approved", "awaiting_approval"))
        sig = str(meta.get("made_at") if meta else None) + str(self.ep.path("publish", "thumbnail.png").exists())
        if sig != self._sig:
            self._sig = sig
            if meta:
                self.title_edit.setText(meta["title"])
                self.desc.setPlainText(meta["description"])
            thumb = self.ep.path("publish", "thumbnail.png")
            if thumb.exists():
                self.thumb.setPixmap(QPixmap(str(thumb)).scaled(480, 270, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.thumb.setText("The thumbnail appears here")
        up = read_json(self.ep.path("publish", "upload.json"))
        if up:
            self.uploaded.setText(f"<span style='color:{GREEN}'>✔ Uploaded ({up['privacy']}):</span> "
                                  f"<a style='color:{GOLD}' href='https://youtu.be/{up['youtube_id']}'>"
                                  f"https://youtu.be/{up['youtube_id']}</a>")
        elif not rendered:
            self.uploaded.setText(f"<span style='color:{MUTED}'>Render and approve the final video first "
                                  "(Production page).</span>")
        else:
            self.uploaded.setText("")

    def watched(self) -> list[str]:
        return ["package", "upload", "render"]
