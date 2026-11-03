"""The "Unreal guides..." window on the Storyboard page. Dave (2026-11-01): ran the script by hand, saw nothing.
Now it's one button: the Studio opens Unreal itself, runs the script, Unreal closes by itself, and the guides come
in. The window shows what Unreal is doing, and if it fails, why, in plain words (unreal_bridge.py). The guide
model for ComfyUI is downloaded from here too (guidemodel.py)."""

from __future__ import annotations

import threading

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout)

from .. import guidemodel
from .. import unreal_bridge as ub
from ..util import StageError
from .common import GREEN, MUTED, RED, error, open_path


class UnrealDialog(QDialog):
    got = Signal(int, int)
    finished_download = Signal(str, bool)
    bible_done = Signal(str)

    def __init__(self, parent, ep) -> None:
        super().__init__(parent)
        self.ep = ep
        self.setWindowTitle("Unreal guides")
        self.resize(680, 600)
        lay = QVBoxLayout(self)
        intro = QLabel("Unreal builds a rough 3D set for each place in this video and photographs it from six "
                       "angles. The Studio paints its pictures on top, so a place looks the same from shot to "
                       "shot and the camera angles really change. You don't need to do anything in Unreal.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)

        # 1. the guide model
        lay.addWidget(self._line())
        lay.addWidget(QLabel("<b>1. The guide model for ComfyUI</b> (once, about 2 GB)"))
        row = QHBoxLayout()
        self.model_note = QLabel("")
        self.model_note.setWordWrap(True)
        row.addWidget(self.model_note, 1)
        self.get_btn = QPushButton("Download it")
        self.get_btn.clicked.connect(self._download)
        row.addWidget(self.get_btn)
        lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.hide()
        lay.addWidget(self.bar)

        # 2. Unreal
        lay.addWidget(self._line())
        lay.addWidget(QLabel("<b>2. Make the guides</b>"))
        row = QHBoxLayout()
        self.go_btn = QPushButton("Make guides with Unreal")
        self.go_btn.setObjectName("primary")
        self.go_btn.clicked.connect(self._start)
        row.addWidget(self.go_btn, 1)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop)
        row.addWidget(self.stop_btn)
        lay.addLayout(row)
        self.status = QLabel("Unreal opens, works on its own (leave it be) and closes when it's finished. "
                             "The first time takes longest (10-20 minutes) while it prepares its shaders.")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("What Unreal is doing shows here.")
        lay.addWidget(self.details, 1)

        # 3.
        lay.addWidget(self._line())
        lay.addWidget(QLabel("<b>3. Then press Make pictures.</b> The guides are used by themselves."))
        self.counts = QLabel("")
        self.counts.setWordWrap(True)
        self.counts.setObjectName("muted")
        lay.addWidget(self.counts)

        row = QHBoxLayout()
        folder_btn = QPushButton("Open the Unreal folder")
        folder_btn.clicked.connect(lambda: (ub.folder().mkdir(parents=True, exist_ok=True), open_path(ub.folder())))
        row.addWidget(folder_btn)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

        self.got.connect(self._progress)
        self.bible_done.connect(self._bible_ready)
        self.finished_download.connect(self._downloaded)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(2000)
        self._model_state()
        self._tick()

    @staticmethod
    def _line() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        return f

    # ------------------------------------------------------------- the guide model
    def _model_state(self) -> None:
        if guidemodel.have():
            ok, why = guidemodel.comfy_ready()
            self.model_note.setText(f"<span style='color:{GREEN if ok else RED}'>Downloaded. {why}</span>")
            self.get_btn.setEnabled(False)
        elif guidemodel.target() is None:
            self.model_note.setText(f"<span style='color:{RED}'>Couldn't find ComfyUI's models folder. Settings "
                                    "&gt; paths &gt; comfyui_models: paste the folder that has checkpoints, vae, "
                                    "loras in it.</span>")
            self.get_btn.setEnabled(False)
        else:
            self.model_note.setText(f"Not downloaded yet. It goes in {guidemodel.target().parent}.")
            self.get_btn.setEnabled(True)

    def _download(self) -> None:
        self.get_btn.setEnabled(False)
        self.get_btn.setText("Downloading...")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.show()

        def work() -> None:
            try:
                guidemodel.download(lambda d, t: self.got.emit(d, t))
                self.finished_download.emit("Downloaded. Restart ComfyUI so it sees the new model.", True)
            except StageError as exc:
                self.finished_download.emit(str(exc), False)
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, done: int, total: int) -> None:
        if total:
            self.bar.setValue(int(done * 100 / total))
            self.bar.setFormat(f"{done // 1_000_000} of {total // 1_000_000} MB")

    def _downloaded(self, text: str, ok: bool) -> None:
        self.bar.hide()
        self.get_btn.setText("Download it")
        self._model_state()
        if not ok:
            error(self, text)
            self.get_btn.setEnabled(True)
        else:
            self.model_note.setText(f"<span style='color:{GREEN}'>{text}</span>")

    # ------------------------------------------------------------- Unreal
    def _start(self) -> None:
        if ub.needs_bible(self.ep):   # list the film's places first (about a minute), then start Unreal
            self._listing = True
            self.go_btn.setEnabled(False)
            self.status.setText("Listing the places in your script first (the film's bible, about a minute)...")

            def work() -> None:
                try:
                    ub.ensure_bible(self.ep)
                    self.bible_done.emit("")
                except StageError as exc:
                    self.bible_done.emit(str(exc))
            threading.Thread(target=work, daemon=True).start()
            return
        self._launch()

    def _bible_ready(self, problem: str) -> None:
        self._listing = False
        self.go_btn.setEnabled(True)
        if problem:
            self.status.setText("")
            error(self, problem)
            return
        self._launch()

    def _launch(self) -> None:
        try:
            r = ub.start(self.ep)
        except StageError as exc:
            error(self, str(exc))
            return
        self.details.clear()
        self.status.setText(f"Opening Unreal {r['version']} for {len(r['places'])} place(s)... Leave Unreal be; "
                            "it closes by itself.")
        self._tick()

    def _stop(self) -> None:
        ub.stop()
        self.status.setText("Stopped.")

    def _tick(self) -> None:
        busy = ub.running()
        self.go_btn.setEnabled(not busy and not getattr(self, "_listing", False))
        self.stop_btn.setEnabled(busy)
        if getattr(self, "_listing", False):
            return
        r = ub.check()
        if r["state"] == "running":
            mins = f" ({r['minutes']} min)" if r.get("minutes") else ""
            self.status.setText(f"Working{mins}: {r['text']}")
        elif r["state"] == "done":
            text = f"<span style='color:{GREEN}'>{r['text']} Now press Make pictures.</span>"
            if r["problems"]:
                text += "<br>Some angles didn't work (the others are fine):<br>" + "<br>".join(r["problems"][:6])
            self.status.setText(text)
        elif r["state"] == "failed":
            self.status.setText(f"<span style='color:{RED}'>{r['text']}</span>")
            if r.get("errors"):
                self.details.setPlainText("\n".join(r.get("log", [])) + "\n\nFrom Unreal's own log:\n" +
                                          "\n".join(r["errors"]))
                return
        if r.get("log") and r["state"] != "idle":
            self.details.setPlainText("\n".join(r["log"]))
        self.counts.setText("Guide pictures so far: " + ", ".join(
            f"{s['name']} {s['guides']}" for s in ub.status(self.ep)) if self.ep else "")

    def done(self, result: int) -> None:   # Unreal keeps working if the window is closed; it's checked next time
        self.timer.stop()
        super().done(result)


_ = MUTED
