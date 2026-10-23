"""Storyboard: every shot the video needs, in order, scene by scene. Each shot shows the version that will be
used; click the little versions underneath to switch, untick a shot to leave it out, or remake it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ... import styles
from ...stages import storyboard as sb
from ..common import GOLD, MUTED, PANEL, RED
from ..widgets import StagePage, click_feedback

THUMB_W, THUMB_H = 240, 135
MINI_W, MINI_H = 74, 42
PER_ROW = 5
KIND_NAMES = {"broll": "Scene", "owl": "Owlbert", "caricature": "Caricature"}


def _pix(path, w, h) -> QPixmap:
    return QPixmap(str(path)).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class ShotTile(QFrame):
    def __init__(self, page: "StoryboardPage", shot: dict):
        super().__init__()
        self.page, self.shot = page, shot
        ep = page.ep
        use = not shot.get("skip")
        self.setStyleSheet(f"QFrame {{ background:#1b1e2b; border-radius:6px; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        kind = KIND_NAMES.get(shot["kind"], shot["kind"])
        color = {"owl": "#6b9bd8", "caricature": RED}.get(shot["kind"], MUTED)
        v.addWidget(QLabel(f"<b>{shot['shot_id'].split('-')[-1]}</b> <span style='color:{color}'>{kind}</span>"))
        pic = QLabel()
        pic.setFixedSize(THUMB_W, THUMB_H)
        pic.setAlignment(Qt.AlignCenter)
        pick = shot.get("pick", 0)
        c = shot["candidates"][pick] if pick < len(shot["candidates"]) else None
        pic.setStyleSheet(f"border:3px solid {GOLD if use else '#2c3046'}; border-radius:6px; background:#0d0f15;")
        if c and ep.abs(c["path"]).exists():
            pic.setPixmap(_pix(ep.abs(c["path"]), THUMB_W - 6, THUMB_H - 6))
            pic.setToolTip(c["prompt"])
        else:
            pic.setText("being painted..." if page.busy("storyboard") else "not made yet")
        v.addWidget(pic)
        minis = QHBoxLayout()
        for k, cand in enumerate(shot["candidates"]):
            b = QPushButton()
            b.setFixedSize(MINI_W + 6, MINI_H + 6)
            b.setToolTip(f"Use version {k + 1}")
            if cand and ep.abs(cand["path"]).exists():
                pm = _pix(ep.abs(cand["path"]), MINI_W, MINI_H)
                b.setIcon(QIcon(pm))
                b.setIconSize(pm.size())
            else:
                b.setText("…")
            b.setStyleSheet(f"border:2px solid {GOLD if k == pick else '#2c3046'}; border-radius:4px; padding:0;")
            b.clicked.connect(lambda _=False, kk=k: self._pick(kk))
            minis.addWidget(b)
        minis.addStretch(1)
        v.addLayout(minis)
        idea = QLabel(shot["idea"][:120])
        idea.setWordWrap(True)
        idea.setObjectName("muted")
        idea.setFixedWidth(THUMB_W)
        v.addWidget(idea)
        row = QHBoxLayout()
        box = QCheckBox("Use")
        box.setChecked(use)
        box.toggled.connect(self._use)
        remake = QPushButton("Remake")
        remake.setEnabled(not page.busy("storyboard"))
        remake.clicked.connect(self._remake)
        row.addWidget(box)
        row.addStretch(1)
        row.addWidget(remake)
        v.addLayout(row)

    def _changed(self) -> None:
        if self.page.ep.stage_status("storyboard")["status"] == "approved":
            self.page.ep.record("storyboard", "awaiting_approval", "shots changed")
        self.page.refresh_checks_only()

    def _pick(self, k: int) -> None:
        sb.set_pick(self.page.ep, self.shot["shot_id"], k)
        self.shot["pick"] = k
        self._changed()
        self.page.force_refresh()

    def _use(self, on: bool) -> None:
        sb.set_use(self.page.ep, self.shot["shot_id"], on)
        self.shot["skip"] = not on
        self._changed()

    def _remake(self) -> None:
        idea, ok = QInputDialog.getMultiLineText(self, "Remake shot", "Change the idea if you like, then OK to paint "
                                                 "every version of this shot again:", self.shot["idea"])
        if not ok:
            return
        sb.set_idea(self.page.ep, self.shot["shot_id"], idea.strip())
        self.page.run_stage("storyboard", {"remake": [self.shot["shot_id"]]}, f"Repainting {self.shot['shot_id']}")


class SceneRow(QFrame):
    def __init__(self, page: "StoryboardPage", scene: dict):
        super().__init__()
        self.page, self.scene = page, scene
        self.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:8px; }}")
        lay = QVBoxLayout(self)
        shots = scene.get("shots", [])
        used = sum(1 for s in shots if not s.get("skip"))
        head = QHBoxLayout()
        title = QLabel(f"<b style='color:{GOLD}'>{scene['scene_id']}</b> <span style='color:{MUTED}'>"
                       f"{scene.get('role', '')} · about {scene.get('seconds', 0):.0f} s · {used} of {len(shots)} "
                       f"shots used</span><br><span style='color:{MUTED}'>{scene['narration'][:260]}...</span>")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        replan = QPushButton("Plan this scene again")
        replan.setEnabled(not page.busy("storyboard"))
        replan.clicked.connect(lambda: page.run_stage("storyboard", {"replan": [scene["scene_id"]]},
                                                      f"Re-planning {scene['scene_id']}"))
        head.addWidget(replan)
        lay.addLayout(head)
        grid = QGridLayout()
        for i, shot in enumerate(shots):
            grid.addWidget(ShotTile(page, shot), i // PER_ROW, i % PER_ROW)
        lay.addLayout(grid)
        if scene.get("cards"):
            lay.addWidget(QLabel("<span style='color:%s'>Also shown automatically: %s</span>" % (
                MUTED, ", ".join(f"{c['type'].replace('_', ' ')} “{c['text'][:50]}”" for c in scene["cards"]))))


class OldSceneRow(QFrame):
    """A scene from an older storyboard (three pictures, ticked)."""

    def __init__(self, page, scene):
        super().__init__()
        self.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:8px; }}")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b style='color:{GOLD}'>{scene['scene_id']}</b> <span style='color:{MUTED}'>made "
                             "with the older storyboard; press Make pictures for the full set of shots</span>"))


class StoryboardPage(StagePage):
    TITLE = "Storyboard"
    HELP = ("Step 5. The program works out how many different pictures each scene needs to cover Owlbert's narration "
            "(so nothing repeats), the AI plans them in order, and ComfyUI paints a couple of versions of each. The "
            "gold one is used: click a small version to switch, untick a shot to leave it out, or remake it.")
    APPROVE_STAGE = "storyboard"

    def __init__(self, window):
        super().__init__(window)
        row = QHBoxLayout()
        self.style = QComboBox()
        for key, name in styles.choices():
            self.style.addItem(name, key)
        self.make_btn = QPushButton("Make pictures")
        self.make_btn.setObjectName("primary")
        click_feedback(self.make_btn, lambda: self.run_stage("storyboard", {"style": self.style.currentData()},
                                                             "Planning and painting every shot"))
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        row.addWidget(QLabel("Style"))
        row.addWidget(self.style)
        row.addWidget(self.make_btn)
        row.addWidget(self.summary, 1)
        self.body.addLayout(row)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body.addWidget(self.scroll, 1)
        self._sig = None

    def refresh_checks_only(self) -> None:
        super().refresh()

    def force_refresh(self) -> None:
        self._sig = None
        self.refresh()

    def refresh(self) -> None:
        super().refresh()
        busy = self.busy("storyboard")
        self.make_btn.setEnabled(bool(self.ep) and not busy and self.stage_status("script")["status"] == "approved")
        if self.ep:
            c = self.ep.creative()
            self.style.blockSignals(True)
            self.style.setCurrentIndex(max(0, self.style.findData(c["style"])))
            self.style.blockSignals(False)
        board = self.ep.storyboard() if self.ep else {}
        n = sum(len(s.get("shots", [])) for s in board.get("scenes", []))
        self.summary.setText(f"{n} shots planned" if n else "")
        sig = (busy, str(board))
        if sig == self._sig:
            return
        self._sig = sig
        holder = QWidget()
        v = QVBoxLayout(holder)
        for scene in board.get("scenes", []):
            v.addWidget(SceneRow(self, scene) if "shots" in scene else OldSceneRow(self, scene))
        if not board.get("scenes"):
            msg = QLabel("Planning and painting... the shots appear here as they finish." if busy else
                         "Press Make pictures. The program plans enough shots for the whole narration and paints each.")
            msg.setObjectName("muted")
            v.addWidget(msg)
        v.addStretch(1)
        pos = self.scroll.verticalScrollBar().value()
        self.scroll.setWidget(holder)
        self.scroll.verticalScrollBar().setValue(pos)

    def poll(self) -> None:
        super().poll()
        if self.ep and self.busy("storyboard"):
            self.refresh()  # show pictures as they come in

    def watched(self) -> list[str]:
        return ["storyboard", "script"]
