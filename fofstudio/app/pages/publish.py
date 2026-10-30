"""Publish: the YouTube write-up (title, description with every proof link, lots of search tags, thumbnail),
then upload on YouTube's own page in your browser (no Google setup)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from ...util import StageError, read_json, write_json, write_text
from ..common import GOLD, GREEN, MUTED
from ..widgets import StagePage, click_feedback


class PublishPage(StagePage):
    TITLE = "Publish"
    HELP = ("Step 8. The write-up for YouTube: title, a description with every proof link and its permanent "
            "Wayback copy, chapters, the Knowledge Fight credit, lots of search tags and a thumbnail with Owlbert. "
            "Edit anything, then Upload on YouTube: it opens YouTube's upload page with everything ready to paste. "
            "Upload it as Private, check YouTube's checks, then make it public.")
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
        self.tags_lab = QLabel("Search tags")
        ll.addWidget(self.tags_lab)
        self.tags = QPlainTextEdit()
        self.tags.setFixedHeight(70)
        self.tags.setPlaceholderText("Search tags, separated by commas (written for you by Write it up)")
        self.tags.setToolTip("What people type into YouTube's search to find this. YouTube allows 500 characters; "
                             "the most important go first. Keep them true and on topic: misleading tags count as "
                             "spam on YouTube.")
        self.tags.textChanged.connect(self._count_tags)
        ll.addWidget(self.tags)
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
        self.upload_btn = QPushButton("Upload on YouTube")
        self.upload_btn.setObjectName("primary")
        self.upload_btn.setMinimumHeight(44)
        self.upload_btn.setToolTip("Opens YouTube's upload page in your browser and the folder with the video, with "
                                   "Copy buttons for the title, description and tags. No Google setup.")
        click_feedback(self.upload_btn, self._browser_upload)
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
        from ...youtube import sanitize_tags
        meta["tags"] = sanitize_tags([t for t in self.tags.toPlainText().split(",")])
        write_json(self.ep.path("publish", "metadata.json"), meta)
        write_text(self.ep.path("publish", "description.txt"), meta["description"])
        if self.stage_status("package")["status"] == "approved":
            self.ep.record("package", "awaiting_approval", "edited by hand")
        self.toast(f"Saved. Description is {len(meta['description'])} of 5,000 characters.")
        self.refresh()

    def _browser_upload(self) -> None:
        from ..youtube_ui import PublishKitDialog
        meta = read_json(self.ep.path("publish", "metadata.json"))
        if not meta:
            if self.stage_status("render")["status"] != "approved":
                raise StageError("Render the final video first (Production page).")
            self.run_stage("package", {}, "Writing the YouTube write-up (then press Upload in my browser again)")
            return
        PublishKitDialog(self.ep, self).exec()
        self.refresh()

    def _count_tags(self) -> None:
        from ...youtube import TAG_LIMIT, tag_length
        tags = [" ".join(t.split()) for t in self.tags.toPlainText().split(",") if t.strip()]
        n = tag_length(tags)
        colour = "#e06c5a" if n > TAG_LIMIT else MUTED
        self.tags_lab.setText(f"Search tags <span style='color:{colour}'>{len(tags)} tags, {n} of {TAG_LIMIT} "
                              "characters" + (" (the extra ones are dropped when you save)" if n > TAG_LIMIT else "")
                              + "</span>")

    def new_episode(self) -> None:
        super().new_episode()
        self.title_edit.clear()
        self.desc.clear()
        self.tags.clear()
        self.thumb_words.clear()
        self.thumb.clear()
        self.thumb.setText("The thumbnail appears here")
        self.uploaded.clear()

    def refresh(self) -> None:
        super().refresh()
        if not self.ep:
            return
        busy = self.busy("package")
        rendered = self.stage_status("render")["status"] == "approved"
        self.make_btn.setEnabled(rendered and not busy)
        meta = read_json(self.ep.path("publish", "metadata.json"))
        self.save_btn.setEnabled(bool(meta) and not busy)
        self.upload_btn.setEnabled((bool(meta) or rendered) and not busy)
        sig = str(meta.get("made_at") if meta else None) + str(self.ep.path("publish", "thumbnail.png").exists())
        if sig != self._sig:
            self._sig = sig
            if meta:
                self.title_edit.setText(meta["title"])
                self.desc.setPlainText(meta["description"])
                self.tags.setPlainText(", ".join(meta.get("tags", [])))
            if not self.thumb_words.text().strip():
                from ...stages.stories import chosen
                self.thumb_words.setText((chosen(self.ep) or {}).get("thumbnail_words", ""))
            thumb = self.ep.path("publish", "thumbnail.png")
            if thumb.exists():
                self.thumb.setPixmap(QPixmap(str(thumb)).scaled(480, 270, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.thumb.setText("The thumbnail appears here")
        up = read_json(self.ep.path("publish", "upload.json"))
        if up:
            studio = up.get("studio_url") or f"https://studio.youtube.com/video/{up['youtube_id']}/edit"
            self.uploaded.setText(f"<span style='color:{GREEN}'>✔ Uploaded ({up['privacy']}):</span> "
                                  f"<a style='color:{GOLD}' href='https://youtu.be/{up['youtube_id']}'>"
                                  f"https://youtu.be/{up['youtube_id']}</a> &nbsp;·&nbsp; "
                                  f"<a style='color:{GOLD}' href='{studio}'><b>Review it in YouTube Studio</b></a> "
                                  "(copyright and ad-suitability checks, then make it public)")
            self.uploaded.setOpenExternalLinks(True)
        elif not rendered:
            self.uploaded.setText(f"<span style='color:{MUTED}'>Render and approve the final video first "
                                  "(Production page).</span>")
        else:
            self.uploaded.setText("")

    def watched(self) -> list[str]:
        return ["package", "upload", "render"]
