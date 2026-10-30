"""Publish → Upload on YouTube: YouTube's own upload page, with everything one click away."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout)

from .. import publishkit
from ..util import StageError, reveal
from .common import GREEN, RED


def _open(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class PublishKitDialog(QDialog):
    """Upload in your own browser: everything one click away, then paste the link back."""

    def __init__(self, ep, parent=None):
        super().__init__(parent)
        self.ep = ep
        self.kit = publishkit.prepare(ep)
        self.setWindowTitle("Upload on YouTube")
        self.setMinimumWidth(760)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("<b>YouTube's upload page and the folder with the video are open.</b> Drag the video in, "
                           "then paste each part with the Copy buttons (the title is already copied: press Ctrl+V "
                           "in YouTube's Title box)."))
        h = QHBoxLayout()
        for text, fn in (("Open YouTube's upload page", lambda: _open(publishkit.UPLOAD_PAGE)),
                         ("Show the video file", lambda: reveal(self.kit["video"]))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        g = QGridLayout()
        for row, (name, key) in enumerate((("Title", "title"), ("Description", "description"), ("Tags", "tags"))):
            text = self.kit[key]
            if key == "tags":
                name = f"Tags ({self.kit['tag_count']})"
            prev = QLabel((text[:110] + "...") if len(text) > 110 else text)
            prev.setObjectName("muted")
            b = QPushButton(f"Copy {key}")
            b.clicked.connect(lambda _=False, k=key, n=name: self._copy(k, n))
            g.addWidget(QLabel(f"<b>{name}</b>"), row, 0)
            g.addWidget(prev, row, 1)
            g.addWidget(b, row, 2)
        v.addLayout(g)
        v.addWidget(QLabel("<b>Checklist</b><ol>" + "".join(f"<li>{c}</li>" for c in self.kit["checklist"]) + "</ol>"))
        h2 = QHBoxLayout()
        self.link = QLineEdit()
        self.link.setPlaceholderText("Paste the video's link here (e.g. https://youtu.be/...)")
        done = QPushButton("It's uploaded")
        done.setObjectName("primary")
        done.clicked.connect(self._done)
        h2.addWidget(self.link, 1)
        h2.addWidget(done)
        v.addLayout(h2)
        self.msg = QLabel("")
        v.addWidget(self.msg)
        _open(publishkit.UPLOAD_PAGE)
        reveal(self.kit["video"])
        QGuiApplication.clipboard().setText(self.kit["title"])

    def _copy(self, key: str, name: str) -> None:
        QGuiApplication.clipboard().setText(self.kit[key])
        self.msg.setText(f"<span style='color:{GREEN}'>{name} copied: paste it on YouTube's page (Ctrl+V).</span>")

    def _done(self) -> None:
        try:
            info = publishkit.record_upload(self.ep, self.link.text())
        except StageError as exc:
            self.msg.setText(f"<span style='color:{RED}'>{exc}</span>")
            return
        self.msg.setText(f"<span style='color:{GREEN}'>✔ Saved: {info['video_url']}</span>")
        self.accept()
