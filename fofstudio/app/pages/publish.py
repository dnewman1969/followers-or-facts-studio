"""Publish: the YouTube write-up (title, description with every proof link, thumbnail), then upload private."""

from __future__ import annotations

import time

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
        self.yt_state = QLabel("")
        self.yt_state.setWordWrap(True)
        self.yt_state.setTextFormat(Qt.RichText)
        rl.addWidget(self.yt_state)
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
        """Upload: signs in first if needed (a browser tab), writes it up if that hasn't been done, then
        uploads PRIVATE. Each step that can't go ahead says exactly why."""
        from ... import youtube
        st = youtube.status()
        if not st["libs"]:
            QMessageBox.warning(self, "Upload to YouTube", "The YouTube packages aren't installed. Close the Studio "
                                "and run Update Studio.cmd, then try again.")
            return
        if not st["client_file"]:
            QMessageBox.warning(self, "Upload to YouTube", "First make your free Google client file and choose it in "
                                "Settings → YouTube → Choose client file (docs/YOUTUBE.md, about 10 minutes). If you "
                                "already downloaded it, put client_secret....json in your Downloads folder and the "
                                "Studio will find it.")
            return
        if not st["signed_in"]:
            self._sign_in_then_upload()
            return
        meta = read_json(self.ep.path("publish", "metadata.json"))
        privacy = settings()["youtube"]["privacy"]
        title = (meta or {}).get("title") or self.ep.title
        if QMessageBox.question(self, "Upload to YouTube",
                                f"Upload \"{title}\" to {st['account']['title']} as {privacy.upper()}?") \
                != QMessageBox.Yes:
            return
        if not meta:   # not written up yet: write it up and upload in one go
            self.run_stage("autopublish", {}, "Writing it up and uploading to YouTube (private)")
            return
        if self.stage_status("package")["status"] != "approved":
            pipeline.approve(self.ep, "package")
        self.run_stage("upload", {}, "Uploading to YouTube")

    def _sign_in_then_upload(self) -> None:
        import threading

        from PySide6.QtCore import QTimer

        from ... import youtube
        self.yt_state.setText(f"<span style='color:{GOLD}'>A browser tab opened: pick the Google account that owns "
                              "the channel and allow access. The upload starts when you're back.</span>")
        self._signin: dict | None = None

        def work() -> None:
            try:
                self._signin = {"ok": youtube.sign_in()}
            except Exception as exc:  # noqa: BLE001 - shown on the page
                self._signin = {"error": str(exc)}
        threading.Thread(target=work, daemon=True).start()
        self._signin_timer = QTimer(self)

        def done() -> None:
            if self._signin is None:
                return
            self._signin_timer.stop()
            if "error" in self._signin:
                QMessageBox.warning(self, "Signing in to YouTube", f"Signing in didn't work:\n{self._signin['error']}")
                self.refresh()
                return
            self.refresh()
            self._upload()
        self._signin_timer.timeout.connect(done)
        self._signin_timer.start(500)

    def new_episode(self) -> None:
        super().new_episode()
        self.title_edit.clear()
        self.desc.clear()
        self.thumb_words.clear()
        self.thumb.clear()
        self.thumb.setText("The thumbnail appears here")
        self.uploaded.clear()

    def refresh(self) -> None:
        super().refresh()
        if not self.ep:
            return
        busy = self.busy("package") or self.busy("upload")
        rendered = self.stage_status("render")["status"] == "approved"
        self.make_btn.setEnabled(rendered and not busy)
        meta = read_json(self.ep.path("publish", "metadata.json"))
        self.save_btn.setEnabled(bool(meta) and not busy)
        self.upload_btn.setEnabled((bool(meta) or rendered) and not busy and not self.busy("autopublish"))
        self._show_youtube_state()
        sig = str(meta.get("made_at") if meta else None) + str(self.ep.path("publish", "thumbnail.png").exists())
        if sig != self._sig:
            self._sig = sig
            if meta:
                self.title_edit.setText(meta["title"])
                self.desc.setPlainText(meta["description"])
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

    def _show_youtube_state(self) -> None:
        from ... import youtube
        if getattr(self, "_yt_checked", 0) and time.time() - self._yt_checked < 20:
            return
        self._yt_checked = time.time()
        st = youtube.status()
        ok, no = f"<span style='color:{GREEN}'>✔</span>", f"<span style='color:#e06c5a'>✖</span>"
        acct = st["account"]
        self.yt_state.setText(
            f"{ok if st['libs'] else no} YouTube packages &nbsp; "
            f"{ok if st['client_file'] else no} Google client file &nbsp; "
            f"{ok if st['signed_in'] else no} "
            + (f"Signed in as <b>{acct['title']}</b>" if st["signed_in"] and acct else
               "Not signed in (Upload signs you in)"))

    def watched(self) -> list[str]:
        return ["package", "upload", "render", "autopublish"]
