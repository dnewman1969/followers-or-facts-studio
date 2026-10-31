"""The "Unreal guides..." window on the Storyboard page: three numbered steps, each with one button, so Unreal
Engine can build a rough 3D set for every place in this video and the Studio paints over it (unreal_bridge.py)."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLabel, QPushButton, QVBoxLayout

from .. import unreal_bridge as ub
from ..util import StageError
from .common import GREEN, MUTED, error, open_path

STEP2 = ("<b>2. In Unreal Engine</b> (any project, an empty one is fine):<br>"
         "&nbsp;&nbsp;• <i>First time only:</i> Edit &gt; Plugins &gt; search <b>Python</b> &gt; tick "
         "<b>Python Editor Script Plugin</b> &gt; restart Unreal.<br>"
         "&nbsp;&nbsp;• Tools &gt; <b>Execute Python Script...</b> &gt; pick <b>fof_unreal_guides.py</b> in the "
         "folder that just opened.<br>"
         "&nbsp;&nbsp;A progress bar shows while it builds and photographs each place (about a minute). "
         "It tidies up after itself and says <b>Done</b>. You don't have to save anything in Unreal.")


class UnrealDialog(QDialog):
    def __init__(self, parent, ep) -> None:
        super().__init__(parent)
        self.ep = ep
        self.setWindowTitle("Unreal guides")
        self.resize(640, 460)
        lay = QVBoxLayout(self)
        intro = QLabel("Unreal builds a rough 3D set for each place in this video and photographs it from six "
                       "angles. The Studio paints its pictures on top, so the rooms stay the same from shot to "
                       "shot and the camera angles really change.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)

        lay.addWidget(self._line())
        lay.addWidget(QLabel("<b>1. Make the job for Unreal</b>"))
        self.make_btn = QPushButton("Make the Unreal job and open its folder")
        self.make_btn.setObjectName("primary")
        self.make_btn.clicked.connect(self._make)
        lay.addWidget(self.make_btn)
        self.job_note = QLabel("")
        self.job_note.setWordWrap(True)
        lay.addWidget(self.job_note)

        lay.addWidget(self._line())
        step2 = QLabel(STEP2)
        step2.setWordWrap(True)
        lay.addWidget(step2)

        lay.addWidget(self._line())
        lay.addWidget(QLabel("<b>3. Back here</b>: just press <b>Make pictures</b>. The Studio picks up what "
                             "Unreal made by itself. Or check now:"))
        self.bring_btn = QPushButton("Bring in what Unreal made")
        self.bring_btn.clicked.connect(self._bring)
        lay.addWidget(self.bring_btn)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close)
        self._show_status()

    @staticmethod
    def _line() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        return f

    def _make(self) -> None:
        try:
            r = ub.prepare(self.ep)
        except StageError as exc:
            error(self, str(exc))
            return
        names = ", ".join(p["name"] or p["id"] for p in r["places"])
        self.job_note.setText(f"<span style='color:{GREEN}'>Ready: {len(r['places'])} place(s): {names}.</span><br>"
                              f"The file to run is <b>{r['script']}</b>")
        open_path(r["script"].parent)

    def _bring(self) -> None:
        self.bring_btn.setEnabled(False)
        self.bring_btn.setText("Bringing them in...")
        QApplication.processEvents()
        try:
            r = ub.bring_in()
        finally:
            self.bring_btn.setText("Bring in what Unreal made")
            self.bring_btn.setEnabled(True)
        if not r["made"] and not r["problems"]:
            self.status.setText(f"<span style='color:{MUTED}'>Nothing new from Unreal yet. Run step 2 first."
                                "</span><br>" + self._counts())
            return
        n = sum(len(v) for v in r["made"].values())
        text = f"<span style='color:{GREEN}'>Brought in {n} guide picture(s).</span>"
        if r["problems"]:
            text += "<br>Some angles didn't work (the others are fine):<br>" + "<br>".join(r["problems"][:6])
        self.status.setText(text + "<br>" + self._counts())

    def _counts(self) -> str:
        rows = ub.status(self.ep)
        if not rows:
            return ""
        return "<br>".join(f"{r['name']}: {r['guides']} guide picture(s)" for r in rows)

    def _show_status(self) -> None:
        c = self._counts()
        if c:
            self.status.setText("Guide pictures so far:<br>" + c)
