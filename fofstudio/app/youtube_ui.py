"""YouTube windows: "Set up YouTube, step by step" (Settings) and "Upload in my browser" (Publish)."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout)

from .. import publishkit, youtube
from ..util import StageError, reveal
from .common import GOLD, GREEN, MUTED, RED


def _open(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class SetupDialog(QDialog):
    """The one-time Google setup, one button per Google page, with checks where the Studio can check."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set up YouTube uploads (one time, about 10 minutes)")
        self.setMinimumWidth(820)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "<b>Why this is needed:</b> PowerDirector comes with its own Google-approved sign-in built in. A personal "
            "program can't borrow that, so you make your own (free, once). Do the steps in order; each button opens "
            "the right Google page in your browser. Sign in to Google with the account that owns your channel.<br>"
            f"<span style='color:{MUTED}'>No setup at all? Use Publish → <b>Upload in my browser</b> instead.</span>"))
        grid = QGridLayout()
        for n, (text, url) in enumerate(youtube.SETUP_LINKS, 1):
            lab = QLabel(f"<b>{n}.</b> {text}")
            lab.setWordWrap(True)
            b = QPushButton("Open this page")
            b.clicked.connect(lambda _=False, u=url: _open(u))
            grid.addWidget(lab, n, 0)
            grid.addWidget(b, n, 1)
        n = len(youtube.SETUP_LINKS) + 1
        self.file_lab = QLabel("")
        self.file_lab.setWordWrap(True)
        find = QPushButton("Find my client file")
        find.clicked.connect(self._find)
        grid.addWidget(QLabel(f"<b>{n}.</b> The Studio looks for the downloaded file (Downloads, Desktop...)"), n, 0)
        grid.addWidget(find, n, 1)
        grid.addWidget(self.file_lab, n + 1, 0, 1, 2)
        self.sign_lab = QLabel("")
        self.sign_lab.setWordWrap(True)
        sign = QPushButton("Sign in to YouTube")
        sign.setObjectName("primary")
        sign.clicked.connect(self._sign_in)
        grid.addWidget(QLabel(f"<b>{n + 2}.</b> Sign in. On Google's page: if it says 'Google hasn't verified this "
                              "app', press Advanced → Go to Followers or Facts Studio (it's your own app), and TICK "
                              "'Manage your YouTube videos'."), n + 2, 0)
        grid.addWidget(sign, n + 2, 1)
        grid.addWidget(self.sign_lab, n + 3, 0, 1, 2)
        v.addLayout(grid)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(close)
        v.addLayout(h)
        self._show()

    def _show(self) -> None:
        st = youtube.status()
        self.file_lab.setText(f"<span style='color:{GREEN}'>✔ Client file: {st['client_file']}</span>"
                              if st["client_file"] else f"<span style='color:{MUTED}'>No client file found yet.</span>")
        if st["signed_in"] and st["account"]:
            self.sign_lab.setText(f"<span style='color:{GREEN}'>✔ Signed in: {st['account']['title']}. Ready to "
                                  "upload.</span>")
        elif st.get("expired"):
            self.sign_lab.setText(f"<span style='color:{RED}'>{st['expired']}</span>")
        else:
            self.sign_lab.setText("")

    def _find(self) -> None:
        found = youtube.find_client_file()
        if not found:
            QMessageBox.information(self, "Client file", "No client file found in Downloads or on the Desktop yet. "
                                    "Do step 5 and press Download JSON, then press this button again.")
            return
        try:
            youtube.use_client_file(found)
        except StageError as exc:
            QMessageBox.warning(self, "Client file", str(exc))
        self._show()

    def _sign_in(self) -> None:
        self.sign_lab.setText(f"<span style='color:{GOLD}'>A browser tab opened: sign in there, then come back.</span>")
        QGuiApplication.processEvents()
        try:
            info = youtube.sign_in()
        except StageError as exc:
            self.sign_lab.setText(f"<span style='color:{RED}'>{exc}</span>")
            return
        except Exception as exc:  # noqa: BLE001 - shown in plain words
            self.sign_lab.setText(f"<span style='color:{RED}'>{youtube.explain(exc)}</span>")
            return
        self.sign_lab.setText(f"<span style='color:{GREEN}'>✔ Signed in: {info['title']}. Ready to upload.</span>")


class PublishKitDialog(QDialog):
    """Upload in your own browser: everything one click away, then paste the link back."""

    def __init__(self, ep, parent=None):
        super().__init__(parent)
        self.ep = ep
        self.kit = publishkit.prepare(ep)
        self.setWindowTitle("Upload in my browser")
        self.setMinimumWidth(760)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("<b>No Google setup needed.</b> The upload page and the folder with the video open; copy "
                           "each part in with the buttons and tick the boxes below as you go."))
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
            prev = QLabel((self.kit[key][:110] + "...") if len(self.kit[key]) > 110 else self.kit[key])
            prev.setObjectName("muted")
            b = QPushButton(f"Copy {name.lower()}")
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
